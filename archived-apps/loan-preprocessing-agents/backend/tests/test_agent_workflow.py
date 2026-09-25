import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from utils import agents


class AgentWorkflowTest(unittest.TestCase):
    @patch("utils.agents.requests.post")
    @patch("utils.agents.get_bearer_token", return_value="test-token")
    def test_processor_preserves_named_tool_fields_instead_of_llm_summary(self, token, post):
        filename = "/data/uploads/test/bank.png"
        extracted = {"filename": filename, "name": "TEST PERSON", "account_number": "000000000000", "address": "TEST ADDRESS"}
        summary = {"filename": filename, "document_type": "Bank Statement", "extracted_data": {"account_number": "0000000000", "...": "..."}}
        for other_file, agent_id in [(False, "processor"), (True, "processor"), (False, "other-agent")]:
            with self.subTest(other_file=other_file, agent_id=agent_id):
                classification = {"filename": "/other.png" if other_file else filename, "doc_type": "Bank Account Statement"}
                response = Mock(status_code=200)
                response.iter_lines.return_value = [json.dumps(event).encode() for event in [
                    {"event": "run.step.delta", "data": {"delta": {"step_details": [
                        {"type": "tool_response", "name": "classify_document", "tool_call_id": "classify-1", "content": json.dumps(classification)},
                        {"type": "tool_response", "name": "extract_document_info", "tool_call_id": "extract-1", "content": json.dumps(extracted)},
                    ]}}},
                    {"event": "message.created", "data": {"thread_id": "thread-1", "message": {"content": [{"text": json.dumps(summary)}]}}},
                ]]
                post.return_value = response
                with patch.object(agents, "DOC_PROCESSOR_AGENT_ID", "processor"):
                    result = agents._get_response_once("Process " + filename, agent_id, thread_id="thread-1")
                parsed = json.loads(result["response"])
                if other_file or agent_id != "processor":
                    self.assertEqual(parsed, summary)
                else:
                    self.assertEqual(parsed["extracted_data"], extracted)
                    self.assertEqual(parsed["document_type"], "Bank Account Statement")

    def test_demo_age_is_calculated_from_the_canonical_birth_date(self):
        self.assertEqual(agents._age_on_date("1980-01-21", date(2026, 9, 1)), 46)
        self.assertEqual(agents._age_on_date("1980-01-21", date(2026, 1, 20)), 45)

    @patch("time.sleep")
    @patch("utils.agents._get_response_once")
    def test_final_continuation_retry_preserves_its_existing_thread(
        self,
        get_response_once,
        sleep,
    ):
        get_response_once.side_effect = [
            agents.TransientAgentError("stream interrupted"),
            {"response": '{"done": true}', "thread_id": "final-thread"},
        ]

        try:
            result = agents.get_response(
                "Continue the existing workflow",
                agents.FINAL_DECISION_AGENT_ID,
                thread_id="final-thread",
                preserve_thread_on_retry=True,
            )
        except TypeError as error:
            self.fail(f"Continuation retries need a thread-preservation option: {error}")

        self.assertEqual(result["thread_id"], "final-thread")
        self.assertEqual(get_response_once.call_count, 2)
        self.assertEqual(
            [call.kwargs["thread_id"] for call in get_response_once.call_args_list],
            ["final-thread", "final-thread"],
        )

    @patch("time.sleep")
    @patch("utils.agents.requests.post")
    @patch("utils.agents.create_thread", side_effect=["thread-1", "thread-2"])
    @patch("utils.agents.get_bearer_token", return_value="token-1")
    def test_transient_stream_failure_retries_with_a_fresh_thread(
        self,
        get_bearer_token,
        create_thread,
        post,
        sleep,
    ):
        interrupted_response = Mock(status_code=200)
        interrupted_response.iter_lines.side_effect = (
            agents.requests.exceptions.ChunkedEncodingError("stream interrupted")
        )
        completed_response = Mock(status_code=200)
        completed_response.iter_lines.return_value = [
            json.dumps(
                {
                    "event": "message.created",
                    "data": {
                        "thread_id": "thread-2",
                        "message": {"content": [{"text": '{"status": "passed"}'}]},
                    },
                }
            ).encode("utf-8")
        ]
        post.side_effect = [interrupted_response, completed_response]

        try:
            result = agents.get_response("hello", "agent-1")
        except Exception as error:
            self.fail(f"A transient WXO stream failure should be retried: {error}")

        self.assertEqual(result["response"], '{"status": "passed"}')
        self.assertEqual(create_thread.call_count, 2)
        sleep.assert_called_once()

    @patch("time.sleep")
    @patch("utils.agents.requests.post")
    @patch("utils.agents.create_thread", side_effect=["thread-1", "thread-2"])
    @patch("utils.agents.get_bearer_token", return_value="token-1")
    def test_retryable_agent_message_is_not_treated_as_a_final_answer(
        self,
        get_bearer_token,
        create_thread,
        post,
        sleep,
    ):
        def response_with_text(text, thread_id):
            response = Mock(status_code=200)
            response.iter_lines.return_value = [
                json.dumps(
                    {
                        "event": "message.created",
                        "data": {
                            "thread_id": thread_id,
                            "message": {"content": [{"text": text}]},
                        },
                    }
                ).encode("utf-8")
            ]
            return response

        post.side_effect = [
            response_with_text(
                "I have encountered an error. Please try again.",
                "thread-1",
            ),
            response_with_text('{"status": "passed"}', "thread-2"),
        ]

        result = agents.get_response("hello", "agent-1")

        self.assertEqual(result["response"], '{"status": "passed"}')
        self.assertEqual(create_thread.call_count, 2)
        sleep.assert_called_once()

    @patch("utils.agents.requests.post")
    @patch("utils.agents.create_thread", return_value="thread-1")
    @patch("utils.agents.get_bearer_token", return_value="token-1")
    def test_document_validator_recovers_valid_json_from_its_tool_response(
        self,
        get_bearer_token,
        create_thread,
        post,
    ):
        tool_result = {
            "filename": "demo-pass-ID-Doc.png",
            "document_type": "Passport",
            "valid": True,
            "risk_level": "Low",
            "authenticity": "Passed: authorized POC fixture",
            "expiry": "Valid for authorized POC fixture",
            "completeness": "Complete",
            "failure_codes": [],
            "reason": "Accepted as an authorized synthetic POC fixture.",
        }
        response = Mock(status_code=200)
        response.iter_lines.return_value = [
            json.dumps(
                {
                    "event": "run.step.delta",
                    "data": {
                        "delta": {
                            "step_details": [
                                {
                                    "type": "tool_response",
                                    "content": json.dumps(tool_result),
                                }
                            ]
                        }
                    },
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "event": "message.created",
                    "data": {
                        "thread_id": "thread-1",
                        "message": {
                            "content": [
                                {"text": "LLM has responded with empty message. Please try again."}
                            ]
                        },
                    },
                }
            ).encode("utf-8"),
        ]
        post.return_value = response

        try:
            result = agents.get_response(
                "Validate this document - demo-pass-ID-Doc.png",
                agents.DOCUMENT_VALIDATION_AGENT_ID,
            )
        except Exception as error:
            self.fail(f"A valid validator tool result should be recoverable: {error}")

        self.assertEqual(json.loads(result["response"]), tool_result)
        self.assertEqual(post.call_count, 1)

    @patch("utils.agents.requests.post")
    @patch("utils.agents.create_thread", return_value="thread-1")
    @patch("utils.agents.get_bearer_token", return_value="token-1")
    def test_incomplete_validator_tool_json_is_not_used_as_a_final_result(
        self,
        get_bearer_token,
        create_thread,
        post,
    ):
        response = Mock(status_code=200)
        response.iter_lines.return_value = [
            json.dumps(
                {
                    "event": "run.step.delta",
                    "data": {
                        "delta": {
                            "step_details": [
                                {
                                    "type": "tool_response",
                                    "content": json.dumps({"valid": True}),
                                }
                            ]
                        }
                    },
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "event": "message.created",
                    "data": {
                        "thread_id": "thread-1",
                        "message": {
                            "content": [
                                {"text": "LLM has responded with empty message. Please try again."}
                            ]
                        },
                    },
                }
            ).encode("utf-8"),
        ]
        post.return_value = response

        with self.assertRaises(agents.TransientAgentError):
            agents._get_response_once(
                "Validate this document - id.png",
                agents.DOCUMENT_VALIDATION_AGENT_ID,
            )

    @patch("utils.agents.requests.post")
    @patch("utils.agents.create_thread", return_value="thread-1")
    @patch("utils.agents.get_bearer_token", return_value="token-1")
    def test_validator_tool_result_does_not_hide_a_real_tool_error(
        self,
        get_bearer_token,
        create_thread,
        post,
    ):
        tool_result = {
            "filename": "id.png",
            "document_type": "Passport",
            "valid": True,
            "risk_level": "Low",
            "authenticity": "Passed",
            "expiry": "Valid",
            "completeness": "Complete",
            "failure_codes": [],
            "reason": "Valid.",
        }
        response = Mock(status_code=200)
        response.iter_lines.return_value = [
            json.dumps(
                {
                    "event": "run.step.delta",
                    "data": {
                        "delta": {
                            "step_details": [
                                {
                                    "type": "tool_response",
                                    "content": json.dumps(tool_result),
                                }
                            ]
                        }
                    },
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "event": "message.created",
                    "data": {
                        "thread_id": "thread-1",
                        "message": {"content": [{"text": "Error calling the tool"}]},
                    },
                }
            ).encode("utf-8"),
        ]
        post.return_value = response

        with self.assertRaises(agents.TransientAgentError):
            agents._get_response_once(
                "Validate this document - id.png",
                agents.DOCUMENT_VALIDATION_AGENT_ID,
            )

    @patch("utils.agents.requests.post")
    @patch("utils.agents.create_thread", return_value="thread-1")
    @patch("utils.agents.get_bearer_token", return_value="token-1")
    def test_wxo_stream_has_a_bounded_network_timeout(
        self,
        get_bearer_token,
        create_thread,
        post,
    ):
        response = Mock(status_code=200)
        response.iter_lines.return_value = []
        post.return_value = response

        agents.get_response("hello", "agent-1")

        self.assertEqual(post.call_args.kwargs["timeout"], (30, 180))

    @patch("utils.agents.get_response")
    def test_each_document_uses_a_separate_short_agent_run(self, get_response):
        complete_final_result = {
            "validation_details": {
                "document_authenticity": {
                    "status": "passed",
                    "details": "All documents are authentic.",
                },
                "cross_validation": {
                    "status": "passed",
                    "details": "All fields are consistent.",
                },
                "age_verification": {
                    "status": "passed",
                    "applicant_age": 46,
                    "dob_consistency": "consistent",
                    "details": "Applicant is over 18.",
                },
                "overall_validation_summary": "All checks passed.",
            },
            "loan_application_status": "passed",
        }
        get_response.side_effect = [
            {
                "response": 'Processing complete.\n{"filename": "id.png"}',
                "thread_id": "dp-1",
            },
            {"response": '[{"filename": "income.png"}]', "thread_id": "dp-2"},
            {"response": '[{"filename": "id.png", "valid": true}]', "thread_id": "dv-1"},
            {"response": '[{"filename": "income.png", "valid": true}]', "thread_id": "dv-2"},
            {
                "response": json.dumps(complete_final_result),
                "thread_id": "final",
            },
        ]

        result = agents.invoke_agents(
            ["id.png", "income.png"],
            "application_data.json",
        )

        self.assertEqual(result.get("loan_application_status"), "passed")
        self.assertEqual(get_response.call_count, 5)
        for agent_call, expected_prefix, other_document, agent_id in zip(
            get_response.call_args_list[:4],
            [
                "Classify and extract information from this document - id.png",
                "Classify and extract information from this document - income.png",
                "Validate this document - id.png",
                "Validate this document - income.png",
            ],
            ["income.png", "id.png", "income.png", "id.png"],
            [
                agents.DOC_PROCESSOR_AGENT_ID,
                agents.DOC_PROCESSOR_AGENT_ID,
                agents.DOCUMENT_VALIDATION_AGENT_ID,
                agents.DOCUMENT_VALIDATION_AGENT_ID,
            ],
        ):
            self.assertTrue(agent_call.args[0].startswith(expected_prefix))
            self.assertNotIn(other_document, agent_call.args[0])
            self.assertEqual(agent_call.args[1], agent_id)
            self.assertEqual(agent_call.kwargs, {"application_id": None})
        final_prompt = get_response.call_args_list[-1].args[0]
        self.assertIn('"filename": "id.png"', final_prompt)
        self.assertIn('"filename": "income.png"', final_prompt)

    @patch("utils.agents.get_response")
    def test_regular_submission_does_not_accept_an_incomplete_final_schema(
        self,
        get_response,
    ):
        get_response.side_effect = [
            {
                "response": json.dumps(
                    {"filename": "id.png", "document_type": "Passport"}
                ),
                "thread_id": "processor",
            },
            {
                "response": json.dumps(
                    {"filename": "id.png", "valid": True, "reason": "Valid."}
                ),
                "thread_id": "validator",
            },
            {
                "response": json.dumps({"loan_application_status": "passed"}),
                "thread_id": "final",
            },
            {
                "response": json.dumps({"loan_application_status": "passed"}),
                "thread_id": "final",
            },
            {
                "response": json.dumps({"loan_application_status": "passed"}),
                "thread_id": "final",
            },
        ]

        with self.assertRaisesRegex(ValueError, "incomplete final decision"):
            agents.invoke_agents(["id.png"], "application_data.json")
        self.assertEqual(get_response.call_count, 5)
        for continuation_call in get_response.call_args_list[-2:]:
            self.assertEqual(continuation_call.kwargs["thread_id"], "final")

    @patch("utils.agents.get_response")
    def test_final_agent_continues_in_the_same_thread_after_an_incomplete_reply(
        self,
        get_response,
    ):
        complete_final_result = {
            "validation_details": {
                "document_authenticity": {
                    "status": "passed",
                    "details": "All documents are authentic.",
                },
                "cross_validation": {
                    "status": "passed",
                    "details": "All fields are consistent.",
                },
                "age_verification": {
                    "status": "passed",
                    "applicant_age": 46,
                    "dob_consistency": "consistent",
                    "details": "Applicant is over 18.",
                },
                "overall_validation_summary": "All checks passed.",
            },
            "loan_application_status": "passed",
        }
        get_response.side_effect = [
            {
                "response": json.dumps(
                    {"filename": "id.png", "document_type": "Passport"}
                ),
                "thread_id": "processor-thread",
            },
            {
                "response": json.dumps(
                    {"filename": "id.png", "valid": True, "reason": "Valid."}
                ),
                "thread_id": "validator-thread",
            },
            {
                "response": json.dumps(
                    {
                        "name": "calculate_years",
                        "parameters": {"date_str": "1980-01-21"},
                    }
                ),
                "thread_id": "final-thread",
            },
            {
                "response": json.dumps(complete_final_result),
                "thread_id": "final-thread",
            },
        ]

        try:
            result = agents.invoke_agents(["id.png"], "application_data.json")
        except ValueError as error:
            self.fail(f"Final Agent should continue after an incomplete reply: {error}")

        self.assertEqual(result["loan_application_status"], "passed")
        continuation_call = get_response.call_args_list[-1]
        self.assertEqual(continuation_call.kwargs["thread_id"], "final-thread")
        self.assertIn("Continue the existing workflow", continuation_call.args[0])
        self.assertNotIn("passed", continuation_call.args[0].lower())
        self.assertNotIn("rejected", continuation_call.args[0].lower())

    def test_passed_final_schema_requires_consistent_typed_validation_details(self):
        invalid_result = {
            "loan_application_status": "passed",
            "validation_details": {
                "document_authenticity": {"status": "failed", "details": "Failed."},
                "cross_validation": {"status": "nonsense", "details": "Unknown."},
                "age_verification": {
                    "status": "passed",
                    "applicant_age": "not-a-number",
                    "dob_consistency": "consistent",
                    "details": "Passed.",
                },
                "overall_validation_summary": ["not", "text"],
            },
        }

        self.assertFalse(agents._is_complete_final_status(invalid_result))

    def test_passed_final_schema_requires_an_adult_applicant(self):
        underage_result = {
            "loan_application_status": "passed",
            "validation_details": {
                "document_authenticity": {"status": "passed", "details": "Passed."},
                "cross_validation": {"status": "passed", "details": "Passed."},
                "age_verification": {
                    "status": "passed",
                    "applicant_age": 5,
                    "dob_consistency": "consistent",
                    "details": "Passed.",
                },
                "overall_validation_summary": "Passed.",
            },
        }

        self.assertFalse(agents._is_complete_final_status(underage_result))

    @patch("utils.agents.get_response")
    def test_reject_fixture_cannot_be_overridden_by_a_passed_final_answer(
        self,
        get_response,
    ):
        passed_final = {
            "validation_details": {
                "document_authenticity": {
                    "status": "passed",
                    "details": "All documents are authentic.",
                },
                "cross_validation": {
                    "status": "passed",
                    "details": "All fields are consistent.",
                },
                "age_verification": {
                    "status": "passed",
                    "applicant_age": 46,
                    "dob_consistency": "consistent",
                    "details": "Applicant is over 18.",
                },
                "overall_validation_summary": "All checks passed.",
            },
            "loan_application_status": "passed",
        }
        get_response.side_effect = [
            {
                "response": json.dumps(
                    {
                        "filename": "demo-reject-ID-Doc.png",
                        "document_type": "Passport",
                    }
                ),
                "thread_id": "processor",
            },
            {
                "response": json.dumps(
                    {
                        "filename": "demo-reject-ID-Doc.png",
                        "valid": False,
                        "reason": "Visible tampering detected.",
                    }
                ),
                "thread_id": "validator",
            },
            {"response": json.dumps(passed_final), "thread_id": "final"},
        ]

        result = agents.invoke_agents(
            ["demo-reject-ID-Doc.png"],
            "application_data.json",
        )

        self.assertEqual(result.get("loan_application_status"), "rejected")
        self.assertIn(
            "Visible tampering detected",
            result["validation_details"]["overall_validation_summary"],
        )

    @patch("utils.agents.get_response")
    def test_regular_invalid_document_cannot_be_overridden_by_passed_final(
        self,
        get_response,
    ):
        passed_final = {
            "validation_details": {
                "document_authenticity": {"status": "passed", "details": "Passed."},
                "cross_validation": {"status": "passed", "details": "Passed."},
                "age_verification": {
                    "status": "passed",
                    "applicant_age": 46,
                    "dob_consistency": "consistent",
                    "details": "Passed.",
                },
                "overall_validation_summary": "Passed.",
            },
            "loan_application_status": "passed",
        }
        get_response.side_effect = [
            {
                "response": json.dumps(
                    {"filename": "id.png", "document_type": "Passport"}
                ),
                "thread_id": "processor",
            },
            {
                "response": json.dumps(
                    {
                        "filename": "id.png",
                        "valid": False,
                        "reason": "Visible tampering detected.",
                    }
                ),
                "thread_id": "validator",
            },
            {"response": json.dumps(passed_final), "thread_id": "final"},
        ]

        with self.assertRaisesRegex(ValueError, "incomplete final decision"):
            agents.invoke_agents(["id.png"], "application_data.json")

    @patch("utils.agents.get_response")
    def test_each_document_must_return_exactly_one_matching_result(
        self,
        get_response,
    ):
        get_response.return_value = {
            "response": json.dumps(
                [
                    {"filename": "id.png"},
                    {"filename": "another.png"},
                ]
            ),
            "thread_id": "processor",
        }

        with self.assertRaisesRegex(ValueError, "exactly one"):
            agents.invoke_agents(["id.png"], "application_data.json")

    @patch("utils.agents.get_response")
    def test_document_result_filename_must_match_the_requested_document(
        self,
        get_response,
    ):
        get_response.return_value = {
            "response": json.dumps({"filename": "someone-elses-id.png"}),
            "thread_id": "processor",
        }

        with self.assertRaisesRegex(ValueError, "does not match"):
            agents.invoke_agents(["id.png"], "application_data.json")

    @patch("utils.agents.get_response")
    def test_document_result_must_match_the_full_requested_path(self, get_response):
        get_response.return_value = {
            "response": json.dumps({"filename": "/uploads/other-app/id.png"}),
            "thread_id": "processor",
        }

        with self.assertRaisesRegex(ValueError, "does not match"):
            agents.invoke_agents(
                ["/uploads/current-app/id.png"],
                "application_data.json",
            )

    @patch("utils.agents.get_response")
    def test_document_filename_mismatch_retries_once_with_exact_path(self, get_response):
        document = "/data/uploads/app-123/ssn.png"
        get_response.side_effect = [
            {
                "response": json.dumps({"filename": "/data/uploads/app-123/ssn-card.png"}),
                "thread_id": "first-processor",
            },
            {
                "response": json.dumps({"filename": document, "document_type": "SSN"}),
                "thread_id": "second-processor",
            },
        ]

        result = agents._collect_document_results(
            [document],
            "Classify and extract information from this document - {document_name}",
            "processor",
            None,
        )

        self.assertEqual(result, [{"filename": document, "document_type": "SSN"}])
        self.assertEqual(get_response.call_count, 2)
        first_message = get_response.call_args_list[0].args[0]
        retry_message = get_response.call_args_list[1].args[0]
        self.assertIn(document, first_message)
        self.assertIn("exact", first_message.lower())
        self.assertIn("exact", retry_message.lower())
        self.assertNotEqual(first_message, retry_message)

    @patch("utils.agents.get_response")
    def test_document_filename_mismatch_still_fails_after_one_retry(self, get_response):
        get_response.return_value = {
            "response": json.dumps({"filename": "/data/uploads/other-app/id.png"}),
            "thread_id": "processor",
        }

        with self.assertRaisesRegex(ValueError, "does not match"):
            agents._collect_document_results(
                ["/data/uploads/current-app/id.png"],
                "Classify and extract information from this document - {document_name}",
                "processor",
                None,
            )

        self.assertEqual(get_response.call_count, 2)

    @patch("utils.agents.get_response")
    def test_pass_demo_recovers_when_final_agent_returns_an_incomplete_tool_call(
        self,
        get_response,
    ):
        get_response.side_effect = [
            {
                "response": json.dumps(
                    {
                        "filename": "./uploads/demo-pass-ID-Doc.png",
                        "document_type": "Passport",
                        "extracted_data": {
                            "name": "Tom Miller",
                            "dob": "1980-01-21",
                        },
                    }
                ),
                "thread_id": "processor",
            },
            {
                "response": json.dumps(
                    {
                        "filename": "./uploads/demo-pass-ID-Doc.png",
                        "valid": True,
                        "reason": "Authorized POC fixture",
                    }
                ),
                "thread_id": "validator",
            },
            {
                "response": json.dumps(
                    {
                        "name": "calculate_years",
                        "parameters": {"date_str": "1980-01-21"},
                    }
                ),
                "thread_id": "final",
            },
            {
                "response": json.dumps(
                    {
                        "name": "calculate_years",
                        "parameters": {"date_str": "1980-01-21"},
                    }
                ),
                "thread_id": "final",
            },
            {
                "response": json.dumps(
                    {
                        "name": "calculate_years",
                        "parameters": {"date_str": "1980-01-21"},
                    }
                ),
                "thread_id": "final",
            },
        ]

        result = agents.invoke_agents(
            ["./uploads/demo-pass-ID-Doc.png"],
            "application_data.json",
        )

        self.assertEqual(result.get("loan_application_status"), "passed")
        self.assertEqual(
            result["validation_details"]["overall_validation_summary"],
            "Authorized POC fixture passed all document checks; the final agent response was incomplete.",
        )
        self.assertEqual(get_response.call_count, 5)

    @patch("utils.agents.get_response")
    def test_pass_demo_recovers_when_final_agent_returns_non_json(self, get_response):
        get_response.side_effect = [
            {
                "response": json.dumps(
                    {
                        "filename": "demo-pass-ID-Doc.png",
                        "document_type": "Passport",
                    }
                ),
                "thread_id": "processor",
            },
            {
                "response": json.dumps(
                    {
                        "filename": "demo-pass-ID-Doc.png",
                        "valid": True,
                        "reason": "Authorized POC fixture.",
                    }
                ),
                "thread_id": "validator",
            },
            {"response": "final response was not JSON", "thread_id": "final"},
            {"response": "final response was not JSON", "thread_id": "final"},
            {"response": "final response was not JSON", "thread_id": "final"},
        ]

        result = agents.invoke_agents(
            ["demo-pass-ID-Doc.png"],
            "application_data.json",
        )

        self.assertEqual(result["loan_application_status"], "passed")

    @patch("utils.agents.get_response")
    def test_reject_demo_recovers_when_final_agent_response_is_incomplete(
        self,
        get_response,
    ):
        get_response.side_effect = [
            {
                "response": json.dumps(
                    {
                        "filename": "./uploads/demo-reject-ID-Doc.png",
                        "document_type": "Passport",
                        "extracted_data": {"name": "Tom Miller"},
                    }
                ),
                "thread_id": "processor",
            },
            {
                "response": json.dumps(
                    {
                        "filename": "./uploads/demo-reject-ID-Doc.png",
                        "valid": False,
                        "reason": "Sample document is not authentic.",
                    }
                ),
                "thread_id": "validator",
            },
            {
                "response": json.dumps({"name": "unfinished_final_tool"}),
                "thread_id": "final",
            },
            {
                "response": json.dumps({"name": "unfinished_final_tool"}),
                "thread_id": "final",
            },
            {
                "response": json.dumps({"name": "unfinished_final_tool"}),
                "thread_id": "final",
            },
        ]

        result = agents.invoke_agents(
            ["./uploads/demo-reject-ID-Doc.png"],
            "application_data.json",
        )

        self.assertEqual(result.get("loan_application_status"), "rejected")
        self.assertIn(
            "Sample document is not authentic",
            result["validation_details"]["overall_validation_summary"],
        )

    def test_background_failure_is_persisted_instead_of_staying_pending(self):
        application = SimpleNamespace(
            id=7,
            app_id_str="pdf_test",
            status="Pending ",
            validation_comments=None,
        )
        session = Mock()
        session.query.return_value.filter.return_value.first.return_value = application

        with (
            patch.object(main.database, "SessionLocal", return_value=session),
            patch.object(main, "invoke_agents", side_effect=RuntimeError("stream failed")),
        ):
            main.process_application_in_background(
                7,
                ["id.png"],
                "application_data.json",
                session,
            )

        self.assertEqual(application.status, "Processing Failed")
        self.assertIn("processing failed", application.validation_comments.lower())
        self.assertEqual(session.commit.call_count, 2)
        session.close.assert_called_once()

    def test_background_status_tracks_processing_and_retrying_before_completion(self):
        class TrackingApplication:
            def __init__(self):
                self.id = 8
                self.app_id_str = "pdf_tracking"
                self.validation_comments = None
                self.status_history = []
                self._status = "Pending"

            @property
            def status(self):
                return self._status

            @status.setter
            def status(self, value):
                self._status = value
                self.status_history.append(value)

        application = TrackingApplication()
        session = Mock()
        session.query.return_value.filter.return_value.first.return_value = application

        def invoke_with_retry(**kwargs):
            kwargs["on_retry"](2, RuntimeError("temporary WXO interruption"))
            return {
                "loan_application_status": "rejected",
                "validation_details": {"summary": "Documents did not match."},
            }

        with (
            patch.object(main.database, "SessionLocal", return_value=session),
            patch.object(main, "invoke_agents", side_effect=invoke_with_retry),
        ):
            main.process_application_in_background(
                8,
                ["id.png"],
                "application_data.json",
                session,
            )

        self.assertEqual(
            application.status_history,
            ["Processing", "Retrying", "rejected"],
        )
        self.assertIn("Documents did not match", application.validation_comments)
        self.assertEqual(session.commit.call_count, 3)


if __name__ == "__main__":
    unittest.main()
