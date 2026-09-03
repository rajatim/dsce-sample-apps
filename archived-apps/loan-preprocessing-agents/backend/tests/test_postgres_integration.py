import io
import os
import sys
import threading
import unittest
import uuid
from contextlib import redirect_stdout
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = BACKEND_DIRECTORY / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import bootstrap_local_postgres as bootstrap


class _MemoryPostgres:
    def __init__(self):
        self.roles = {}
        self.databases = {}
        self.commands = []
        self.connections = []

    def connect(self, _dsn, autocommit=False):
        connection = _MemoryConnection(self, autocommit)
        self.connections.append(connection)
        return connection


class _MemoryConnection:
    def __init__(self, server, autocommit):
        self.server = server
        self.autocommit = autocommit

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return _MemoryCursor(self.server)


class _MemoryCursor:
    def __init__(self, server):
        self.server = server
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, parameters=None):
        statement = query.as_string(None) if hasattr(query, "as_string") else query
        self.server.commands.append((statement, parameters))
        if statement == "SELECT 1 FROM pg_roles WHERE rolname = %s":
            self._result = (1,) if parameters[0] in self.server.roles else None
        elif statement.startswith("CREATE ROLE "):
            self.server.roles[statement.split('"')[1]] = None
        elif statement.startswith("ALTER ROLE "):
            if parameters:
                raise AssertionError(
                    "PostgreSQL ALTER ROLE utility statements cannot use bind parameters"
                )
            self.server.roles[statement.split('"')[1]] = statement.rsplit("'", 2)[1]
        elif statement == "SELECT 1 FROM pg_database WHERE datname = %s":
            self._result = (1,) if parameters[0] in self.server.databases else None
        elif statement.startswith("CREATE DATABASE "):
            quoted = statement.split('"')
            self.server.databases[quoted[1]] = quoted[3]
        elif statement.startswith("ALTER DATABASE "):
            quoted = statement.split('"')
            self.server.databases[quoted[1]] = quoted[3]
        else:
            raise AssertionError(f"unexpected PostgreSQL command: {statement}")

    def fetchone(self):
        return self._result


