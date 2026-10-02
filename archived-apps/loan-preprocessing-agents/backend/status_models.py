from datetime import datetime
from enum import StrEnum
from typing import Literal


from pydantic import BaseModel, ConfigDict, Field


class StatusValue(StrEnum):
    READY = "ready"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    CHECKING = "checking"
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"


class EvidenceKind(StrEnum):
    LIVE_CHECK = "live_check"
    CONFIGURED = "configured"
    RECENT_EXECUTION = "recent_execution"
    NOT_VERIFIED = "not_verified"


class PublicStatusModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


DependencyId = Literal[
    "loan_api", "postgresql", "cos", "watsonx_ai", "wxo",
    "document_processing_agent", "document_validation_agent", "final_decision_agent",
]


class StatusProblem(PublicStatusModel):
    category: Literal["provider", "response", "configuration", "registration", "timeout", "connection", "unknown", "quota", "authorization"]
    service: DependencyId
    stage: Literal["authentication", "metadata", "registration", "response_parsing", "configuration", "database_query", "orchestration"]
    code: Literal["http_error", "invalid_response", "missing_configuration", "agent_not_registered", "timeout", "connection_error", "tls_error", "check_failed"]
    provider_code: str | None = Field(default=None, max_length=128)
    http_status: int | None = Field(default=None, ge=100, le=599)
    provider_message: str | None = Field(default=None, max_length=512)
    trace_id: str | None = Field(default=None, max_length=128)
    blocked_by: DependencyId | None = None
    retryable_now: bool
    action: Literal["retry_later", "review_configuration"]


class RefreshResult(PublicStatusModel):
    requested_dependency: DependencyId | None = None
    affected_ids: tuple[DependencyId, ...] = ()
    result: Literal["executed", "shared", "cooldown"]
    retry_after_seconds: int = Field(default=0, ge=0)


class DependencyStatus(PublicStatusModel):
    id: str
    label: str
    status: StatusValue
    evidence: EvidenceKind
    message: str
    checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    problem: StatusProblem | None = None
    stale: bool = False
    age_seconds: float = Field(default=0, ge=0)
    check_kind: Literal["api_response", "database_query", "bucket_metadata", "deployment_metadata", "agent_registration"] | None = None


class CapabilityStatus(PublicStatusModel):
    stale: bool = False
    age_seconds: float = Field(default=0, ge=0)
    id: str
    label: str
    status: StatusValue
    message: str


class OverallStatus(PublicStatusModel):
    status: StatusValue
    title: str
    message: str


class SystemStatusResponse(PublicStatusModel):
    overall: OverallStatus
    checked_at: datetime
    stale_after_seconds: int
    stale: bool = False
    capabilities: tuple[CapabilityStatus, ...]
    dependencies: tuple[DependencyStatus, ...]
    instance_id: str = ""
    revision: int = 0
    refresh: RefreshResult | None = None
