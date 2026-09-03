import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentEvent, Application, User
from repositories import agent_events


class AgentEventRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "agent-events.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        self.session = self.session_factory()
        self.session.add(
            User(
                id=1,
                username="event-owner",
                hashed_password="hash",
                first_name="Event",
                last_name="Owner",
                date_of_birth=date(1980, 1, 21),
            )
        )
        self.session.add(
            Application(
                app_id_str="app-1",
                applicant_name="Event Owner",
                loan_type="Home Renovation",
                amount=Decimal("50000.00"),
                status="Pending",
                submitted_date=date(2026, 9, 3),
                owner_id=1,
            )
        )
        self.session.commit()
        self.session_local_patch = patch.object(
            agent_events,
            "SessionLocal",
            self.session_factory,
        )
        self.session_local_patch.start()

    def tearDown(self):
        self.session_local_patch.stop()
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_append_event_links_existing_application(self):
        agent_events.append_event("app-1", "invoke_agent", "Invoking agent")

        event = self.session.query(AgentEvent).one()

        self.assertEqual(event.application.app_id_str, "app-1")

    def test_append_event_preserves_external_id_without_application(self):
        agent_events.append_event("unknown-app", "invoke_agent", {"attempt": 1})

        event = self.session.query(AgentEvent).one()

        self.assertIsNone(event.application_id)
        self.assertEqual(event.external_application_id, "unknown-app")
        self.assertEqual(event.payload, {"attempt": 1})

    def test_plain_text_becomes_json_message(self):
        agent_events.append_event("app-1", "agent_response", "complete")

        self.assertEqual(
            self.session.query(AgentEvent).one().payload,
            {"message": "complete"},
        )

    def test_list_events_returns_timestamp_order_and_frontend_shape(self):
        occurred_at = datetime(2026, 9, 3, 10, 15, tzinfo=timezone.utc)
        agent_events.append_event("app-1", "first", {"step": 1}, occurred_at)
        agent_events.append_event("app-1", "second", {"step": 2}, occurred_at)

        events = agent_events.list_events("app-1")

        self.assertEqual([event["stage"] for event in events], ["first", "second"])
        self.assertEqual(
            events,
            [
                {
                    "application_id": "app-1",
                    "stage": "first",
                    "timestamp": "2026-09-03T10:15:00Z",
                    "data": {"step": 1},
                },
                {
                    "application_id": "app-1",
                    "stage": "second",
                    "timestamp": "2026-09-03T10:15:00Z",
                    "data": {"step": 2},
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
