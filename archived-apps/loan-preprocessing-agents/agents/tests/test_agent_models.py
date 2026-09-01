import unittest
from pathlib import Path

import yaml


AGENTS_DIRECTORY = Path(__file__).resolve().parents[1]
TOOL_CALLING_AGENT_SPECS = (
    AGENTS_DIRECTORY / "data_processing/agents/data_processing_agent.yaml",
    AGENTS_DIRECTORY / "document_validate/agents/document_validate.yaml",
    AGENTS_DIRECTORY / "final_decision/agents/final_decision.yaml",
)


class AgentModelConfigurationTest(unittest.TestCase):
    def test_tool_calling_agents_use_the_proven_multi_step_model(self):
        for spec_path in TOOL_CALLING_AGENT_SPECS:
            with self.subTest(spec=spec_path.name):
                spec = yaml.safe_load(spec_path.read_text())
                self.assertEqual(
                    spec["llm"],
                    "watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
                )

    def test_final_decision_short_circuits_invalid_documents_without_questions(self):
        spec_path = AGENTS_DIRECTORY / "final_decision/agents/final_decision.yaml"
        instructions = yaml.safe_load(spec_path.read_text())["instructions"]

        self.assertIn("immediately return", instructions)
        self.assertIn("Do not ask the user", instructions)
        self.assertIn("loan_application_status", instructions)

    def test_document_validator_finishes_each_single_document_request(self):
        spec_path = AGENTS_DIRECTORY / "document_validate/agents/document_validate.yaml"
        instructions = yaml.safe_load(spec_path.read_text())["instructions"]

        self.assertIn("exactly one document", instructions)
        self.assertIn("Return the JSON result immediately", instructions)


if __name__ == "__main__":
    unittest.main()
