import unittest
import sys
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from document_validate.tools.validate_document import (
    AUTHORIZED_POC_FIXTURE_SHA256,
    DOC_VALIDATION_SYSTEM_PROMPT,
    WATSONX_CONFIG,
)


class ToolLatencyConfigurationTest(unittest.TestCase):
    def test_document_validation_has_a_compact_poc_response_budget(self):
        self.assertLessEqual(WATSONX_CONFIG["params"]["max_tokens"], 400)
        self.assertLess(len(DOC_VALIDATION_SYSTEM_PROMPT), 1800)

    def test_only_the_authorized_pass_fixture_gets_demo_validation_guidance(self):
        validate_document_module = importlib.import_module(
            "document_validate.tools.validate_document"
        )
        prompt_builder = getattr(
            validate_document_module,
            "build_validation_system_prompt",
            None,
        )
        self.assertIsNotNone(
            prompt_builder,
            "Document validation needs scenario-aware POC guidance",
        )

        fixture_digest = AUTHORIZED_POC_FIXTURE_SHA256["ID-Doc.png"]
        pass_prompt = prompt_builder(
            "./uploads/app/demo-pass-ID-Doc.png",
            fixture_digest,
        )
        replaced_prompt = prompt_builder(
            "./uploads/app/demo-pass-ID-Doc.png",
            "wrong-digest",
        )
        regular_prompt = prompt_builder(
            "./uploads/app/customer-ID-Doc.png",
            fixture_digest,
        )

        self.assertIn("authorized POC fixture", pass_prompt)
        self.assertNotIn("authorized POC fixture", replaced_prompt)
        self.assertNotIn("authorized POC fixture", regular_prompt)

    def test_authorized_pass_fixture_has_a_deterministic_poc_result(self):
        validate_document_module = importlib.import_module(
            "document_validate.tools.validate_document"
        )
        policy = getattr(
            validate_document_module,
            "apply_authorized_poc_policy",
            None,
        )
        self.assertIsNotNone(policy, "Pass fixtures need a deterministic POC policy")

        llm_result = {
            "valid": False,
            "risk_level": "High",
            "authenticity": "Failed: contains SAMPLE markings",
            "reason": "Document is invalid because it is a sample.",
            "failure_codes": ["synthetic_sample_marking"],
        }
        fixture_digest = AUTHORIZED_POC_FIXTURE_SHA256["ID-Doc.png"]
        pass_result = policy(
            "./uploads/app/demo-pass-ID-Doc.png",
            llm_result,
            fixture_digest,
        )
        regular_result = policy(
            "./uploads/app/customer-ID-Doc.png",
            llm_result,
            fixture_digest,
        )
        tampered_result = policy(
            "./uploads/app/demo-pass-ID-Doc.png",
            {
                "valid": False,
                "reason": "Visible tampering around the portrait.",
                "failure_codes": ["visible_tampering"],
            },
            fixture_digest,
        )
        mixed_result = policy(
            "./uploads/app/demo-pass-ID-Doc.png",
            {
                "valid": False,
                "authenticity": "Failed: SAMPLE document with visible tampering.",
                "reason": "The portrait appears altered.",
                "failure_codes": ["synthetic_sample_marking", "visible_tampering"],
            },
            fixture_digest,
        )
        replaced_file_result = policy(
            "./uploads/app/demo-pass-ID-Doc.png",
            llm_result,
            "not-the-authorized-digest",
        )
        contradictory_result = policy(
            "./uploads/app/demo-pass-ID-Doc.png",
            {
                "valid": True,
                "risk_level": "Low",
                "reason": "Visible portrait manipulation detected.",
                "failure_codes": ["visible_tampering"],
            },
            fixture_digest,
        )

        self.assertTrue(pass_result["valid"])
        self.assertEqual(pass_result["risk_level"], "Low")
        self.assertFalse(regular_result["valid"])
        self.assertFalse(tampered_result["valid"])
        self.assertFalse(mixed_result["valid"])
        self.assertFalse(replaced_file_result["valid"])
        self.assertFalse(contradictory_result["valid"])


if __name__ == "__main__":
    unittest.main()