class BootstrapLocalPostgresTests(unittest.TestCase):
    def test_validate_name_accepts_postgresql_identifier_boundaries(self):
        self.assertEqual(bootstrap.validate_name("a", "LOAN_DB_NAME"), "a")
        self.assertEqual(
            bootstrap.validate_name("a" + "z" * 62, "LOAN_DB_NAME"),
            "a" + "z" * 62,
        )
        self.assertEqual(
            bootstrap.validate_name("loan_app_dev", "LOAN_DB_USER"),
            "loan_app_dev",
        )

    def test_validate_name_rejects_unsafe_postgresql_identifiers(self):
        for invalid_name in ("", "Loan", "1loan", "loan-name", "loan app", "a" * 64):
            with self.subTest(invalid_name=invalid_name):
                with self.assertRaises(ValueError):
                    bootstrap.validate_name(invalid_name, "LOAN_DB_NAME")

    def test_configuration_requires_an_environment_password(self):
        environment = {
            "LOAN_DB_NAME": "loan_poc_dev",
            "LOAN_DB_USER": "loan_app_dev",
        }

        with self.assertRaisesRegex(RuntimeError, "LOAN_DB_PASSWORD"):
            bootstrap.configuration_from_environment(environment)

    def test_bootstrap_creates_missing_role_and_database_without_printing_password(self):
        server = _MemoryPostgres()
        config = bootstrap.BootstrapConfiguration(
            admin_dsn="postgresql:///postgres",
            database_name="loan_poc_dev",
            database_user="loan_app_dev",
            database_password="test-local-password",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            bootstrap.bootstrap(config, connect=server.connect)

        self.assertEqual(server.roles, {"loan_app_dev": "test-local-password"})
        self.assertEqual(server.databases, {"loan_poc_dev": "loan_app_dev"})
        self.assertNotIn("test-local-password", output.getvalue())

    def test_bootstrap_rerun_updates_password_and_preserves_one_role_and_database(self):
        server = _MemoryPostgres()
        server.roles["loan_app_dev"] = "outdated-password"
        server.databases["loan_poc_dev"] = "another_owner"
        config = bootstrap.BootstrapConfiguration(
            admin_dsn="postgresql:///postgres",
            database_name="loan_poc_dev",
            database_user="loan_app_dev",
            database_password="replacement-password",
        )

        bootstrap.bootstrap(config, connect=server.connect)

        self.assertEqual(server.roles, {"loan_app_dev": "replacement-password"})
        self.assertEqual(server.databases, {"loan_poc_dev": "loan_app_dev"})
        self.assertFalse(
            any(command.startswith("CREATE ") for command, _ in server.commands)
        )

    def test_bootstrap_uses_autocommit_connection_for_database_creation(self):
        server = _MemoryPostgres()
        config = bootstrap.BootstrapConfiguration(
            admin_dsn="postgresql:///postgres",
            database_name="loan_poc_dev",
            database_user="loan_app_dev",
            database_password="test-local-password",
        )

        bootstrap.bootstrap(config, connect=server.connect)

        self.assertTrue(server.databases)
        self.assertTrue(server.connections[-1].autocommit)


class PostgreSQLIntegrationTargetSafetyTests(unittest.TestCase):
    def test_accepts_only_the_planned_loopback_database_targets(self):
        for database_url in (
            "postgresql+psycopg://loan_app_dev:test-password@127.0.0.1/loan_poc_dev",
            "postgresql://loan_app_dev:test-password@localhost:5432/loan_poc_dev",
            "postgresql://loan_app_dev:test-password@[::1]:5432/loan_poc_dev",
        ):
            with self.subTest(database_url=database_url):
                self.assertEqual(
                    validate_test_database_url(database_url).database,
                    "loan_poc_dev",
                )

    def test_rejects_remote_hosts_before_any_connection_can_be_created(self):
        with self.assertRaisesRegex(ValueError, "loopback") as raised:
            validate_test_database_url(
                "postgresql+psycopg://loan_app_dev:unsafe-password@db.example/loan_poc_dev"
            )

        self.assertNotIn("unsafe-password", str(raised.exception))
        self.assertNotIn("db.example", str(raised.exception))

    def test_rejects_a_different_database_name(self):
        with self.assertRaisesRegex(ValueError, "loan_poc_dev"):
            validate_test_database_url(
                "postgresql+psycopg://loan_app_dev:test-password@127.0.0.1/other_database"
            )

    def test_rejects_non_postgresql_urls(self):
        with self.assertRaisesRegex(ValueError, "PostgreSQL"):
            validate_test_database_url("sqlite:///loan_poc_dev.db")

    def test_rejects_nonstandard_ports(self):
        with self.assertRaisesRegex(ValueError, "5432"):
            validate_test_database_url(
                "postgresql+psycopg://loan_app_dev:test-password@127.0.0.1:6543/loan_poc_dev"
            )


def validate_test_database_url(database_url: str):
    """Reject integration targets outside the disposable local POC database."""
    try:
        parsed_url = make_url(database_url)
    except Exception as error:
        raise ValueError("TEST_DATABASE_URL must be a local PostgreSQL URL") from error

    if parsed_url.get_backend_name() != "postgresql":
        raise ValueError("TEST_DATABASE_URL must use PostgreSQL")
    if parsed_url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("TEST_DATABASE_URL must use a loopback host")
    if parsed_url.database != "loan_poc_dev":
        raise ValueError("TEST_DATABASE_URL must target loan_poc_dev")
    if parsed_url.port not in {None, 5432}:
        raise ValueError("TEST_DATABASE_URL must use port 5432")
    return parsed_url


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not configured")
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        local_database_url = validate_test_database_url(TEST_DATABASE_URL)
        cls.engine = create_engine(local_database_url)
        cls.Session = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def test_rollback_removes_inserted_row(self):
        username = f"rollback_{uuid.uuid4().hex}"
        with self.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, hashed_password, first_name, last_name, date_of_birth) "
                    "VALUES (:username, :password, :first_name, :last_name, :date_of_birth)"
                ),
                {
                    "username": username,
                    "password": "rollback-only",
                    "first_name": "Rollback",
                    "last_name": "Test",
                    "date_of_birth": date(1990, 1, 1),
                },
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT COUNT(*) FROM users WHERE username = :username"),
                    {"username": username},
                ).scalar_one(),
                1,
            )
            transaction.rollback()

        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT COUNT(*) FROM users WHERE username = :username"),
                    {"username": username},
                ).scalar_one(),
                0,
            )

    def test_concurrent_processing_runs_receive_consecutive_attempts(self):
        import repositories.application_records as application_records
        from models import Application, ProcessingRun, User

        suffix = uuid.uuid4().hex
        session = self.Session()
        try:
            owner = User(
                username=f"concurrent_owner_{suffix}",
                hashed_password="test-hash",
                first_name="Concurrent",
                last_name="Owner",
                date_of_birth=date(1990, 1, 1),
            )
            session.add(owner)
            session.flush()
            application = Application(
                app_id_str=f"concurrent_application_{suffix}",
                applicant_name="Concurrent Test",
                loan_type="Personal",
                amount=Decimal("100.00"),
                status="Pending",
                submitted_date=date(2026, 9, 3),
                owner_id=owner.id,
            )
            session.add(application)
            session.commit()
            application_id = application.id
            owner_id = owner.id
        finally:
            session.close()

        original_session_local = application_records.SessionLocal
        application_records.SessionLocal = self.Session
        barrier = threading.Barrier(3)
        run_ids = []
        errors = []
        result_lock = threading.Lock()

        def start_run():
            try:
                barrier.wait()
                run_id = application_records.start_processing_run(application_id)
                with result_lock:
                    run_ids.append(run_id)
            except BaseException as error:  # pragma: no cover - asserted below
                with result_lock:
                    errors.append(error)

        threads = [threading.Thread(target=start_run) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(set(run_ids)), 2)
            session = self.Session()
            try:
                attempts = session.query(ProcessingRun.attempt_number).filter(
                    ProcessingRun.application_id == application_id
                ).order_by(ProcessingRun.attempt_number).all()
                self.assertEqual([attempt for (attempt,) in attempts], [1, 2])
            finally:
                session.close()
        finally:
            application_records.SessionLocal = original_session_local
            session = self.Session()
            try:
                session.query(ProcessingRun).filter(
                    ProcessingRun.application_id == application_id
                ).delete(synchronize_session=False)
                session.query(Application).filter(Application.id == application_id).delete(
                    synchronize_session=False
                )
                session.query(User).filter(User.id == owner_id).delete(
                    synchronize_session=False
                )
                session.commit()
            finally:
                session.close()
