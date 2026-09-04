"""Low-cost, read-only checks for the Loan demo's external dependencies."""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import text

from status_models import DependencyStatus, EvidenceKind, StatusValue


LOGGER = logging.getLogger(__name__)
HTTP_TIMEOUT = (2, 3)
IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
IAM_TOKEN_GRANT = "urn:ibm:params:oauth:grant-type:apikey"
TRUE_VALUES = {"1", "true", "yes", "on"}

_LABELS = {
    "postgresql": "PostgreSQL",
    "cos": "Cloud Object Storage",
    "watsonx_ai": "watsonx.ai",
    "wxo": "watsonx Orchestrate",
    "document_processing_agent": "Document processing agent",
    "document_validation_agent": "Document validation agent",
    "final_decision_agent": "Final decision agent",
    "openllmetry": "OpenLLMetry",
}
_WXO_AGENTS = (
    ("document_processing_agent", "DOC_PROCESSOR_AGENT_ID"),
    ("document_validation_agent", "DOCUMENT_VALIDATION_AGENT_ID"),
    ("final_decision_agent", "FINAL_DECISION_AGENT_ID"),
)


class _HTTPStatusFailure(RuntimeError):
    """Internal marker that deliberately carries no provider response content."""


def _dependency(
    dependency_id: str,
    status: StatusValue,
    evidence: EvidenceKind,
    message: str,
    checked_at: datetime,
) -> DependencyStatus:
    return DependencyStatus(
        id=dependency_id,
        label=_LABELS[dependency_id],
        status=status,
        evidence=evidence,
        message=message,
        checked_at=checked_at,
    )


def _warning(service_label: str, error: Exception) -> None:
    LOGGER.warning("%s status check failed (%s)", service_label, type(error).__name__)


def _value(environment: Mapping[str, str], name: str) -> str:
    return environment.get(name, "").strip()


