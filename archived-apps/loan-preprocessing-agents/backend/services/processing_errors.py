"""Convert stored internal errors into safe application-detail problem fields."""

import re
from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict


class ProcessingFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    service: str
    stage: str
    provider_code: str
    http_status: int | None = None
    trace_id: str | None = None
    documentation_url: str | None = None
    retryable_now: bool
    action: str


_AGENT_STAGES = {
    "Invoking Document Processor Agent": "document_processing_agent",
    "Invoking Document Validator Agent": "document_validation_agent",
    "Invoking Final Decision Agent": "final_decision_agent",
}
_DOCUMENTATION_URL = "https://cloud.ibm.com/apidocs/watsonx-ai"
_HTTP_STATUS = re.compile(r"Status code:\s*(\d{3})", re.IGNORECASE)
_PROVIDER_CODE = re.compile(r'"code"\s*:\s*"([A-Za-z0-9_.-]{1,128})"')
_TRACE_ID = re.compile(
    r'"trace"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F-]{27,40})"'
)


def latest_agent_stage(events: Iterable[object]) -> str:
    stage = "agent_workflow"
    ordered = sorted(
        events,
        key=lambda event: (
            getattr(event, "occurred_at", None) is not None,
            getattr(event, "occurred_at", None),
            getattr(event, "id", 0) or 0,
        ),
    )
    for event in ordered:
        if getattr(event, "stage", "") != "invoke_agent":
            continue
        payload = getattr(event, "payload", None)
        message = payload.get("message") if isinstance(payload, Mapping) else payload
        candidate = _AGENT_STAGES.get(message) if isinstance(message, str) else None
        if candidate:
            stage = candidate
    return stage


def classify_processing_error(
    error_text: str | None, *, stage: str = "agent_workflow"
) -> ProcessingFailure | None:
    if not error_text:
        return None

    status_match = _HTTP_STATUS.search(error_text)
    http_status = int(status_match.group(1)) if status_match else None
    code_match = _PROVIDER_CODE.search(error_text)
    provider_code = (
        "token_quota_reached"
        if code_match and code_match.group(1) == "token_quota_reached"
        else "processing_failed"
    )
    trace_match = _TRACE_ID.search(error_text)
    trace_id = trace_match.group(1) if trace_match else None
    normalized = error_text.casefold()
    is_watsonx = (
        provider_code == "token_quota_reached"
        or "ibm_watsonx_ai" in normalized
        or ".ml.cloud.ibm.com" in normalized
    )
    service = "watsonx_ai" if is_watsonx else "agent_workflow"
    documentation_url = _DOCUMENTATION_URL if is_watsonx else None

    if (
        error_text.startswith("Agent result filename ")
        and " does not match requested document " in error_text
    ):
        category = "document_mismatch"
        provider_code = "document_filename_mismatch"
        retryable_now = False
        action = "check_agent_document_mapping"
    elif provider_code == "token_quota_reached":
        category = "provider_quota"
        retryable_now = False
        action = "check_service_configuration"
    elif http_status in (401, 403):
        category = "provider_authorization"
        retryable_now = False
        action = "check_service_configuration"
    elif http_status == 429:
        category = "provider_rate_limit"
        retryable_now = True
        action = "retry_later"
    elif http_status is not None and http_status >= 500:
        category = "provider_unavailable"
        retryable_now = True
        action = "retry_later"
    elif "timeout" in normalized or "timed out" in normalized:
        category = "timeout"
        retryable_now = True
        action = "retry_later"
    else:
        category = "unknown"
        retryable_now = True
        action = "review_technical_details"

    return ProcessingFailure(
        category=category,
        service=service,
        stage=stage,
        provider_code=provider_code,
        http_status=http_status,
        trace_id=trace_id,
        documentation_url=documentation_url,
        retryable_now=retryable_now,
        action=action,
    )


def describe_application_failure(application: object) -> ProcessingFailure | None:
    if str(getattr(application, "status", "")).strip().casefold() != "processing failed":
        return None

    runs = [
        run for run in getattr(application, "processing_runs", ())
        if getattr(run, "status", "") == "failed" and getattr(run, "error_text", None)
    ]
    if not runs:
        return None
    latest_run = max(
        runs, key=lambda run: (getattr(run, "attempt_number", 0), getattr(run, "id", 0) or 0)
    )
    return classify_processing_error(
        latest_run.error_text,
        stage=latest_agent_stage(getattr(application, "agent_events", ())),
    )
