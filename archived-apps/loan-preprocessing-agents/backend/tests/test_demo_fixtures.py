import asyncio
import hashlib
import io
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from fastapi import UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class DemoFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_pass_fixture_is_served_with_a_scenario_specific_filename(self):
        response = self.client.get("/demo_fixtures/pass/idProof")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(
            'filename="demo-pass-ID-Doc.png"',
            response.headers["content-disposition"],
        )

    def test_pdf_fixture_uses_the_pdf_media_type(self):
        response = self.client.get("/demo_fixtures/reject/applicationPdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_unknown_fixture_key_is_rejected(self):
        response = self.client.get("/demo_fixtures/pass/not-a-document")

        self.assertEqual(response.status_code, 404)

    def test_fixture_endpoint_streams_without_loading_the_whole_member(self):
        with patch.object(
            zipfile.ZipFile,
            "read",
            side_effect=AssertionError("The endpoint must stream with ZipFile.open"),
        ):
            response = self.client.get("/demo_fixtures/pass/idProof")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_only_exact_builtin_bytes_can_keep_the_demo_pass_filename(self):
        resolver = getattr(main, "resolve_upload_name", None)
        self.assertIsNotNone(
            resolver,
            "Upload names need server-side fixture verification",
        )
        with zipfile.ZipFile(main.ZIP_FILE_PATH) as archive:
            fixture_bytes = archive.read("ID Doc.png")

        verified_name = resolver(
            "idProof",
            "../../demo-pass-ID-Doc.png",
            "pass",
            hashlib.sha256(fixture_bytes).hexdigest(),
        )
        spoofed_name = resolver(
            "idProof",
            "../../demo-pass-ID-Doc.png",
            "pass",
            hashlib.sha256(b"not the fixture").hexdigest(),
        )

        self.assertEqual(verified_name, "demo-pass-ID-Doc.png")
        self.assertTrue(spoofed_name.startswith("idProof-"))
        self.assertTrue(spoofed_name.endswith("demo-pass-ID-Doc.png"))
        self.assertNotIn("/", spoofed_name)
        self.assertNotIn("..", spoofed_name)

    def test_regular_upload_uses_a_server_generated_role_specific_name(self):
        resolved_name = main.resolve_upload_name(
            "idProof",
            "../../application_data.json",
            None,
            hashlib.sha256(b"customer upload").hexdigest(),
        )

        self.assertNotEqual(resolved_name, "application_data.json")
        self.assertTrue(resolved_name.startswith("idProof-"))
        self.assertNotIn("/", resolved_name)

    def test_pass_pdf_uses_canonical_data_that_matches_the_demo_documents(self):
        def upload(name, archive_name):
            with zipfile.ZipFile(main.ZIP_FILE_PATH) as archive:
                fixture_bytes = archive.read(archive_name)
            return UploadFile(filename=name, file=io.BytesIO(fixture_bytes))

        session = Mock()
        session.add.side_effect = lambda application: setattr(application, "id", 42)
        background_tasks = Mock()
        cos_client = Mock()

        with (
            patch.object(main, "save_upload_file"),
            patch.object(main, "get_cos_client", return_value=cos_client),
            patch.object(
                main,
                "extract_key_value_pairs",
                return_value={
                    "full_name": "Wrong OCR Name",
                    "loan_type": "Unknown",
                    "loan_amount": 1,
                },
            ) as extract_key_value_pairs,
        ):
            try:
                asyncio.run(
                    main.submit_pdf_form(
                        background_tasks=background_tasks,
                        applicationPdf=upload(
                            "demo-pass-Loan-Application-Form.pdf",
                            "Loan Application Form.pdf",
                        ),
                        idProof=upload("demo-pass-ID-Doc.png", "ID Doc.png"),
                        incomeProof=upload(
                            "demo-pass-Income-Doc.png",
                            "Income Doc.png",
                        ),
                        addressProof=upload(
                            "demo-pass-Address-Doc.png",
                            "Address Doc.png",
                        ),
                        additionalDocs=[upload("demo-pass-SSN.png", "SSN.png")],
                        demoScenario="pass",
                        db=session,
                        current_user=SimpleNamespace(id=1, username="tom_miller"),
                    )
                )
            except TypeError as error:
                self.fail(f"PDF submissions should accept a demo scenario: {error}")

        saved_application = session.add.call_args.args[0]
        uploaded_json = cos_client.upload_json_to_cos.call_args.kwargs["json_content"]
        self.assertEqual(saved_application.applicant_name, "Tom Miller")
        self.assertEqual(saved_application.amount, 50000)
        self.assertEqual(uploaded_json["ssn"], "987-65-4321")
        self.assertEqual(uploaded_json["passportNumber"], "AB1234567")
        extract_key_value_pairs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
