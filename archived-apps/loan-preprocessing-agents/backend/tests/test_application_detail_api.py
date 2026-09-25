import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
import main
import models
import security


class ApplicationDetailApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "detail-api.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        database.Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as session:
            session.add_all(
                [
                    models.User(
                        id=1, username="owner", hashed_password="hash",
                        first_name="Test", last_name="Owner",
                        date_of_birth=date(1980, 1, 1),
                    ),
                    models.User(
                        id=2, username="other", hashed_password="hash",
                        first_name="Other", last_name="User",
                        date_of_birth=date(1980, 1, 1),
                    ),
                ]
            )
            session.add_all(
                [
                    models.Application(
                        id=1, app_id_str="failed-app", applicant_name="Test Owner",
                        loan_type="Home", amount=Decimal("50000"),
                        status="Processing Failed", submitted_date=date(2026, 9, 25),
                        owner_id=1, validation_comments="Please retry.",
                    ),
                    models.Application(
                        id=2, app_id_str="decided-app", applicant_name="Test Owner",
                        loan_type="Home", amount=Decimal("50000"), status="rejected",
                        submitted_date=date(2026, 9, 25), owner_id=1,
                    ),
                ]
            )
            session.add(
                models.ProcessingRun(
                    application_id=1, attempt_number=1, status="failed",
                    error_text=(
                        "Agent result filename /private/passport-secret.png does not "
                        "match requested document /private/requested-secret.png"
                    ),
                )
            )
            session.add(
                models.AgentEvent(
                    application_id=1, external_application_id="failed-app",
                    stage="invoke_agent",
                    payload={"message": "Invoking Document Processor Agent"},
                )
            )
            session.commit()

        def get_db():
            with self.session_factory() as session:
                yield session

        main.app.dependency_overrides[database.get_db] = get_db
        main.app.dependency_overrides[security.get_current_user] = (
            lambda: SimpleNamespace(id=1, username="owner")
        )
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_failed_detail_has_safe_specific_processing_failure(self):
        response = self.client.get("/applications/failed-app")

        self.assertEqual(response.status_code, 200)
        failure = response.json().get("processing_failure")
        self.assertIsNotNone(failure)
        self.assertEqual(failure["provider_code"], "document_filename_mismatch")
        self.assertEqual(failure["stage"], "document_processing_agent")
        self.assertEqual(failure["service"], "agent_workflow")
        self.assertNotIn("/private/", response.text)
        self.assertNotIn("passport-secret", response.text)
        self.assertNotIn("requested-secret", response.text)

    def test_decided_detail_has_no_processing_failure(self):
        response = self.client.get("/applications/decided-app")

        self.assertEqual(response.status_code, 200)
        self.assertIn("processing_failure", response.json())
        self.assertIsNone(response.json()["processing_failure"])

    def test_other_user_cannot_read_application_detail(self):
        main.app.dependency_overrides[security.get_current_user] = (
            lambda: SimpleNamespace(id=2, username="other")
        )

        response = self.client.get("/applications/failed-app")

        self.assertEqual(response.status_code, 404)
