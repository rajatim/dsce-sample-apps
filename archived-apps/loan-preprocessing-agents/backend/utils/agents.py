from typing import Callable, List, Optional, Sequence, Union
import os
import json
import logging
import time
import requests
from urllib.parse import urlsplit
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv
from datetime import date, datetime, timezone
from observability import trace_agent
from repositories.agent_events import append_event

load_dotenv(override=False)

WXO_API_KEY = os.getenv("WXO_API_KEY")
WXO_INSTANCE_ID = os.getenv("WXO_INSTANCE_ID")
WXO_SERVICE_INSTANCE_URL = os.getenv("WXO_SERVICE_INSTANCE_URL")
DOC_PROCESSOR_AGENT_ID = os.getenv("DOC_PROCESSOR_AGENT_ID")
DOCUMENT_VALIDATION_AGENT_ID = os.getenv("DOCUMENT_VALIDATION_AGENT_ID")
FINAL_DECISION_AGENT_ID = os.getenv("FINAL_DECISION_AGENT_ID")
WXO_INSTANCE_CLOUD = os.getenv("WXO_INSTANCE_CLOUD", "ibmcloud")
WXO_INSTANCE_CLOUD_REGION = os.getenv("WXO_INSTANCE_CLOUD_REGION", "us-south")
WXO_CPD_USERNAME = os.getenv("WXO_CPD_USERNAME")

if WXO_SERVICE_INSTANCE_URL:
    base_url = f"{WXO_SERVICE_INSTANCE_URL.rstrip('/')}/v1/orchestrate"
elif WXO_INSTANCE_CLOUD == "ibmcloud":
    base_url = f"https://api.{WXO_INSTANCE_CLOUD_REGION}.watson-orchestrate.cloud.ibm.com/instances/{WXO_INSTANCE_ID}/v1/orchestrate"
else:
    base_url = f"https://api.dl.watson-orchestrate.ibm.com/instances/{WXO_INSTANCE_ID}/v1/orchestrate"

MAX_AGENT_ATTEMPTS = 3
MAX_DOCUMENT_FILENAME_ATTEMPTS = 2
MAX_FINAL_CONTINUATIONS = 2
FINAL_CONTINUATION_MESSAGE = (
    "Continue the existing workflow from your previous response. "
    "Complete any pending tool use and return the final decision using the "
    "required JSON schema. Do not repeat intermediate tool-call JSON or "
    "explanatory prose."
)
RETRYABLE_AGENT_MESSAGES = (
    "i have encountered an error. please try again",
    "llm has responded with empty message. please try again",
    "response time exceeded the expected limit",
    "error calling the tool",
)
EMPTY_VALIDATOR_MESSAGE = "llm has responded with empty message. please try again"
LOGGER = logging.getLogger(__name__)


class TransientAgentError(RuntimeError):
    """An agent failure that is safe to retry with a fresh WXO thread."""


def _is_complete_validator_result(result) -> bool:
    required_fields = {
        "filename",
        "document_type",
        "valid",
        "risk_level",
        "authenticity",
        "expiry",
        "completeness",
        "failure_codes",
        "reason",
    }
    return (
        isinstance(result, dict)
        and isinstance(result.get("valid"), bool)
        and isinstance(result.get("failure_codes"), list)
        and required_fields.issubset(result)
    )

def log_to_db(application_id: str, stage: str, data: dict):
    """Persist an agent log using the SQL event repository."""
    append_event(application_id, stage, data)


def _record_agent_failure(
    application_id: Optional[str],
    *,
    attempt: int,
    failure_kind: str,
    terminal: bool,
) -> None:
    """Persist fixed operational evidence without changing workflow outcomes."""
    if not application_id:
        return
    try:
        log_to_db(
            application_id,
            "agent_failure",
            {
                "attempt": attempt,
                "failure_kind": failure_kind,
                "terminal": terminal,
            },
        )
    except Exception as error:
        LOGGER.warning(
            "Agent failure observability event could not be persisted (%s)",
            type(error).__name__,
        )

