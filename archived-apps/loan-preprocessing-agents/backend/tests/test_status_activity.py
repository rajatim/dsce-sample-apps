import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentEvent
from repositories.status_activity import get_recent_agent_activity


class StatusActivityRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "status-activity.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        self.session = self.session_factory()

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def append(self, application_id, stage, payload, occurred_at=None):
        self.session.add(
            AgentEvent(
                external_application_id=application_id,
                stage=stage,
                payload=payload,
                occurred_at=occurred_at or datetime.now(timezone.utc),
            )
        )
        self.session.commit()

    def test_correlates_responses_with_the_latest_agent_invocation(self):
        self.append(
            "app-1",
            "invoke_agent",
            {"message": "Invoking Document Processor Agent"},
        )
        self.append("app-1", "agent_response", {"message": "extraction complete"})
        self.append(
            "app-1",
            "invoke_agent",
            {"message": "Invoking Document Validator Agent"},
        )
        self.append(
            "app-1",
            "agent_response",
            {"message": "I have encountered an error. Please try again."},
        )

        activity = get_recent_agent_activity(self.session_factory)

        self.assertIsNotNone(activity["document_processing_agent"].last_success_at)
        self.assertIsNotNone(activity["document_validation_agent"].last_failure_at)

    def test_returns_timestamps_only_and_never_payload_content(self):
        self.append(
            "app-1",
            "invoke_agent",
            {"message": "Invoking Final Decision Agent", "secret": "PII"},
        )
        self.append(
            "app-1",
            "agent_response",
            {"message": "decision", "applicant_name": "Private Person"},
        )

        activity = get_recent_agent_activity(self.session_factory)

        self.assertFalse(hasattr(activity["final_decision_agent"], "payload"))
        self.assertEqual(activity["final_decision_agent"].agent_key, "final_decision_agent")


if __name__ == "__main__":
    unittest.main()