def _access_token(http: Any, api_key: str) -> str:
    response = http.post(
        IAM_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": IAM_TOKEN_GRANT, "apikey": api_key},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise _HTTPStatusFailure()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise _HTTPStatusFailure()
    return token


def check_postgresql(
    session_factory: Callable[[], Any], checked_at: datetime
) -> DependencyStatus:
    """Execute a single read-only PostgreSQL liveness statement."""
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception as error:
        _warning(_LABELS["postgresql"], error)
        return _dependency(
            "postgresql",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "PostgreSQL is unavailable.",
            checked_at,
        )
    return _dependency(
        "postgresql",
        StatusValue.READY,
        EvidenceKind.LIVE_CHECK,
        "PostgreSQL is reachable.",
        checked_at,
    )


def check_cos(
    client_factory: Callable[[], Any], bucket_name: str, checked_at: datetime
) -> DependencyStatus:
    """Check COS bucket metadata without listing or mutating objects."""
    if not bucket_name.strip():
        return _dependency(
            "cos",
            StatusValue.NOT_CONFIGURED,
            EvidenceKind.NOT_VERIFIED,
            "Cloud Object Storage is not configured.",
            checked_at,
        )
    try:
        client = client_factory()
    except ValueError:
        return _dependency(
            "cos",
            StatusValue.NOT_CONFIGURED,
            EvidenceKind.NOT_VERIFIED,
            "Cloud Object Storage is not configured.",
            checked_at,
        )
    except Exception as error:
        _warning(_LABELS["cos"], error)
        return _dependency(
            "cos",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "Cloud Object Storage is unavailable.",
            checked_at,
        )
    try:
        client.head_bucket(bucket_name)
    except Exception as error:
        _warning(_LABELS["cos"], error)
        return _dependency(
            "cos",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "Cloud Object Storage is unavailable.",
            checked_at,
        )
    return _dependency(
        "cos",
        StatusValue.READY,
        EvidenceKind.LIVE_CHECK,
        "Cloud Object Storage is reachable.",
        checked_at,
    )


def check_watsonx(
    environment: Mapping[str, str], http: Any, checked_at: datetime
) -> DependencyStatus:
    """Acquire an ephemeral IAM token and read watsonx project metadata."""
    api_key = _value(environment, "WATSONX_APIKEY")
    project_id = _value(environment, "WATSONX_PROJECT_ID")
    base_url = _value(environment, "WATSONX_URL")
    if not all((api_key, project_id, base_url)):
        return _dependency(
            "watsonx_ai",
            StatusValue.NOT_CONFIGURED,
            EvidenceKind.NOT_VERIFIED,
            "watsonx.ai is not configured.",
            checked_at,
        )
    try:
        token = _access_token(http, api_key)
        response = http.get(
            f"{base_url.rstrip('/')}/v2/projects/{project_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            raise _HTTPStatusFailure()
    except Exception as error:
        _warning(_LABELS["watsonx_ai"], error)
        return _dependency(
            "watsonx_ai",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "watsonx.ai is unavailable.",
            checked_at,
        )
    return _dependency(
        "watsonx_ai",
        StatusValue.READY,
        EvidenceKind.LIVE_CHECK,
        "watsonx.ai is reachable.",
        checked_at,
    )


def _wxo_root(environment: Mapping[str, str]) -> str:
    service_instance_url = _value(environment, "WXO_SERVICE_INSTANCE_URL")
    if service_instance_url:
        return service_instance_url.rstrip("/")
    instance_id = _value(environment, "WXO_INSTANCE_ID")
    instance_cloud = _value(environment, "WXO_INSTANCE_CLOUD") or "ibmcloud"
    if instance_cloud == "ibmcloud":
        region = _value(environment, "WXO_INSTANCE_CLOUD_REGION") or "us-south"
        return (
            f"https://api.{region}.watson-orchestrate.cloud.ibm.com"
            f"/instances/{instance_id}"
        )
    return f"https://api.dl.watson-orchestrate.ibm.com/instances/{instance_id}"


def _wxo_unavailable(checked_at: datetime) -> list[DependencyStatus]:
    return [
        _dependency(
            "wxo",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "watsonx Orchestrate is unavailable.",
            checked_at,
        ),
        *[
            _dependency(
                dependency_id,
                StatusValue.UNAVAILABLE,
                EvidenceKind.LIVE_CHECK,
                "Agent status is unavailable.",
                checked_at,
            )
            for dependency_id, _ in _WXO_AGENTS
        ],
    ]


def check_wxo(
    environment: Mapping[str, str], http: Any, checked_at: datetime
) -> list[DependencyStatus]:
    """Read the registered-agent collection without creating threads or runs."""
    api_key = _value(environment, "WXO_API_KEY")
    service_url = _value(environment, "WXO_SERVICE_INSTANCE_URL")
    instance_id = _value(environment, "WXO_INSTANCE_ID")
    agent_ids = [_value(environment, name) for _, name in _WXO_AGENTS]
    if not api_key or not (service_url or instance_id) or not all(agent_ids):
        return [
            _dependency(
                "wxo",
                StatusValue.NOT_CONFIGURED,
                EvidenceKind.NOT_VERIFIED,
                "watsonx Orchestrate is not configured.",
                checked_at,
            ),
            *[
                _dependency(
                    dependency_id,
                    StatusValue.NOT_CONFIGURED,
                    EvidenceKind.NOT_VERIFIED,
                    "Agent is not configured.",
                    checked_at,
                )
                for dependency_id, _ in _WXO_AGENTS
            ],
        ]

    root = _wxo_root(environment)
    try:
        token = _access_token(http, api_key)
        response = http.get(
            f"{root}/v2/orchestrate/agents",
            headers={"Authorization": f"Bearer {token}"},
            params=[("ids", agent_id) for agent_id in agent_ids],
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            raise _HTTPStatusFailure()
        payload = response.json()
        registered_agents = payload.get("agents", [])
        registered_ids = {
            item.get("id") for item in registered_agents if isinstance(item, Mapping)
        }
    except Exception as error:
        _warning(_LABELS["wxo"], error)
        return _wxo_unavailable(checked_at)

    results = [
        _dependency(
            "wxo",
            StatusValue.READY,
            EvidenceKind.LIVE_CHECK,
            "watsonx Orchestrate is reachable.",
            checked_at,
        )
    ]
    for (dependency_id, _), agent_id in zip(_WXO_AGENTS, agent_ids, strict=True):
        registered = agent_id in registered_ids
        results.append(
            _dependency(
                dependency_id,
                StatusValue.READY if registered else StatusValue.UNAVAILABLE,
                EvidenceKind.LIVE_CHECK,
                "Agent is registered." if registered else "Agent is not registered.",
                checked_at,
            )
        )
    return results


def check_openllmetry(
    environment: Mapping[str, str], initialized: bool, checked_at: datetime
) -> DependencyStatus:
    """Report optional OpenLLMetry configuration and initialization state."""
    enabled = _value(environment, "OPENLLMETRY_ENABLED").lower() in TRUE_VALUES
    if not enabled:
        return _dependency(
            "openllmetry",
            StatusValue.NOT_CONFIGURED,
            EvidenceKind.NOT_VERIFIED,
            "OpenLLMetry is not configured.",
            checked_at,
        )
    if initialized:
        return _dependency(
            "openllmetry",
            StatusValue.READY,
            EvidenceKind.CONFIGURED,
            "OpenLLMetry is initialized.",
            checked_at,
        )
    return _dependency(
        "openllmetry",
        StatusValue.LIMITED,
        EvidenceKind.CONFIGURED,
        "OpenLLMetry is enabled but not initialized.",
        checked_at,
    )