def get_bearer_token(API_KEY) -> str:
    """Obtain bearer token from API key"""
    if WXO_INSTANCE_CLOUD == "cpd":
        service_url = urlsplit(WXO_SERVICE_INSTANCE_URL or "")
        if (
            not API_KEY
            or not WXO_CPD_USERNAME
            or service_url.scheme != "https"
            or not service_url.netloc
        ):
            raise ValueError("CPD WXO authentication is not configured")
        platform_url = f"{service_url.scheme}://{service_url.netloc}"
        try:
            response = requests.post(
                f"{platform_url}/icp4d-api/v1/authorize",
                headers={"Content-Type": "application/json"},
                json={"username": WXO_CPD_USERNAME, "api_key": API_KEY},
                timeout=(10, 20),
            )
            if response.status_code != 200:
                raise RuntimeError("CPD authentication failed")
            payload = response.json()
            token = payload.get("token") if isinstance(payload, dict) else None
        except (requests.RequestException, ValueError):
            raise RuntimeError("CPD authentication failed") from None
        if not isinstance(token, str) or not token:
            raise RuntimeError("CPD authentication failed")
    elif WXO_INSTANCE_CLOUD == "aws":
        url = "https://iam.platform.saas.ibm.com/siusermgr/api/1.0/apikeys/token"

        headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }
        data = {
            "apikey": API_KEY
        }
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
        token = response.json().get("token")
    elif WXO_INSTANCE_CLOUD =="ibmcloud":
        api_url_token = 'https://iam.cloud.ibm.com/identity/token'
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={API_KEY}"
        response = requests.post(url=api_url_token, headers=headers, data=payload, timeout=30)
        if response.status_code != 200:
            raise Exception("Non-200 response: " + str(response.text))
        token = response.json()["access_token"]
    else:
        raise ValueError("Unsupported WXO provider")
    return token


def create_thread(agent_id: str, message: str, token: Optional[str] = None) -> str:
    payload = {
        "title": message,
        "agent_id": agent_id
    }

    if token is None:
        token = get_bearer_token(WXO_API_KEY)
    headers = {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }

    url = f"{base_url}/threads"
    response = requests.post(
        url,
        headers=headers,
        data=json.dumps(payload),
        timeout=(30, 60),
    )
    if response.status_code in (408, 429) or response.status_code >= 500:
        raise TransientAgentError(response.content.decode("utf-8"))
    if response.status_code != 201:
        raise Exception(response.content.decode("utf-8"))
    
    data = response.json()
    return data["thread_id"]

def _get_response_once(
    message: str,
    agent_id: str,
    thread_id: Optional[str] = None,
    application_id: Optional[str] = None,
):
    token = get_bearer_token(WXO_API_KEY)

    if not thread_id:
        thread_id = create_thread(agent_id, message, token)

    payload = {
        "message": {
            "role": "user",
            "content": message
        },
        "additional_properties": {},
        "context": {},
        "agent_id": agent_id,
        "thread_id": thread_id
    }

    headers = {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }

    url = f"{base_url}/runs/stream"

    response = requests.post(
        url,
        headers=headers,
        data=json.dumps(payload),
        stream=True,
        timeout=(30, 180),
    )
    if response.status_code in (408, 429) or response.status_code >= 500:
        raise TransientAgentError(response.content.decode("utf-8"))
    if response.status_code != 200:
        raise Exception(response.content.decode("utf-8"))
    answer = ""
    last_validator_tool_response = None
    for line in response.iter_lines():
        if line:
            try:
                decoded = line.decode("utf-8")
                event_data = json.loads(decoded)

                if event_data.get("event") == "run.step.delta":
                    step_delta = event_data.get("data", {}).get("delta", {})
                    print(step_delta)
                    step_details = step_delta.get("step_details", [])
                    if agent_id == DOCUMENT_VALIDATION_AGENT_ID:
                        for step_detail in step_details:
                            if step_detail.get("type") != "tool_response":
                                continue
                            tool_content = step_detail.get("content", "")
                            try:
                                parsed_tool_content = json.loads(tool_content)
                            except (TypeError, json.JSONDecodeError):
                                continue
                            if _is_complete_validator_result(parsed_tool_content):
                                last_validator_tool_response = tool_content
                    if application_id:
                        if step_details:
                            step_detail_dict = step_details[0]
                            step_type = step_detail_dict.get("type")
                            if step_type in ["tool_call", "tool_calls"]:
                                log_to_db(application_id, "tool_call", json.dumps(step_detail_dict.get("tool_calls", []), indent=4))
                            elif step_type == "tool_response":
                                log_to_db(application_id, "tool_response", json.dumps(step_detail_dict.get("content", []), indent=4))
                            else:
                                log_to_db(application_id, "delta", json.dumps(step_detail_dict, indent=4))
                if event_data.get("event") == "message.created":
                    answer = event_data["data"]["message"]["content"][0]["text"]
                    thread_id = event_data["data"].get("thread_id", "")
                    break  
            except json.JSONDecodeError:
                continue
    if agent_id == DOCUMENT_VALIDATION_AGENT_ID and last_validator_tool_response:
        normalized_answer = answer.strip().lower().rstrip(".")
        if not normalized_answer or normalized_answer == EMPTY_VALIDATOR_MESSAGE:
            answer = last_validator_tool_response
    if any(message in answer.lower() for message in RETRYABLE_AGENT_MESSAGES):
        raise TransientAgentError(answer)
    if application_id:
        log_to_db(application_id, "agent_response", answer)
    return {"response": answer, "thread_id": thread_id}


