import os
import subprocess
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import models
import schemas


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


def compile_postgresql_table(table):
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))


class PostgreSQLModelTests(unittest.TestCase):
    def setUp(self):
        self.application = SimpleNamespace(
            id=1,
            app_id_str="app_20260903",
            applicant_name="Tom Miller",
            loan_type="Home Renovation",
            amount=Decimal("50000.00"),
            status="Pending",
            submitted_date=date(2026, 9, 3),
            validation_comments=None,
        )

    def test_application_amount_compiles_as_numeric_for_postgresql(self):
        ddl = compile_postgresql_table(models.Application.__table__)
        self.assertIn("NUMERIC(12, 2)", ddl)

    def test_agent_event_payload_compiles_as_jsonb(self):
        ddl = compile_postgresql_table(models.AgentEvent.__table__)
        self.assertIn("JSONB", ddl)

    def test_application_id_string_remains_unique(self):
        self.assertTrue(models.Application.__table__.c.app_id_str.unique)

    def test_api_keeps_date_and_amount_shape(self):
        response = schemas.Application.model_validate(self.application)
        self.assertEqual(response.submitted_date, "2026-09-03")
        self.assertEqual(response.amount, 50000.0)
        self.assertEqual(
            response.model_dump(mode="json")["submitted_date"],
            "2026-09-03",
        )
        self.assertEqual(response.model_dump(mode="json")["amount"], 50000.0)

    def test_user_detail_keeps_date_shape(self):
        response = schemas.UserDetail.model_validate(
            SimpleNamespace(
                id=1,
                username="tom",
                first_name="Tom",
                last_name="Miller",
                date_of_birth=date(1980, 1, 21),
            )
        )

        self.assertEqual(response.date_of_birth, "1980-01-21")
        self.assertEqual(
            response.model_dump(mode="json")["date_of_birth"],
            "1980-01-21",
        )

    def test_models_accept_existing_iso_date_api_inputs(self):
        user = models.User(date_of_birth="1980-01-21")
        application = models.Application(submitted_date="2026-09-03")

        self.assertEqual(user.date_of_birth, date(1980, 1, 21))
        self.assertEqual(application.submitted_date, date(2026, 9, 3))

    def test_tables_expose_the_required_columns_and_nullability(self):
        expected_columns = {
            "users": {
                "id": False,
                "username": False,
                "hashed_password": False,
                "first_name": False,
                "last_name": False,
                "date_of_birth": False,
            },
            "applications": {
                "id": False,
                "app_id_str": False,
                "applicant_name": False,
                "loan_type": False,
                "amount": False,
                "status": False,
                "submitted_date": False,
                "validation_comments": True,
                "validation_details": True,
                "input_snapshot": True,
                "owner_id": False,
                "created_at": False,
                "updated_at": False,
            },
            "application_documents": {
                "id": False,
                "application_id": False,
                "document_role": False,
                "original_filename": False,
                "cos_object_key": False,
                "content_type": True,
                "size_bytes": False,
                "sha256": False,
                "created_at": False,
            },
            "processing_runs": {
                "id": False,
                "application_id": False,
                "attempt_number": False,
                "status": False,
                "started_at": False,
                "finished_at": True,
                "error_text": True,
            },
            "agent_events": {
                "id": False,
                "application_id": True,
                "external_application_id": False,
                "stage": False,
                "occurred_at": False,
                "payload": False,
                "legacy_source_id": True,
            },
            "migration_anomalies": {
                "id": False,
                "kind": False,
                "external_application_id": False,
                "source_id": False,
                "details": False,
                "created_at": False,
            },
        }

        for table_name, expected in expected_columns.items():
            table = models.Base.metadata.tables[table_name]
            actual = {column.name: column.nullable for column in table.columns}
            self.assertEqual(actual, expected, table_name)

    def test_postgresql_ddl_uses_the_required_domain_types(self):
        expected_fragments = {
            "users": (
                "username VARCHAR(255) NOT NULL",
                "hashed_password TEXT NOT NULL",
                "date_of_birth DATE NOT NULL",
            ),
            "applications": (
                "app_id_str VARCHAR(64) NOT NULL",
                "loan_type VARCHAR(100) NOT NULL",
                "amount NUMERIC(12, 2) NOT NULL",
                "validation_details JSONB",
                "input_snapshot JSONB",
                "created_at TIMESTAMP WITH TIME ZONE NOT NULL",
            ),
            "application_documents": (
                "document_role VARCHAR(64) NOT NULL",
                "size_bytes BIGINT NOT NULL",
                "sha256 CHAR(64) NOT NULL",
            ),
            "processing_runs": (
                "attempt_number INTEGER NOT NULL",
                "finished_at TIMESTAMP WITH TIME ZONE",
                "error_text TEXT",
            ),
            "agent_events": (
                "external_application_id VARCHAR(64) NOT NULL",
                "occurred_at TIMESTAMP WITH TIME ZONE NOT NULL",
                "payload JSONB NOT NULL",
                "UNIQUE (legacy_source_id)",
            ),
            "migration_anomalies": (
                "kind VARCHAR(64) NOT NULL",
                "source_id VARCHAR(64) NOT NULL",
                "details TEXT NOT NULL",
                "UNIQUE (kind, source_id)",
            ),
        }

        for table_name, fragments in expected_fragments.items():
            ddl = compile_postgresql_table(models.Base.metadata.tables[table_name])
            for fragment in fragments:
                self.assertIn(fragment, ddl, table_name)

        agent_event_id = models.AgentEvent.__table__.c.id.type
        self.assertEqual(agent_event_id.compile(dialect=postgresql.dialect()), "BIGINT")

    def test_foreign_keys_target_the_required_parent_tables(self):
        expected_targets = {
            ("applications", "owner_id"): "users.id",
            ("application_documents", "application_id"): "applications.id",
            ("processing_runs", "application_id"): "applications.id",
            ("agent_events", "application_id"): "applications.id",
        }

        for (table_name, column_name), target in expected_targets.items():
            foreign_keys = models.Base.metadata.tables[table_name].c[column_name].foreign_keys
            self.assertEqual(
                {foreign_key.target_fullname for foreign_key in foreign_keys},
                {target},
            )

    def test_required_indexes_compile_for_postgresql(self):
        expected_indexes = {
            ("users", ("username",)),
            ("applications", ("app_id_str",)),
            ("applications", ("owner_id",)),
            ("application_documents", ("application_id",)),
            ("processing_runs", ("application_id",)),
            ("agent_events", ("external_application_id",)),
            ("agent_events", ("application_id", "occurred_at")),
        }
        actual_indexes = {}
        for table in models.Base.metadata.tables.values():
            for index in table.indexes:
                key = (table.name, tuple(column.name for column in index.columns))
                actual_indexes[key] = str(
                    CreateIndex(index).compile(dialect=postgresql.dialect())
                )

        self.assertTrue(expected_indexes.issubset(actual_indexes))
        for key in expected_indexes:
            self.assertIn("INDEX", actual_indexes[key])
        self.assertIn(
            "CREATE UNIQUE INDEX",
            actual_indexes[("users", ("username",))],
        )
        self.assertIn(
            "CREATE UNIQUE INDEX",
            actual_indexes[("applications", ("app_id_str",))],
        )

    def test_fastapi_import_does_not_create_database_tables(self):
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "startup.db"
            database_url = f"sqlite:///{database_path}"
            environment = os.environ.copy()
            environment["DATABASE_URL"] = database_url

            result = subprocess.run(
                [sys.executable, "-c", "import main"],
                cwd=BACKEND_DIRECTORY,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            engine = create_engine(database_url)
            try:
                self.assertEqual(inspect(engine).get_table_names(), [])
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
