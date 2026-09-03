import asyncio
import hashlib
import io
import json
import os
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers

from database import Base
from models import Application, ApplicationDocument, ProcessingRun, User
from repositories import application_records
from utils.cos_client import COSClient, ClientError
import main


class ApplicationRecordRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "application-records.db"
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
                username="record-owner",
                hashed_password="hash",
                first_name="Record",
                last_name="Owner",
                date_of_birth=date(1980, 1, 21),
            )
        )
        self.application = Application(
            app_id_str="app-1",
            applicant_name="Record Owner",
            loan_type="Home Renovation",
            amount=Decimal("50000.00"),
            status="Pending",
            submitted_date=date(2026, 9, 3),
            owner_id=1,
        )
        self.other_application = Application(
            app_id_str="app-2",
            applicant_name="Record Owner",
            loan_type="Auto",
            amount=Decimal("20000.00"),
            status="Processing Failed",
            submitted_date=date(2026, 9, 3),
            owner_id=1,
        )
        self.session.add_all([self.application, self.other_application])
        self.session.commit()
        self.session_local_patch = patch.object(
            application_records,
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

    def get_run(self, run_id):
        return self.session.query(ProcessingRun).filter(ProcessingRun.id == run_id).one()

    @staticmethod
    def upload(filename, content, content_type):
        return UploadFile(
            filename=filename,
            file=io.BytesIO(content),
            headers=Headers({"content-type": content_type}),
        )

    def test_record_document_saves_metadata_not_binary(self):
        record = application_records.record_document(
            application_id=self.application.id,
            document_role="idProof",
            original_filename="passport.png",
            cos_object_key="uploads/app-1/idProof-passport.png",
            content_type="image/png",
            size_bytes=2048,
            sha256="a" * 64,
        )

        stored = self.session.query(ApplicationDocument).one()
        self.assertEqual(record.id, stored.id)
        self.assertEqual(record.application_id, self.application.id)
        self.assertEqual(record.document_role, "idProof")
        self.assertEqual(record.original_filename, "passport.png")
        self.assertEqual(record.cos_object_key, "uploads/app-1/idProof-passport.png")
        self.assertEqual(record.content_type, "image/png")
        self.assertEqual(record.size_bytes, 2048)
        self.assertEqual(record.sha256, "a" * 64)
        self.assertFalse(hasattr(record, "content"))
        self.assertFalse(hasattr(record, "bytes"))

    def test_save_application_upload_returns_path_and_complete_metadata(self):
        content = b"unaltered customer document bytes"
        upload = UploadFile(
            filename="../passport.png",
            file=io.BytesIO(content),
            headers=Headers({"content-type": "image/png"}),
        )
        captured_content = None

        def capture_upload(upload_file, destination):
            nonlocal captured_content
            captured_content = upload_file.file.read()

        with patch.object(main, "save_upload_file", side_effect=capture_upload):
            path, metadata = main.save_application_upload(
                upload,
                "./uploads/app-1",
                "idProof",
                None,
            )

        self.assertEqual(captured_content, content)
        self.assertEqual(path, metadata["cos_object_key"])
        self.assertEqual(metadata["original_filename"], "../passport.png")
        self.assertEqual(metadata["safe_filename"], Path(path).name)
        self.assertTrue(metadata["safe_filename"].startswith("idProof-"))
        self.assertEqual(metadata["content_type"], "image/png")
        self.assertEqual(metadata["size_bytes"], len(content))
        self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())

    def test_processing_run_numbers_attempts_per_application(self):
        first = application_records.start_processing_run(self.application.id)
        second = application_records.start_processing_run(self.application.id)
        other = application_records.start_processing_run(self.other_application.id)

        self.assertEqual(self.get_run(first).attempt_number, 1)
        self.assertEqual(self.get_run(second).attempt_number, 2)
        self.assertEqual(self.get_run(other).attempt_number, 1)

    def test_form_submission_records_each_uploaded_document(self):
        background_tasks = Mock()
        cos_client = Mock()
        form_data = {
            "firstName": "Record",
            "lastName": "Owner",
            "loanType": "Home Renovation",
            "loanAmount": 50000,
        }

        with (
            patch.object(main, "save_upload_file"),
            patch.object(main, "get_cos_client", return_value=cos_client),
        ):
            result = asyncio.run(
                main.submit_application_form(
                    background_tasks=background_tasks,
                    formDataJson=json.dumps(form_data),
                    idProof=self.upload("passport.png", b"passport", "image/png"),
                    incomeProof=self.upload("paystub.pdf", b"paystub", "application/pdf"),
                    addressProof=self.upload("utility.pdf", b"utility", "application/pdf"),
                    additionalDocs=[
                        self.upload("notes.txt", b"notes", "text/plain")
                    ],
                    demoScenario=None,
                    db=self.session,
                    current_user=SimpleNamespace(id=1, username="record-owner"),
                )
            )

        application = (
            self.session.query(Application)
            .filter(Application.app_id_str == result["application_id"])
            .one()
        )
        documents = (
            self.session.query(ApplicationDocument)
            .filter(ApplicationDocument.application_id == application.id)
            .order_by(ApplicationDocument.document_role)
            .all()
        )
        self.assertEqual(
            [document.document_role for document in documents],
            ["additional", "addressProof", "idProof", "incomeProof"],
        )
        id_proof = next(
            document for document in documents if document.document_role == "idProof"
        )
        self.assertEqual(id_proof.original_filename, "passport.png")
        self.assertEqual(id_proof.content_type, "image/png")
        self.assertEqual(id_proof.size_bytes, len(b"passport"))
        self.assertEqual(id_proof.sha256, hashlib.sha256(b"passport").hexdigest())
        self.assertEqual(Path(id_proof.cos_object_key).name[:8], "idProof-")
        background_tasks.add_task.assert_called_once()

    def test_pdf_submission_records_the_application_form_metadata(self):
        background_tasks = Mock()
        cos_client = Mock()

        with (
            patch.object(main, "save_upload_file"),
            patch.object(main, "get_cos_client", return_value=cos_client),
            patch.object(main, "get_image_client", return_value=Mock()),
            patch.object(
                main,
                "extract_key_value_pairs",
                return_value={
                    "full_name": "Record Owner",
                    "loan_type": "Home Renovation",
                    "loan_amount": 50000,
                },
            ),
        ):
            result = asyncio.run(
                main.submit_pdf_form(
                    background_tasks=background_tasks,
                    applicationPdf=self.upload(
                        "application.pdf",
                        b"application form",
                        "application/pdf",
                    ),
                    idProof=self.upload("passport.png", b"passport", "image/png"),
                    incomeProof=self.upload("paystub.pdf", b"paystub", "application/pdf"),
                    addressProof=self.upload("utility.pdf", b"utility", "application/pdf"),
                    additionalDocs=[],
                    demoScenario=None,
                    db=self.session,
                    current_user=SimpleNamespace(id=1, username="record-owner"),
                )
            )

        application = (
            self.session.query(Application)
            .filter(Application.app_id_str == result["application_id"])
            .one()
        )
        application_form = (
            self.session.query(ApplicationDocument)
            .filter(
                ApplicationDocument.application_id == application.id,
                ApplicationDocument.document_role == "applicationPdf",
            )
            .one()
        )
        self.assertEqual(application_form.original_filename, "application.pdf")
        self.assertEqual(application_form.content_type, "application/pdf")
        self.assertEqual(application_form.size_bytes, len(b"application form"))
        self.assertEqual(
            application_form.sha256,
            hashlib.sha256(b"application form").hexdigest(),
        )

    def test_cos_upload_failure_does_not_persist_document_metadata(self):
        cos_client = COSClient.__new__(COSClient)
        cos_client._cos = Mock()
        cos_client._cos.upload_file.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "upload failed"}},
            "UploadFile",
        )
        upload_directory = str(Path(self.temporary_directory.name) / "uploads")
        caught_error = None

        with (
            patch.object(main, "get_cos_client", return_value=cos_client),
            patch.object(main, "UPLOAD_DIRECTORY", upload_directory),
        ):
            try:
                asyncio.run(
                    main.submit_application_form(
                        background_tasks=Mock(),
                        formDataJson=json.dumps(
                            {
                                "firstName": "Record",
                                "lastName": "Owner",
                                "loanType": "Home Renovation",
                                "loanAmount": 50000,
                            }
                        ),
                        idProof=self.upload(
                            "passport.png",
                            b"passport",
                            "image/png",
                        ),
                        incomeProof=self.upload(
                            "paystub.pdf",
                            b"paystub",
                            "application/pdf",
                        ),
                        addressProof=self.upload(
                            "utility.pdf",
                            b"utility",
                            "application/pdf",
                        ),
                        additionalDocs=None,
                        demoScenario=None,
                        db=self.session,
                        current_user=SimpleNamespace(id=1, username="record-owner"),
                    )
                )
            except HTTPException as error:
                caught_error = error

        self.assertIsNotNone(caught_error)
        self.assertEqual(caught_error.status_code, 500)
        self.assertEqual(self.session.query(ApplicationDocument).count(), 0)

    def test_successful_cos_upload_uses_each_persisted_object_key(self):
        cos_client = COSClient.__new__(COSClient)
        cos_client._cos = Mock()
        upload_directory = str(Path(self.temporary_directory.name) / "uploads")

        with (
            patch.object(main, "get_cos_client", return_value=cos_client),
            patch.object(main, "UPLOAD_DIRECTORY", upload_directory),
        ):
            result = asyncio.run(
                main.submit_application_form(
                    background_tasks=Mock(),
                    formDataJson=json.dumps(
                        {
                            "firstName": "Record",
                            "lastName": "Owner",
                            "loanType": "Home Renovation",
                            "loanAmount": 50000,
                        }
                    ),
                    idProof=self.upload("passport.png", b"passport", "image/png"),
                    incomeProof=self.upload(
                        "paystub.pdf",
                        b"paystub",
                        "application/pdf",
                    ),
                    addressProof=self.upload(
                        "utility.pdf",
                        b"utility",
                        "application/pdf",
                    ),
                    additionalDocs=None,
                    demoScenario=None,
                    db=self.session,
                    current_user=SimpleNamespace(id=1, username="record-owner"),
                )
            )

        application = (
            self.session.query(Application)
            .filter(Application.app_id_str == result["application_id"])
            .one()
        )
        persisted_keys = sorted(
            document.cos_object_key for document in application.documents
        )
        uploaded_keys = sorted(
            call.args[2] for call in cos_client._cos.upload_file.call_args_list
        )
        self.assertEqual(uploaded_keys, persisted_keys)

    def test_background_attempts_finish_without_changing_business_status_rules(self):
        success = {
            "loan_application_status": "passed",
            "validation_details": {"summary": "Documents matched."},
        }

        with (
            patch.object(main.database, "SessionLocal", self.session_factory),
            patch.object(main, "invoke_agents", return_value=success),
        ):
            main.process_application_in_background(
                self.application.id,
                ["id.png"],
                "application_data.json",
                self.session,
            )

        self.session.refresh(self.application)
        first_run = (
            self.session.query(ProcessingRun)
            .filter(ProcessingRun.application_id == self.application.id)
            .one()
        )
        self.assertEqual(self.application.status, "passed")
        self.assertEqual(first_run.attempt_number, 1)
        self.assertEqual(first_run.status, "completed")
        self.assertIsNotNone(first_run.finished_at)
        self.assertIsNone(first_run.error_text)

        self.application.status = "Processing Failed"
        self.session.commit()
        background_tasks = Mock()
        with patch.object(
            main,
            "recover_application_inputs",
            return_value=(["id.png"], "application_data.json"),
        ):
            asyncio.run(
                main.retry_application(
                    self.application.app_id_str,
                    background_tasks=background_tasks,
                    current_user=SimpleNamespace(id=1),
                    db=self.session,
                )
            )

        scheduled_call = background_tasks.add_task.call_args.args
        self.assertIs(scheduled_call[0], main.process_application_in_background)
        with (
            patch.object(main.database, "SessionLocal", self.session_factory),
            patch.object(
                main,
                "invoke_agents",
                side_effect=RuntimeError("Agent timeout"),
            ),
        ):
            scheduled_call[0](*scheduled_call[1:])

        self.session.refresh(self.application)
        second_run = (
            self.session.query(ProcessingRun)
            .filter(
                ProcessingRun.application_id == self.application.id,
                ProcessingRun.attempt_number == 2,
            )
            .one()
        )
        self.assertEqual(self.application.status, "Processing Failed")
        self.assertEqual(second_run.status, "failed")
        self.assertIsNotNone(second_run.finished_at)
        self.assertEqual(second_run.error_text, "Agent timeout")

    def test_completed_run_records_terminal_state(self):
        run_id = application_records.start_processing_run(self.application.id)

        application_records.finish_processing_run(run_id, "completed")

        run = self.get_run(run_id)
        self.assertEqual(run.status, "completed")
        self.assertIsNotNone(run.finished_at)
        self.assertIsNone(run.error_text)

    def test_failed_run_keeps_error_without_changing_business_status(self):
        original_status = self.other_application.status
        run_id = application_records.start_processing_run(self.other_application.id)

        application_records.finish_processing_run(run_id, "failed", "Agent timeout")

        run = self.get_run(run_id)
        self.session.refresh(self.other_application)
        self.assertEqual(run.status, "failed")
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(run.error_text, "Agent timeout")
        self.assertEqual(self.other_application.status, original_status)

    def test_failed_run_redacts_authorization_and_wxo_credentials(self):
        run_id = application_records.start_processing_run(self.application.id)
        error = (
            "Agent timeout; Authorization: Bearer bearer-secret; "
            "WXO_API_KEY=wxo-secret; bare-wxo-secret"
        )

        with patch.dict(os.environ, {"WXO_API_KEY": "bare-wxo-secret"}):
            application_records.finish_processing_run(run_id, "failed", error)

        stored_error = self.get_run(run_id).error_text
        self.assertIn("Agent timeout", stored_error)
        self.assertNotIn("bearer-secret", stored_error)
        self.assertNotIn("wxo-secret", stored_error)
        self.assertNotIn("bare-wxo-secret", stored_error)

    def test_failed_run_redacts_database_url_credentials(self):
        run_id = application_records.start_processing_run(self.application.id)
        error = (
            "Database unavailable; "
            "DATABASE_URL=postgresql+psycopg://user:db-secret@host/db; "
            "retry later"
        )

        application_records.finish_processing_run(run_id, "failed", error)

        self.assertEqual(
            self.get_run(run_id).error_text,
            "Database unavailable; DATABASE_URL=[REDACTED]; retry later",
        )

    def test_failed_run_redacts_non_bearer_authorization_credentials(self):
        run_id = application_records.start_processing_run(self.application.id)
        error = "Request failed; Authorization: Basic basic-secret; retry later"

        application_records.finish_processing_run(run_id, "failed", error)

        self.assertEqual(
            self.get_run(run_id).error_text,
            "Request failed; Authorization: [REDACTED]; retry later",
        )

    def test_failed_run_redacts_standalone_bearer_credentials(self):
        run_id = application_records.start_processing_run(self.application.id)
        error = "Request failed with Bearer standalone-secret; retry later"

        application_records.finish_processing_run(run_id, "failed", error)

        self.assertEqual(
            self.get_run(run_id).error_text,
            "Request failed with Bearer [REDACTED]; retry later",
        )

    def test_failed_run_redacts_quoted_labeled_wxo_credentials(self):
        run_id = application_records.start_processing_run(self.application.id)
        error = "Agent failed; WXO_API_KEY='quoted-wxo-secret'; retry later"

        with patch.dict(os.environ, {"WXO_API_KEY": "different-current-secret"}):
            application_records.finish_processing_run(run_id, "failed", error)

        self.assertEqual(
            self.get_run(run_id).error_text,
            "Agent failed; WXO_API_KEY=[REDACTED]; retry later",
        )


if __name__ == "__main__":
    unittest.main()