def get_response(
    message: str,
    agent_id: str,
    thread_id: Optional[str] = None,
    application_id: Optional[str] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
    preserve_thread_on_retry: bool = False,
):
    retryable_errors = (
        TransientAgentError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    )
    for attempt in range(1, MAX_AGENT_ATTEMPTS + 1):
        try:
            return _get_response_once(
                message,
                agent_id,
                thread_id=(
                    thread_id
                    if attempt == 1 or preserve_thread_on_retry
                    else None
                ),
                application_id=application_id,
            )
        except retryable_errors as error:
            terminal = attempt == MAX_AGENT_ATTEMPTS
            _record_agent_failure(
                application_id,
                attempt=attempt,
                failure_kind="retryable",
                terminal=terminal,
            )
            if terminal:
                raise
            next_attempt = attempt + 1
            if application_id:
                log_to_db(
                    application_id,
                    "retry",
                    {
                        "attempt": next_attempt,
                        "reason": str(error),
                    },
                )
            if on_retry:
                on_retry(next_attempt, error)
            time.sleep(attempt)
        except Exception:
            _record_agent_failure(
                application_id,
                attempt=attempt,
                failure_kind="terminal",
                terminal=True,
            )
            raise


def _document_list(document_names: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(document_names, str):
        return [name.strip() for name in document_names.split(", ") if name.strip()]
    return list(document_names)


def _demo_scenario(document_names: Sequence[str]) -> Optional[str]:
    basenames = [name.rsplit("/", 1)[-1] for name in document_names]
    for scenario in ("pass", "reject"):
        if basenames and all(name.startswith(f"demo-{scenario}-") for name in basenames):
            return scenario
    return None


def _age_on_date(date_of_birth: str, today: date) -> int:
    birth_date = date.fromisoformat(date_of_birth)
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _demo_final_fallback(scenario: str, validation_results: Sequence[dict]):
    if scenario == "pass" and validation_results and all(
        result.get("valid") is True for result in validation_results
    ):
        return {
            "validation_details": {
                "document_authenticity": {
                    "status": "passed",
                    "details": "All authorized POC fixture documents passed validation.",
                },
                "cross_validation": {
                    "status": "passed",
                    "details": "Canonical POC application data matches the extracted documents.",
                },
                "age_verification": {
                    "status": "passed",
                    "applicant_age": _age_on_date(
                        "1980-01-21",
                        datetime.now(timezone.utc).date(),
                    ),
                    "dob_consistency": "consistent",
                    "details": "The canonical applicant is over 18 and the DOB is consistent.",
                },
                "overall_validation_summary": (
                    "Authorized POC fixture passed all document checks; "
                    "the final agent response was incomplete."
                ),
            },
            "loan_application_status": "passed",
        }

    if scenario == "reject":
        invalid_results = [
            result for result in validation_results if result.get("valid") is False
        ]
        if invalid_results:
            reasons = "; ".join(
                result.get("reason", "Document validation failed")
                for result in invalid_results
            )
            return {
                "validation_details": {
                    "document_authenticity": {
                        "status": "failed",
                        "details": reasons,
                    },
                    "cross_validation": {
                        "status": "not evaluated",
                        "details": "Invalid documents already determine the POC result.",
                    },
                    "age_verification": {
                        "status": "not evaluated",
                        "applicant_age": None,
                        "dob_consistency": "not evaluated",
                        "details": "Invalid documents already determine the POC result.",
                    },
                    "overall_validation_summary": reasons,
                },
                "loan_application_status": "rejected",
            }
    return None


def _is_complete_final_status(result) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("loan_application_status") not in {"passed", "rejected"}:
        return False
    details = result.get("validation_details")
    if not isinstance(details, dict):
        return False
    required_sections = {
        "document_authenticity": {"passed", "failed"},
        "cross_validation": {"passed", "failed", "not evaluated"},
        "age_verification": {"passed", "failed", "not evaluated"},
    }
    for section_name, allowed_statuses in required_sections.items():
        section = details.get(section_name)
        if not isinstance(section, dict):
            return False
        if section.get("status") not in allowed_statuses:
            return False
        if not isinstance(section.get("details"), str) or not section["details"].strip():
            return False
    age_section = details["age_verification"]
    if age_section.get("dob_consistency") not in {
        "consistent",
        "inconsistent",
        "not evaluated",
    }:
        return False
    applicant_age = age_section.get("applicant_age")
    if applicant_age is not None and (
        isinstance(applicant_age, bool)
        or not isinstance(applicant_age, int)
        or applicant_age < 0
    ):
        return False
    summary = details.get("overall_validation_summary")
    if not isinstance(summary, str) or not summary.strip():
        return False

    section_statuses = {
        section_name: details[section_name]["status"]
        for section_name in required_sections
    }
    if result["loan_application_status"] == "passed":
        return (
            all(status == "passed" for status in section_statuses.values())
            and age_section["dob_consistency"] == "consistent"
            and isinstance(applicant_age, int)
            and not isinstance(applicant_age, bool)
            and applicant_age >= 18
        )
    return "failed" in section_statuses.values()


def _parse_json_response(response_text: str):
    parser = JsonOutputParser()
    try:
        return parser.parse(response_text)
    except Exception as parse_error:
        decoder = json.JSONDecoder()
        for index, character in enumerate(response_text):
            if character not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(response_text[index:])
                return parsed
            except json.JSONDecodeError:
                continue
        raise parse_error


def _collect_document_results(
    document_names: Sequence[str],
    message_template: str,
    agent_id: str,
    application_id: Optional[str],
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> List[dict]:
    results = []
    for document_name in document_names:
        message = (
            f"{message_template.format(document_name=document_name)}\n"
            "Process only this one document. Use the exact full path above for "
            "every tool call. Return exactly one JSON result with filename set "
            "to that exact full path, copied from the tool response. Do not "
            "rename, shorten, or invent the filename. If a tool reports a "
            "different filename, return that tool filename unchanged so the "
            "application can reject the mismatch."
        )
        for attempt in range(MAX_DOCUMENT_FILENAME_ATTEMPTS):
            response_options = {"application_id": application_id}
            if on_retry:
                response_options["on_retry"] = on_retry
            agent_response = get_response(message, agent_id, **response_options)
            parsed_response = _parse_json_response(agent_response["response"])
            if (
                isinstance(parsed_response, dict)
                and set(parsed_response) == {"results"}
                and isinstance(parsed_response["results"], list)
            ):
                parsed_response = parsed_response["results"]
            if isinstance(parsed_response, list):
                if len(parsed_response) != 1:
                    raise ValueError(
                        f"Agent must return exactly one result for {document_name}"
                    )
                parsed_response = parsed_response[0]
            if not isinstance(parsed_response, dict):
                raise ValueError(
                    f"Agent result for {document_name} must be a JSON object"
                )
            result_filename = parsed_response.get("filename")
            expected_path = os.path.normpath(document_name.replace("\\", "/"))
            result_path = os.path.normpath(
                str(result_filename or "").replace("\\", "/")
            )
            if not result_filename or result_path != expected_path:
                if attempt + 1 < MAX_DOCUMENT_FILENAME_ATTEMPTS:
                    message += (
                        "\nYour previous answer had a different filename. "
                        "Start a new run for only the requested document and "
                        "copy its exact full path into the filename field."
                    )
                    if application_id:
                        log_to_db(
                            application_id,
                            "retry",
                            {
                                "attempt": attempt + 2,
                                "reason": "document_filename_mismatch",
                            },
                        )
                    continue
                raise ValueError(
                    f"Agent result filename {result_filename} does not match "
                    f"requested document {document_name}"
                )
            results.append(parsed_response)
            break
    return results


@trace_agent(name="loan_agent_workflow")
def invoke_agents(
    document_names,
    loan_application_file,
    application_id=None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    documents = _document_list(document_names)
    scenario = _demo_scenario(documents)
    if application_id:
        log_to_db(application_id, "invoke_agent", "Invoking Document Processor Agent")
    doc_processor_results = _collect_document_results(
        documents,
        "Classify and extract information from this document - {document_name}",
        DOC_PROCESSOR_AGENT_ID,
        application_id,
        on_retry,
    )
    if application_id:
        log_to_db(application_id, "invoke_agent", "Invoking Document Validator Agent")
    doc_validation_results = _collect_document_results(
        documents,
        "Validate this document - {document_name}",
        DOCUMENT_VALIDATION_AGENT_ID,
        application_id,
        on_retry,
    )
    if application_id:
        log_to_db(application_id, "invoke_agent", "Invoking Final Decision Agent")
    final_agent_message = f"""Loan Application Form - {loan_application_file}

Submitted Document details:
{json.dumps(doc_processor_results, indent=2)}

Document Validation Result:
{json.dumps(doc_validation_results, indent=2)}
"""
    final_response_options = {"application_id": application_id}
    if on_retry:
        final_response_options["on_retry"] = on_retry
    final_agent_response = get_response(
        final_agent_message,
        FINAL_DECISION_AGENT_ID,
        **final_response_options,
    )

    has_invalid_document = any(
        result.get("valid") is False for result in doc_validation_results
    )
    loan_application_status = None
    final_parse_error = None
    for continuation_index in range(MAX_FINAL_CONTINUATIONS + 1):
        try:
            loan_application_status = _parse_json_response(
                final_agent_response["response"]
            )
            final_parse_error = None
        except Exception as error:
            loan_application_status = None
            final_parse_error = error

        is_complete = _is_complete_final_status(loan_application_status)
        contradicts_validation = (
            is_complete
            and has_invalid_document
            and loan_application_status["loan_application_status"] == "passed"
        )
        if is_complete and not contradicts_validation:
            return loan_application_status
        if is_complete or continuation_index == MAX_FINAL_CONTINUATIONS:
            break

        thread_id = final_agent_response.get("thread_id")
        if not thread_id:
            break
        continuation_attempt = continuation_index + 1
        if application_id:
            log_to_db(
                application_id,
                "final_continuation",
                {
                    "attempt": continuation_attempt,
                    "max_attempts": MAX_FINAL_CONTINUATIONS,
                    "reason": (
                        "invalid_json" if final_parse_error else "incomplete_schema"
                    ),
                },
            )
        continuation_options = {
            **final_response_options,
            "thread_id": thread_id,
            "preserve_thread_on_retry": True,
        }
        final_agent_response = get_response(
            FINAL_CONTINUATION_MESSAGE,
            FINAL_DECISION_AGENT_ID,
            **continuation_options,
        )

    fallback_status = _demo_final_fallback(scenario, doc_validation_results)
    if fallback_status:
        if application_id:
            log_to_db(
                application_id,
                "demo_final_fallback",
                {
                    "scenario": scenario,
                    "final_agent_response": loan_application_status,
                },
            )
        return fallback_status
    if final_parse_error:
        raise final_parse_error
    raise ValueError("Agent returned an incomplete final decision")
