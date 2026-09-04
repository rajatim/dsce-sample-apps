import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class ApplicationRetryTest(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=11, username="tom_miller")
        self.application = SimpleNamespace(
            id=7,
            app_id_str="pdf_retry_test",
            status="Processing Failed",
            validation_comments="- **error**: Processing failed.",
            owner_id=self.user.id,
        )
        self.session = Mock()
        self.session.query.return_value.filter.return_value.first.return_value = (
            self.application
        )

    def test_owned_application_can_be_reloaded_for_live_panel_updates(self):
        self.assertTrue(
            hasattr(main, "get_application"),
            "The live application lookup endpoint is missing",
        )
        result = asyncio.run(
            main.get_application(
                self.application.app_id_str,
                current_user=self.user,
                db=self.session,
            )
        )

        self.assertIs(result, self.application)

    def test_retry_reuses_the_failed_application_and_schedules_existing_sources(self):
        self.assertTrue(
            hasattr(main, "retry_application"),
            "The retry endpoint is missing",
        )
        self.assertTrue(
            hasattr(main, "recover_application_inputs"),
            "Retry source recovery is missing",
        )
        background_tasks = Mock()
        documents = [
            "./uploads/pdf_retry_test/idProof-a-passport.png",
            "./uploads/pdf_retry_test/incomeProof-b-bank.pdf",
        ]
        application_data = "./uploads/pdf_retry_test/application_data.json"

        with patch.object(
            main,
            "recover_application_inputs",
            return_value=(documents, application_data),
        ):
            result = asyncio.run(
                main.retry_application(
                    self.application.app_id_str,
                    background_tasks=background_tasks,
                    current_user=self.user,
                    db=self.session,
                )
            )

        self.assertIs(result, self.application)
        self.assertEqual(self.application.status, "Pending")
        self.assertIn("Retry requested", self.application.validation_comments)
        self.session.commit.assert_called_once()
        background_tasks.add_task.assert_called_once_with(
            main.process_application_in_background,
            self.application.id,
            documents,
            application_data,
            self.session,
        )

    def test_retry_refuses_an_application_that_is_not_processing_failed(self):
        self.assertTrue(
            hasattr(main, "retry_application"),
            "The retry endpoint is missing",
        )
        self.application.status = "Processing"

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                main.retry_application(
                    self.application.app_id_str,
                    background_tasks=Mock(),
                    current_user=self.user,
                    db=self.session,
                )
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.session.commit.assert_not_called()

    def test_retry_keeps_the_failure_unchanged_when_sources_are_missing(self):
        self.assertTrue(
            hasattr(main, "retry_application"),
            "The retry endpoint is missing",
        )
        self.assertTrue(
            hasattr(main, "recover_application_inputs"),
            "Retry source recovery is missing",
        )
        original_comments = self.application.validation_comments

        with patch.object(
            main,
            "recover_application_inputs",
            side_effect=FileNotFoundError("source documents are no longer available"),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    main.retry_application(
                        self.application.app_id_str,
                        background_tasks=Mock(),
                        current_user=self.user,
                        db=self.session,
                    )
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.application.status, "Processing Failed")
        self.assertEqual(self.application.validation_comments, original_comments)
        self.session.commit.assert_not_called()

    def test_source_recovery_excludes_the_pdf_application_form(self):
        self.assertTrue(
            hasattr(main, "recover_application_inputs"),
            "Retry source recovery is missing",
        )
        prefix = "./uploads/pdf_retry_test"
        cos_files = [
            f"{prefix}/applicationPdf-a-application.pdf",
            f"{prefix}/idProof-b-passport.pdf",
            f"{prefix}/incomeProof-c-bank.pdf",
            f"{prefix}/addressProof-d-license.png",
            f"{prefix}/application_data.json",
        ]
        cos_client = Mock()
        cos_client.get_contents_of_folder_in_bucket.return_value = cos_files

        with (
            patch.object(main.os.path, "isdir", return_value=False),
            patch.object(main, "get_cos_client", return_value=cos_client),
        ):
            documents, application_data = main.recover_application_inputs(
                "pdf_retry_test"
            )

        self.assertEqual(
            documents,
            [
                f"{prefix}/addressProof-d-license.png",
                f"{prefix}/idProof-b-passport.pdf",
                f"{prefix}/incomeProof-c-bank.pdf",
            ],
        )
        self.assertEqual(application_data, f"{prefix}/application_data.json")

    def test_source_recovery_queries_cos_without_a_dot_path_segment(self):
        normalized_prefix = "./uploads/pdf_retry_test"
        cos_prefix = "uploads/pdf_retry_test/"
        cos_files = [
            "uploads/pdf_retry_test/idProof-a-passport.png",
            "uploads/pdf_retry_test/application_data.json",
        ]
        cos_client = Mock()
        cos_client.get_contents_of_folder_in_bucket.side_effect = (
            lambda bucket_name, prefix: cos_files if prefix == cos_prefix else []
        )

        with (
            patch.object(main.os.path, "isdir", return_value=False),
            patch.object(main, "get_cos_client", return_value=cos_client),
        ):
            documents, application_data = main.recover_application_inputs(
                "pdf_retry_test"
            )

        cos_client.get_contents_of_folder_in_bucket.assert_called_once_with(
            main.COS_BUCKET_NAME,
            cos_prefix,
        )
        self.assertEqual(
            documents,
            [f"{normalized_prefix}/idProof-a-passport.png"],
        )
        self.assertEqual(
            application_data,
            f"{normalized_prefix}/application_data.json",
        )


if __name__ == "__main__":
    unittest.main()
