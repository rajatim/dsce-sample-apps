from collections.abc import Mapping, Sequence

from status_models import (
    CapabilityStatus,
    DependencyStatus,
    OverallStatus,
    StatusValue,
)


CAPABILITY_DEPENDENCIES = {
    "submit_application": ("loan_api", "postgresql", "cos"),
    "process_documents": (
        "cos", "watsonx_ai", "wxo", "document_processing_agent",
        "document_validation_agent",
    ),
    "generate_decision": (
        "cos", "watsonx_ai", "wxo", "document_processing_agent",
        "document_validation_agent", "final_decision_agent",
    ),
    "view_applications": ("loan_api", "postgresql"),
}

CAPABILITY_LABELS = {
    "submit_application": "Submit an application",
    "process_documents": "Process documents",
    "generate_decision": "Generate a loan decision",
    "view_applications": "View applications",
}

_CAPABILITY_MESSAGES = {
    "submit_application": {
        StatusValue.READY: "Online form and PDF upload are available.",
        StatusValue.LIMITED: (
            "You can still submit an application, but it may take longer than usual."
        ),
        StatusValue.UNAVAILABLE: (
            "Application submission is unavailable. Please try again later."
        ),
        StatusValue.NOT_CONFIGURED: (
            "Application submission is not configured for this demo."
        ),
    },
    "process_documents": {
        StatusValue.READY: "Uploaded documents can be extracted and validated.",
        StatusValue.LIMITED: (
            "You can continue, but document processing may take longer than usual."
        ),
        StatusValue.UNAVAILABLE: (
            "Document processing is unavailable. Please try again later."
        ),
        StatusValue.NOT_CONFIGURED: (
            "Document processing is not configured for this demo."
        ),
    },
    "generate_decision": {
        StatusValue.READY: (
            "Agent processing is available. Results may take 2–4 minutes."
        ),
        StatusValue.LIMITED: (
            "You can continue, but a loan decision may take longer than usual."
        ),
        StatusValue.UNAVAILABLE: (
            "Loan decisions are unavailable. Please try again later."
        ),
        StatusValue.NOT_CONFIGURED: (
            "Loan decisions are not configured for this demo."
        ),
    },
    "view_applications": {
        StatusValue.READY: (
            "Application history and processing details are available."
        ),
        StatusValue.LIMITED: (
            "You can still view applications, but history may take longer to load."
        ),
        StatusValue.UNAVAILABLE: (
            "Application history is unavailable. Please try again later."
        ),
        StatusValue.NOT_CONFIGURED: (
            "Application history is not configured for this demo."
        ),
    },
}
_OVERALL_COPY = {
    StatusValue.READY: (
        "Demo ready",
        "You can submit and review loan applications.",
    ),
    StatusValue.LIMITED: (
        "Some demo features are limited",
        "Check the details below before continuing.",
    ),
    StatusValue.UNAVAILABLE: (
        "The demo is currently unavailable",
        "Please try again later.",
    ),
}


def _capability_status(
    capability_id: str, dependencies: Mapping[str, DependencyStatus]
) -> StatusValue:
    required = (dependencies.get(name) for name in CAPABILITY_DEPENDENCIES[capability_id])
    statuses = [
        item.status if item is not None else StatusValue.UNKNOWN for item in required
    ]
    if StatusValue.UNAVAILABLE in statuses:
        return StatusValue.UNAVAILABLE
    if StatusValue.NOT_CONFIGURED in statuses:
        return StatusValue.NOT_CONFIGURED
    if any(
        status in (StatusValue.LIMITED, StatusValue.UNKNOWN, StatusValue.CHECKING)
        for status in statuses
    ):
        return StatusValue.LIMITED
    return StatusValue.READY


def build_capabilities(
    dependencies: Mapping[str, DependencyStatus],
) -> list[CapabilityStatus]:
    capabilities = []
    for capability_id in CAPABILITY_DEPENDENCIES:
        status = _capability_status(capability_id, dependencies)
        message = _CAPABILITY_MESSAGES[capability_id][status]
        capabilities.append(
            CapabilityStatus(
                id=capability_id,
                label=CAPABILITY_LABELS[capability_id],
                status=status,
                message=message,
            )
        )
    return capabilities


def build_overall(capabilities: Sequence[CapabilityStatus]) -> OverallStatus:
    statuses = {item.id: item.status for item in capabilities}
    if all(statuses.get(capability_id) is StatusValue.READY for capability_id in CAPABILITY_DEPENDENCIES):
        status = StatusValue.READY
    elif (
        statuses.get("submit_application") is StatusValue.UNAVAILABLE
        and statuses.get("view_applications") is StatusValue.UNAVAILABLE
    ):
        status = StatusValue.UNAVAILABLE
    else:
        status = StatusValue.LIMITED
    title, message = _OVERALL_COPY[status]
    return OverallStatus(status=status, title=title, message=message)
