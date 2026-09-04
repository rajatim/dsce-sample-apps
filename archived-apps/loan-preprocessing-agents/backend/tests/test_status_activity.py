import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentEvent
from repositories import agent_events
from repositories.status_activity import get_recent_agent_activity
from utils import agents


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

    def test_unrecognized_invocation_clears_the_application_agent_mapping(self):
        self.append(
            "app-unknown",
            "invoke_agent",
            {"message": "Invoking Document Processor Agent"},
        )
        self.append(
            "app-unknown",
            "invoke_agent",
            {"message": "Invoking an unrecognized agent"},
        )
        self.append(
            "app-unknown",
            "agent_response",
            {"message": "must not be attributed to the processor"},
        )

        activity = get_recent_agent_activity(self.session_factory)

        self.assertIsNone(activity["document_processing_agent"].last_success_at)
        self.assertIsNone(activity["document_processing_agent"].last_failure_at)

    def test_retryable_failure_event_is_sanitized_and_readable_end_to_end(self):
        application_id = "app-retryable-failure"
        self.append(
            application_id,
            "invoke_agent",
            {"message": "Invoking Document Validator Agent"},
        )

        with (
            patch.object(agent_events, "SessionLocal", self.session_factory),
            patch.object(
                agents,
                "_get_response_once",
                side_effect=agents.TransientAgentError("private provider response"),
            ),
            patch.object(agents.time, "sleep"),
        ):
            with self.assertRaises(agents.TransientAgentError):
                agents.get_response(
                    "validate",
                    "configured-agent-id",
                    application_id=application_id,
                )

        self.session.expire_all()
        failures = (
            self.session.query(AgentEvent)
            .filter(
                AgentEvent.external_application_id == application_id,
                AgentEvent.stage == "agent_failure",
            )
            .all()
        )
        self.assertEqual(len(failures), agents.MAX_AGENT_ATTEMPTS)
        self.assertNotIn("private provider response", repr([item.payload for item in failures]))
        self.assertTrue(all(item.payload["failure_kind"] == "retryable" for item in failures))
        self.assertTrue(failures[-1].payload["terminal"])

        activity = get_recent_agent_activity(self.session_factory)
        self.assertIsNotNone(activity["document_validation_agent"].last_failure_at)

    def test_terminal_failure_event_is_sanitized_and_readable_end_to_end(self):
        application_id = "app-terminal-failure"
        self.append(
            application_id,
            "invoke_agent",
            {"message": "Invoking Final Decision Agent"},
        )

        with (
            patch.object(agent_events, "SessionLocal", self.session_factory),
            patch.object(
                agents,
                "_get_response_once",
                side_effect=ValueError("private malformed response"),
            ),
        ):
            with self.assertRaises(ValueError):
                agents.get_response(
                    "decide",
                    "configured-agent-id",
                    application_id=application_id,
                )

        self.session.expire_all()
        failure = (
            self.session.query(AgentEvent)
            .filter(
                AgentEvent.external_application_id == application_id,
                AgentEvent.stage == "agent_failure",
            )
            .one()
        )
        self.assertEqual(
            failure.payload,
            {
                "attempt": 1,
                "failure_kind": "terminal",
                "terminal": True,
            },
        )
        self.assertNotIn("private malformed response", repr(failure.payload))

        activity = get_recent_agent_activity(self.session_factory)
        self.assertIsNotNone(activity["final_decision_agent"].last_failure_at)


if __name__ == "__main__":
    unittest.main()
