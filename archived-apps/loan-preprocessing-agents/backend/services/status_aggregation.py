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
    "submit_application": "Submit application",
    "process_documents": "Process documents",
    "generate_decision": "Generate decision",
    "view_applications": "View applications",
}

_READY_MESSAGE = "Available"
_LIMITED_MESSAGE = "Some required dependencies need attention"
_UNAVAILABLE_MESSAGE = "One or more required dependencies are unavailable"
_OVERALL_COPY = {
    StatusValue.READY: ("System ready", "All capabilities are available"),
    StatusValue.LIMITED: ("System limited", "Some capabilities need attention"),
    StatusValue.UNAVAILABLE: (
        "System unavailable",
        "Core application capabilities are unavailable",
    ),
}


def _capability_status(
    capability_id: str, dependencies: Mapping[str, DependencyStatus]
) -> StatusValue:
    required = (dependencies.get(name) for name in CAPABILITY_DEPENDENCIES[capability_id])
    statuses = [
        item.status if item is not None else StatusValue.UNKNOWN for item in required
    ]
    if any(status in (StatusValue.UNAVAILABLE, StatusValue.NOT_CONFIGURED) for status in statuses):
        return StatusValue.UNAVAILABLE
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
        message = {
            StatusValue.READY: _READY_MESSAGE,
            StatusValue.LIMITED: _LIMITED_MESSAGE,
            StatusValue.UNAVAILABLE: _UNAVAILABLE_MESSAGE,
        }[status]
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
