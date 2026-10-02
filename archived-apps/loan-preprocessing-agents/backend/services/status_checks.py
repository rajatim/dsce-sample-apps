"""Low-cost, read-only checks for the Loan demo's external dependencies."""

import json
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from status_models import DependencyStatus, EvidenceKind, StatusValue
from services.status_errors import problem_for, problem_from_http, problem_from_exception


LOGGER = logging.getLogger(__name__)
HTTP_TIMEOUT = (2, 3)
IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
IAM_TOKEN_GRANT = "urn:ibm:params:oauth:grant-type:apikey"
AWS_IAM_TOKEN_URL = (
    "https://iam.platform.saas.ibm.com/siusermgr/api/1.0/apikeys/token"
)

_LABELS = {
    "postgresql": "PostgreSQL",
    "cos": "Cloud Object Storage",
    "watsonx_ai": "watsonx.ai",
    "wxo": "watsonx Orchestrate",
    "document_processing_agent": "Document processing agent",
    "document_validation_agent": "Document validation agent",
    "final_decision_agent": "Final decision agent",
}
_WXO_AGENTS = (
    ("document_processing_agent", "DOC_PROCESSOR_AGENT_ID"),
    ("document_validation_agent", "DOCUMENT_VALIDATION_AGENT_ID"),
    ("final_decision_agent", "FINAL_DECISION_AGENT_ID"),
)


class _HTTPStatusFailure(RuntimeError):
    """Carry only the reviewed public fields, never the raw response."""

    def __init__(self, problem):
        super().__init__(problem.code)
        self.problem = problem


def _json_response(response, service, stage):
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None
    if response.status_code != 200:
        raise _HTTPStatusFailure(problem_from_http(
            service=service, stage=stage, status_code=response.status_code,
            payload=payload, headers=getattr(response, "headers", {}),
        ))
    if not isinstance(payload, (Mapping, list)):
        raise _HTTPStatusFailure(problem_for(
            service=service, stage="response_parsing", code="invalid_response", http_status=200,
        ))
    return payload


def _token(response, service, field):
    payload = _json_response(response, service, "authentication")
    value = payload.get(field) if isinstance(payload, Mapping) else None
    if not isinstance(value, str) or not value:
        raise _HTTPStatusFailure(problem_for(
            service=service, stage="response_parsing", code="invalid_response", http_status=200,
        ))
    return value


def build_status_http_client() -> requests.Session:
    """Create a status-only HTTP client with explicitly disabled retries."""
    client = requests.Session()
    adapter = HTTPAdapter(max_retries=0)
    client.mount("https://", adapter)
    client.mount("http://", adapter)
    return client


