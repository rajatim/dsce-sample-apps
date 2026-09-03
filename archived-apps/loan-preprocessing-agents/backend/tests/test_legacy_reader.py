import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from legacy_import.reader import load_legacy_snapshot


class LegacyReaderTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_path = Path(self.temporary_directory.name)
        self.sqlite_path = temporary_path / "loan_app.db"
        self.logs_path = temporary_path / "logs.json"
        self._create_sqlite_fixture()
        self._create_tinydb_fixture()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _create_sqlite_fixture(self):
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
                (1, "loan_user", "hashed", "Loan", "User", "1980-01-01"),
            )
            connection.executemany(
                "INSERT INTO applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (1, "known-app", "Loan User", "Mortgage", 50000, "new", "2026-09-03", None, 1),
                    (2, "other-app", "Loan User", "Auto", 30000, "new", "2026-09-03", None, 1),
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def _create_tinydb_fixture(self):
        self.logs_path.write_text(
            json.dumps(
                {
                    "_default": {
                        "1": {
                            "application_id": "known-app",
                            "stage": "validation",
                            "timestamp": "2026-09-03T01:02:03Z",
                            "data": '{"valid": true}',
                        },
                        "2": {
                            "application_id": "known-app",
                            "stage": "invoke_agent",
                            "timestamp": "2026-09-03T02:03:04",
                            "data": "Invoking agent",
                        },
                        "4": {
                            "application_id": "missing-app",
                            "stage": "tool_call",
                            "timestamp": "2026-09-03T03:04:05+00:00",
                            "data": "[1, 2]",
                        },
                        "3": {
                            "application_id": "missing-app",
                            "stage": "tool_response",
                            "timestamp": "2026-09-03T03:04:06+00:00",
                            "data": "{}",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_loads_users_applications_and_events(self):
        snapshot = load_legacy_snapshot(self.sqlite_path, self.logs_path)

        self.assertEqual(len(snapshot.users), 1)
        self.assertEqual(len(snapshot.applications), 2)
        self.assertEqual(len(snapshot.events), 4)

    def test_marks_log_without_application_as_anomaly(self):
        snapshot = load_legacy_snapshot(self.sqlite_path, self.logs_path)

        self.assertEqual(snapshot.anomalies[0].external_application_id, "missing-app")

    def test_keeps_orphan_events_but_reports_one_anomaly_per_application(self):
        snapshot = load_legacy_snapshot(self.sqlite_path, self.logs_path)

        missing_application_events = [
            event
            for event in snapshot.events
            if event.external_application_id == "missing-app"
        ]
        self.assertEqual(len(missing_application_events), 2)
        self.assertEqual(len(snapshot.anomalies), 1)
        self.assertEqual(snapshot.anomalies[0].source_id, "3")

    def test_normalizes_naive_and_zulu_timestamps_to_utc(self):
        snapshot = load_legacy_snapshot(self.sqlite_path, self.logs_path)

        self.assertTrue(all(event.occurred_at.tzinfo is not None for event in snapshot.events))
        self.assertTrue(
            all(event.occurred_at.utcoffset() == timedelta(0) for event in snapshot.events)
        )

    def test_preserves_json_and_plain_text_payloads(self):
        snapshot = load_legacy_snapshot(self.sqlite_path, self.logs_path)

        self.assertEqual(snapshot.events[0].payload, {"valid": True})
        self.assertEqual(snapshot.events[1].payload, {"message": "Invoking agent"})


if __name__ == "__main__":
    unittest.main()
