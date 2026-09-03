import json
import sqlite3
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from legacy_import.importer import import_snapshot
from legacy_import.reader import (
    LegacyEvent,
    LegacySnapshot,
    MigrationAnomaly as LegacyMigrationAnomaly,
)
from models import AgentEvent, Application, MigrationAnomaly, User


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
CLI_PATH = BACKEND_DIRECTORY / "scripts" / "migrate_legacy_data.py"


class LegacyImporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "target.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        with self.session_factory.begin() as session:
            session.add(
                User(
                    id=7,
                    username="unrelated-target-user",
                    hashed_password="unrelated-hash",
                    first_name="Unrelated",
                    last_name="User",
                    date_of_birth=date(1970, 1, 1),
                )
            )
        self.snapshot = self._snapshot()

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        self.temporary_directory.cleanup()

    @staticmethod
    def _snapshot():
        return LegacySnapshot(
            users=[
                {
                    "id": 7,
                    "username": "loan-user",
                    "hashed_password": "$legacy$hash-must-not-change",
                    "first_name": "Loan",
                    "last_name": "User",
                    "date_of_birth": "1980-01-21",
                }
            ],
            applications=[
                {
                    "id": 11,
                    "app_id_str": "known-app",
                    "applicant_name": "Loan User",
                    "loan_type": "Home Renovation",
                    "amount": 1234.5,
                    "status": "Approved AS-IS ",
                    "submitted_date": "2026-09-03",
                    "validation_comments": "validation stays exactly\nunchanged",
                    "owner_id": 7,
                },
                {
                    "id": 12,
                    "app_id_str": "other-app",
                    "applicant_name": "Loan User",
                    "loan_type": "Auto",
                    "amount": "30000.10",
                    "status": "pending",
                    "submitted_date": "2026-09-04",
                    "validation_comments": None,
                    "owner_id": 7,
                },
            ],
            events=[
                LegacyEvent(
                    source_id="1",
                    external_application_id="known-app",
                    stage="validation",
                    occurred_at=datetime(2026, 9, 3, 1, 2, 3, tzinfo=UTC),
                    payload={"valid": True},
                ),
                LegacyEvent(
                    source_id="2",
                    external_application_id="missing-app",
                    stage="tool_call",
                    occurred_at=datetime(2026, 9, 3, 2, 3, 4, tzinfo=UTC),
                    payload=[1, 2],
                ),
                LegacyEvent(
                    source_id="3",
                    external_application_id="missing-app",
                    stage="tool_response",
                    occurred_at=datetime(2026, 9, 3, 2, 3, 5, tzinfo=UTC),
                    payload={"message": "kept"},
                ),
            ],
            anomalies=[
                LegacyMigrationAnomaly(
                    kind="orphan_agent_event",
                    external_application_id="missing-app",
                    source_id="2",
                    details="No matching legacy application row",
                )
            ],
        )

    def _counts(self):
        with self.session_factory() as session:
            return {
                User: session.query(User).count(),
                Application: session.query(Application).count(),
                AgentEvent: session.query(AgentEvent).count(),
                MigrationAnomaly: session.query(MigrationAnomaly).count(),
            }

    def _seed_existing_application(self, *, owner_id=88, status="Approved AS-IS "):
        with self.session_factory.begin() as session:
            session.add(
                User(
                    id=88,
                    username="loan-user",
                    hashed_password="already-there",
                    first_name="Existing",
                    last_name="Owner",
                    date_of_birth=date(1981, 2, 3),
                )
            )
            session.add(
                Application(
                    app_id_str="known-app",
                    applicant_name="Loan User",
                    loan_type="Home Renovation",
                    amount=Decimal("1234.50"),
                    status=status,
                    submitted_date=date(2026, 9, 3),
                    validation_comments="validation stays exactly\nunchanged",
                    owner_id=owner_id,
                )
            )

    def test_dry_run_reports_seen_records_and_writes_nothing(self):
        report = import_snapshot(self.snapshot, self.session_factory, apply=False)

        self.assertEqual(report.users_seen, 1)
        self.assertEqual(report.applications_seen, 2)
        self.assertEqual(report.events_seen, 3)
        self.assertEqual(report.anomalies_seen, 1)
        self.assertEqual(report.total_inserted, 0)
        self.assertEqual(
            self._counts(),
            {User: 1, Application: 0, AgentEvent: 0, MigrationAnomaly: 0},
        )

    def test_apply_imports_all_records_with_explicit_field_mapping(self):
        report = import_snapshot(self.snapshot, self.session_factory, apply=True)

        self.assertEqual(report.users_inserted, 1)
        self.assertEqual(report.applications_inserted, 2)
        self.assertEqual(report.events_inserted, 3)
        self.assertEqual(report.anomalies_inserted, 1)
        with self.session_factory() as session:
            imported_user = session.query(User).filter_by(username="loan-user").one()
            application = (
                session.query(Application).filter_by(app_id_str="known-app").one()
            )
            linked_event = session.query(AgentEvent).filter_by(legacy_source_id="1").one()

            self.assertNotEqual(imported_user.id, 7)
            self.assertEqual(imported_user.hashed_password, "$legacy$hash-must-not-change")
            self.assertEqual(imported_user.date_of_birth, date(1980, 1, 21))
            self.assertEqual(application.owner_id, imported_user.id)
            self.assertEqual(application.amount, Decimal("1234.50"))
            self.assertEqual(application.submitted_date, date(2026, 9, 3))
            self.assertEqual(application.status, "Approved AS-IS ")
            self.assertEqual(
                application.validation_comments,
                "validation stays exactly\nunchanged",
            )
            self.assertEqual(linked_event.application_id, application.id)
            self.assertEqual(linked_event.payload, {"valid": True})

    def test_second_apply_is_idempotent_for_every_table(self):
        first = import_snapshot(self.snapshot, self.session_factory, apply=True)
        second = import_snapshot(self.snapshot, self.session_factory, apply=True)

        self.assertEqual(first.total_inserted, 7)
        self.assertEqual(second.users_inserted, 0)
        self.assertEqual(second.applications_inserted, 0)
        self.assertEqual(second.events_inserted, 0)
        self.assertEqual(second.anomalies_inserted, 0)
        self.assertEqual(second.total_inserted, 0)
        self.assertEqual(
            self._counts(),
            {User: 2, Application: 2, AgentEvent: 3, MigrationAnomaly: 1},
        )

    def test_orphan_events_are_preserved_without_multiplying_snapshot_anomalies(self):
        import_snapshot(self.snapshot, self.session_factory, apply=True)

        with self.session_factory() as session:
            orphan_events = (
                session.query(AgentEvent)
                .filter_by(external_application_id="missing-app")
                .order_by(AgentEvent.legacy_source_id)
                .all()
            )
            self.assertEqual(
                [event.legacy_source_id for event in orphan_events],
                ["2", "3"],
            )
            self.assertTrue(all(event.application_id is None for event in orphan_events))
            anomalies = session.query(MigrationAnomaly).all()
            self.assertEqual(len(anomalies), 1)
            self.assertEqual(
                (anomalies[0].kind, anomalies[0].source_id),
                ("orphan_agent_event", "2"),
            )

    def test_existing_username_is_reused_even_when_target_primary_key_differs(self):
        with self.session_factory.begin() as session:
            session.add(
                User(
                    id=88,
                    username="loan-user",
                    hashed_password="already-there",
                    first_name="Existing",
                    last_name="Owner",
                    date_of_birth=date(1981, 2, 3),
                )
            )

        report = import_snapshot(self.snapshot, self.session_factory, apply=True)

        self.assertEqual(report.users_inserted, 0)
        with self.session_factory() as session:
            owners = {
                application.owner_id
                for application in session.query(Application).all()
            }
            self.assertEqual(owners, {88})
            self.assertEqual(session.get(User, 88).hashed_password, "already-there")

    def test_existing_application_with_different_mapped_owner_aborts_apply(self):
        self._seed_existing_application(owner_id=7)

        with self.assertRaisesRegex(
            ValueError,
            "^target application conflicts with legacy app_id_str$",
        ):
            import_snapshot(self.snapshot, self.session_factory, apply=True)

        self.assertEqual(
            self._counts(),
            {User: 2, Application: 1, AgentEvent: 0, MigrationAnomaly: 0},
        )

    def test_existing_application_with_different_legacy_content_aborts_apply(self):
        self._seed_existing_application(status="target-only-sensitive-status")

        with self.assertRaisesRegex(
            ValueError,
            "^target application conflicts with legacy app_id_str$",
        ) as error:
            import_snapshot(self.snapshot, self.session_factory, apply=True)

        self.assertNotIn("target-only-sensitive-status", str(error.exception))
        self.assertEqual(
            self._counts(),
            {User: 2, Application: 1, AgentEvent: 0, MigrationAnomaly: 0},
        )

    def test_existing_event_with_different_content_rolls_back_prior_inserts(self):
        import_snapshot(self.snapshot, self.session_factory, apply=True)
        with self.session_factory.begin() as session:
            event = session.query(AgentEvent).filter_by(legacy_source_id="1").one()
            event.stage = "target-only-sensitive-stage"
        late_application = dict(self.snapshot.applications[1])
        late_application["id"] = 13
        late_application["app_id_str"] = "late-app"
        expanded_snapshot = replace(
            self.snapshot,
            applications=[*self.snapshot.applications, late_application],
        )

        with self.assertRaisesRegex(
            ValueError,
            "^target event conflicts with legacy_source_id$",
        ) as error:
            import_snapshot(expanded_snapshot, self.session_factory, apply=True)

        self.assertNotIn("target-only-sensitive-stage", str(error.exception))
        with self.session_factory() as session:
            self.assertIsNone(
                session.query(Application).filter_by(app_id_str="late-app").one_or_none()
            )
        self.assertEqual(
            self._counts(),
            {User: 2, Application: 2, AgentEvent: 3, MigrationAnomaly: 1},
        )

    def test_duplicate_snapshot_username_with_conflicting_hash_is_rejected(self):
        duplicate_user = dict(self.snapshot.users[0])
        duplicate_user["hashed_password"] = "duplicate-user-sensitive-hash"
        conflicting_snapshot = replace(
            self.snapshot,
            users=[self.snapshot.users[0], duplicate_user],
        )

        with self.assertRaisesRegex(
            ValueError,
            "^conflicting legacy user for username$",
        ) as error:
            import_snapshot(conflicting_snapshot, self.session_factory, apply=False)

        self.assertNotIn("duplicate-user-sensitive-hash", str(error.exception))
        self.assertEqual(
            self._counts(),
            {User: 1, Application: 0, AgentEvent: 0, MigrationAnomaly: 0},
        )

    def test_duplicate_snapshot_application_with_conflicting_content_is_rejected(self):
        duplicate_application = dict(self.snapshot.applications[0])
        duplicate_application["status"] = "duplicate-app-sensitive-status"
        conflicting_snapshot = replace(
            self.snapshot,
            applications=[self.snapshot.applications[0], duplicate_application],
        )

        with self.assertRaisesRegex(
            ValueError,
            "^conflicting legacy application for app_id_str$",
        ) as error:
            import_snapshot(conflicting_snapshot, self.session_factory, apply=False)

        self.assertNotIn("duplicate-app-sensitive-status", str(error.exception))
        self.assertEqual(
            self._counts(),
            {User: 1, Application: 0, AgentEvent: 0, MigrationAnomaly: 0},
        )

    def test_duplicate_snapshot_application_is_converted_before_deduplication(self):
        duplicate_application = dict(self.snapshot.applications[0])
        duplicate_application["submitted_date"] = "duplicate-invalid-date-secret"
        invalid_snapshot = replace(
            self.snapshot,
            applications=[self.snapshot.applications[0], duplicate_application],
        )

        with self.assertRaisesRegex(ValueError, "^invalid legacy ISO date$") as error:
            import_snapshot(invalid_snapshot, self.session_factory, apply=False)

        self.assertNotIn("duplicate-invalid-date-secret", str(error.exception))

    def test_duplicate_snapshot_event_with_conflicting_payload_is_rejected(self):
        duplicate_event = replace(
            self.snapshot.events[0],
            payload={"sensitive": "duplicate-event-payload"},
        )
        conflicting_snapshot = replace(
            self.snapshot,
            events=[self.snapshot.events[0], duplicate_event],
        )

        with self.assertRaisesRegex(
            ValueError,
            "^conflicting legacy event for legacy_source_id$",
        ) as error:
            import_snapshot(conflicting_snapshot, self.session_factory, apply=False)

        self.assertNotIn("duplicate-event-payload", str(error.exception))
        self.assertEqual(
            self._counts(),
            {User: 1, Application: 0, AgentEvent: 0, MigrationAnomaly: 0},
        )

    def test_existing_event_treats_integer_and_float_json_numbers_as_equal(self):
        integer_event = replace(self.snapshot.events[0], payload={"number": 1})
        first_snapshot = replace(
            self.snapshot,
            events=[integer_event],
            anomalies=[],
        )
        import_snapshot(first_snapshot, self.session_factory, apply=True)
        float_event = replace(integer_event, payload={"number": 1.0})
        second_snapshot = replace(first_snapshot, events=[float_event])

        report = import_snapshot(second_snapshot, self.session_factory, apply=True)

        self.assertEqual(report.events_inserted, 0)
        with self.session_factory() as session:
            self.assertEqual(session.query(AgentEvent).count(), 1)

    def test_duplicate_snapshot_event_deduplicates_equal_json_numbers(self):
        integer_event = replace(self.snapshot.events[0], payload={"number": 1})
        float_event = replace(integer_event, payload={"number": 1.0})
        duplicate_snapshot = replace(
            self.snapshot,
            events=[integer_event, float_event],
            anomalies=[],
        )

        report = import_snapshot(duplicate_snapshot, self.session_factory, apply=True)

        self.assertEqual(report.events_seen, 2)
        self.assertEqual(report.events_inserted, 1)
        with self.session_factory() as session:
            self.assertEqual(session.query(AgentEvent).count(), 1)

    def test_duplicate_snapshot_event_keeps_boolean_distinct_from_number(self):
        boolean_event = replace(self.snapshot.events[0], payload={"value": True})
        number_event = replace(boolean_event, payload={"value": 1})
        conflicting_snapshot = replace(
            self.snapshot,
            events=[boolean_event, number_event],
        )

        with self.assertRaisesRegex(
            ValueError,
            "^conflicting legacy event for legacy_source_id$",
        ):
            import_snapshot(conflicting_snapshot, self.session_factory, apply=False)

    def test_duplicate_snapshot_event_keeps_array_order_significant(self):
        forward_event = replace(self.snapshot.events[0], payload=[1, 2])
        reverse_event = replace(forward_event, payload=[2, 1])
        conflicting_snapshot = replace(
            self.snapshot,
            events=[forward_event, reverse_event],
        )

        with self.assertRaisesRegex(
            ValueError,
            "^conflicting legacy event for legacy_source_id$",
        ):
            import_snapshot(conflicting_snapshot, self.session_factory, apply=False)

    def test_duplicate_snapshot_event_ignores_object_key_order(self):
        first_event = replace(
            self.snapshot.events[0],
            payload={"outer": {"alpha": 1, "beta": 2}},
        )
        reordered_event = replace(
            first_event,
            payload={"outer": {"beta": 2, "alpha": 1}},
        )
        duplicate_snapshot = replace(
            self.snapshot,
            events=[first_event, reordered_event],
            anomalies=[],
        )

        report = import_snapshot(duplicate_snapshot, self.session_factory, apply=True)

        self.assertEqual(report.events_inserted, 1)
        with self.session_factory() as session:
            self.assertEqual(session.query(AgentEvent).count(), 1)

    def test_invalid_conversion_rolls_back_the_whole_apply(self):
        invalid_application = dict(self.snapshot.applications[1])
        invalid_application["submitted_date"] = "not-an-iso-date"
        invalid_snapshot = replace(
            self.snapshot,
            applications=[self.snapshot.applications[0], invalid_application],
        )

        with self.assertRaises(ValueError):
            import_snapshot(invalid_snapshot, self.session_factory, apply=True)

        self.assertEqual(
            self._counts(),
            {User: 1, Application: 0, AgentEvent: 0, MigrationAnomaly: 0},
        )

    def test_missing_legacy_owner_mapping_rolls_back_the_whole_apply(self):
        unmapped_application = dict(self.snapshot.applications[1])
        unmapped_application["owner_id"] = 999
        invalid_snapshot = replace(
            self.snapshot,
            applications=[self.snapshot.applications[0], unmapped_application],
        )

        with self.assertRaises(ValueError):
            import_snapshot(invalid_snapshot, self.session_factory, apply=True)

        self.assertEqual(
            self._counts(),
            {User: 1, Application: 0, AgentEvent: 0, MigrationAnomaly: 0},
        )


class LegacyImporterCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.temporary_path = Path(self.temporary_directory.name)
        self.sqlite_path = self.temporary_path / "legacy.db"
        self.logs_path = self.temporary_path / "logs.json"
        self.target_path = self.temporary_path / "target.db"
        self.database_url = f"sqlite:///{self.target_path}"
        self._write_legacy_source()
        engine = create_engine(self.database_url)
        Base.metadata.create_all(engine)
        engine.dispose()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_legacy_source(self, date_of_birth="1980-01-21"):
        connection = sqlite3.connect(self.sqlite_path)
        try:
            connection.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    hashed_password TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    date_of_birth TEXT
                );
                CREATE TABLE applications (
                    id INTEGER PRIMARY KEY,
                    app_id_str TEXT,
                    applicant_name TEXT,
                    loan_type TEXT,
                    amount REAL,
                    status TEXT,
                    submitted_date TEXT,
                    validation_comments TEXT,
                    owner_id INTEGER
                );
                """
            )
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                (
                    1,
                    "cli-user",
                    "hash-cli-secret",
                    "ApplicantCliSecret",
                    "User",
                    date_of_birth,
                ),
            )
            connection.execute(
                "INSERT INTO applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    1,
                    "cli-app",
                    "ApplicantCliSecret User",
                    "Mortgage",
                    50000,
                    "Pending",
                    "2026-09-03",
                    "validation-cli-secret",
                    1,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        self.logs_path.write_text(
            json.dumps(
                {
                    "_default": {
                        "1": {
                            "application_id": "missing-cli-app",
                            "stage": "tool_response",
                            "timestamp": "2026-09-03T01:02:03Z",
                            "data": {"credential": "cos-cli-secret"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def _run_cli(self, *extra_arguments):
        return subprocess.run(
            [
                sys.executable,
                str(CLI_PATH),
                "--sqlite",
                str(self.sqlite_path),
                "--logs",
                str(self.logs_path),
                "--database-url",
                self.database_url,
                *extra_arguments,
            ],
            cwd=BACKEND_DIRECTORY,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _target_counts(self):
        engine = create_engine(self.database_url)
        session_factory = sessionmaker(bind=engine)
        try:
            with session_factory() as session:
                return (
                    session.query(User).count(),
                    session.query(Application).count(),
                    session.query(AgentEvent).count(),
                    session.query(MigrationAnomaly).count(),
                )
        finally:
            engine.dispose()

    def test_cli_defaults_to_dry_run(self):
        result = self._run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._target_counts(), (0, 0, 0, 0))
        self.assertIn("mode=dry-run", result.stdout)
        self.assertIn("users_seen=1", result.stdout)
        self.assertIn("applications_seen=1", result.stdout)
        self.assertIn("events_seen=1", result.stdout)
        self.assertIn("anomalies_seen=1", result.stdout)
        self.assertIn("anomaly=orphan_agent_event:1", result.stdout)

    def test_cli_apply_writes_and_never_prints_sensitive_values(self):
        result = self._run_cli("--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._target_counts(), (1, 1, 1, 1))
        self.assertIn("mode=apply", result.stdout)
        self.assertIn("total_inserted=4", result.stdout)
        combined_output = result.stdout + result.stderr
        for secret in (
            self.database_url,
            "hash-cli-secret",
            "ApplicantCliSecret",
            "validation-cli-secret",
            "cos-cli-secret",
        ):
            self.assertNotIn(secret, combined_output)

    def test_cli_redacts_conversion_errors(self):
        self.sqlite_path.unlink()
        conversion_secret = "invalid-date-with-password-cli-secret"
        self._write_legacy_source(date_of_birth=conversion_secret)

        result = self._run_cli("--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._target_counts(), (0, 0, 0, 0))
        self.assertIn("Migration failed: invalid legacy data", result.stderr)
        self.assertNotIn(conversion_secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