def build_status_session_factory(database_url: str):
    """Build a status-only database path without changing the business pool."""
    if database_url.startswith("sqlite:"):
        connect_args = {"check_same_thread": False}
    else:
        connect_args = {
            "connect_timeout": 1,
            "options": "-c statement_timeout=2000",
        }
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        connect_args=connect_args,
    )
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _dependency(
    dependency_id: str,
    status: StatusValue,
    evidence: EvidenceKind,
    message: str,
    checked_at: datetime,
    problem=None,
) -> DependencyStatus:
    if status is StatusValue.NOT_CONFIGURED and problem is None:
        problem = problem_for(service=dependency_id, stage="configuration", code="missing_configuration")
    return DependencyStatus(
        problem=problem,
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


def _access_token(http: Any, api_key: str, service="watsonx_ai") -> str:
    response = http.post(
        IAM_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": IAM_TOKEN_GRANT, "apikey": api_key},
        timeout=HTTP_TIMEOUT,
    )
    return _token(response, service, "access_token")


def _wxo_access_token(
    http: Any,
    api_key: str,
    instance_cloud: str,
    service_url: str = "",
    username: str = "",
) -> str:
    if instance_cloud == "cpd":
        parsed_url = urlsplit(service_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc or not username:
            raise _HTTPStatusFailure(problem_for(service="wxo", stage="configuration", code="missing_configuration"))
        response = http.post(
            f"{parsed_url.scheme}://{parsed_url.netloc}/icp4d-api/v1/authorize",
            headers={"Content-Type": "application/json"},
            json={"username": username, "api_key": api_key},
            timeout=HTTP_TIMEOUT,
        )
        return _token(response, "wxo", "token")
    if instance_cloud == "aws":
        response = http.post(
            AWS_IAM_TOKEN_URL,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=json.dumps({"apikey": api_key}),
            timeout=HTTP_TIMEOUT,
        )
        return _token(response, "wxo", "token")
    if instance_cloud == "ibmcloud":
        return _access_token(http, api_key, "wxo")
    raise _HTTPStatusFailure(problem_for(service="wxo", stage="configuration", code="missing_configuration"))


def check_postgresql(
    session_factory: Callable[[], Any], checked_at: datetime
) -> DependencyStatus:
    """Execute a single read-only PostgreSQL liveness statement."""
    try:
        with session_factory() as session:
            if session.get_bind().dialect.name != "postgresql":
                return _dependency(
                    "postgresql",
                    StatusValue.NOT_CONFIGURED,
                    EvidenceKind.NOT_VERIFIED,
                    "PostgreSQL is not configured.",
                    checked_at,
                )
            session.execute(text("SELECT 1"))
    except Exception as error:
        _warning(_LABELS["postgresql"], error)
        return _dependency(
            "postgresql",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "PostgreSQL is unavailable.",
            checked_at, problem_from_exception(service="postgresql", stage="database_query", error=error),
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
            checked_at, problem_from_exception(service="cos", stage="metadata", error=error),
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
            checked_at, problem_from_exception(service="cos", stage="metadata", error=error),
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
    """Acquire an ephemeral IAM token and list one project deployment."""
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
    stage = "authentication"
    try:
        token = _access_token(http, api_key)
        stage = "metadata"
        response = http.get(
            f"{base_url.rstrip('/')}/ml/v4/deployments",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "version": "2024-05-31",
                "project_id": project_id,
                "limit": 1,
            },
            timeout=HTTP_TIMEOUT,
        )
        payload = _json_response(response, "watsonx_ai", stage)
        resources = payload.get("resources") if isinstance(payload, Mapping) else None
        if not isinstance(resources, list) or not all(isinstance(item, Mapping) for item in resources):
            raise _HTTPStatusFailure(problem_for(
                service="watsonx_ai", stage="response_parsing", code="invalid_response", http_status=200,
            ))
    except Exception as error:
        _warning(_LABELS["watsonx_ai"], error)
        return _dependency(
            "watsonx_ai",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "watsonx.ai is unavailable.",
            checked_at, problem_from_exception(service="watsonx_ai", stage=stage, error=error),
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
    instance_cloud = (
        _value(environment, "WXO_INSTANCE_CLOUD") or "ibmcloud"
    ).lower()
    if instance_cloud == "ibmcloud":
        region = _value(environment, "WXO_INSTANCE_CLOUD_REGION") or "us-south"
        return (
            f"https://api.{region}.watson-orchestrate.cloud.ibm.com"
            f"/instances/{instance_id}"
        )
    if instance_cloud == "aws":
        return f"https://api.dl.watson-orchestrate.ibm.com/instances/{instance_id}"
    raise _HTTPStatusFailure(problem_for(service="wxo", stage="configuration", code="missing_configuration"))


def _registered_agent_ids(payload: Any) -> set[str]:
    if isinstance(payload, list):
        collection = payload
    elif isinstance(payload, Mapping) and isinstance(payload.get("agents"), list):
        collection = payload["agents"]
    else:
        raise _HTTPStatusFailure(problem_for(service="wxo", stage="response_parsing", code="invalid_response", http_status=200))
    if not all(isinstance(item, Mapping) and isinstance(item.get("id"), str) and item["id"].strip() for item in collection):
        raise _HTTPStatusFailure(problem_for(service="wxo", stage="response_parsing", code="invalid_response", http_status=200))
    return {
        agent_id
        for item in collection
        if isinstance((agent_id := item.get("id")), str) and agent_id
    }


def _wxo_agent_status(
    dependency_id: str,
    agent_id: str,
    registered_ids: set[str],
    checked_at: datetime,
) -> DependencyStatus:
    if not agent_id:
        return _dependency(
            dependency_id,
            StatusValue.NOT_CONFIGURED,
            EvidenceKind.NOT_VERIFIED,
            "Agent is not configured.",
            checked_at,
        )
    registered = agent_id in registered_ids
    return _dependency(
        dependency_id,
        StatusValue.READY if registered else StatusValue.UNAVAILABLE,
        EvidenceKind.LIVE_CHECK,
        "Agent is registered." if registered else "Agent is not registered.",
        checked_at,
        None if registered else problem_for(service=dependency_id, stage="registration", code="agent_not_registered"),
    )


def _wxo_unavailable(
    checked_at: datetime, agent_ids: list[str], problem
) -> list[DependencyStatus]:
    return [
        _dependency(
            "wxo",
            StatusValue.UNAVAILABLE,
            EvidenceKind.LIVE_CHECK,
            "watsonx Orchestrate is unavailable.",
            checked_at, problem,
        ),
        *[
            _dependency(
                dependency_id,
                StatusValue.UNAVAILABLE,
                EvidenceKind.NOT_VERIFIED,
                "Agent status is unavailable.",
                checked_at, problem.model_copy(update={"blocked_by": "wxo"}),
            )
            if agent_id
            else _wxo_agent_status(dependency_id, agent_id, set(), checked_at)
            for (dependency_id, _), agent_id in zip(
                _WXO_AGENTS, agent_ids, strict=True
            )
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
    if not api_key or not (service_url or instance_id):
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

    stage = "configuration"
    try:
        root = _wxo_root(environment)
        instance_cloud = (
            _value(environment, "WXO_INSTANCE_CLOUD") or "ibmcloud"
        ).lower()
        stage = "authentication"
        token = _wxo_access_token(
            http,
            api_key,
            instance_cloud,
            service_url,
            _value(environment, "WXO_CPD_USERNAME"),
        )
        stage = "metadata"
        api_version = "v1" if instance_cloud == "cpd" else "v2"
        response = http.get(
            f"{root}/{api_version}/orchestrate/agents",
            headers={"Authorization": f"Bearer {token}"},
            params=[("ids", agent_id) for agent_id in agent_ids if agent_id],
            timeout=HTTP_TIMEOUT,
        )
        registered_ids = _registered_agent_ids(_json_response(response, "wxo", stage))
    except Exception as error:
        _warning(_LABELS["wxo"], error)
        return _wxo_unavailable(checked_at, agent_ids, problem_from_exception(service="wxo", stage=stage, error=error))

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
        results.append(
            _wxo_agent_status(
                dependency_id, agent_id, registered_ids, checked_at
            )
        )
    return results
