from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


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
    model_config = ConfigDict(extra="forbid")


class DependencyStatus(PublicStatusModel):
    id: str
    label: str
    status: StatusValue
    evidence: EvidenceKind
    message: str
    checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None


class CapabilityStatus(PublicStatusModel):
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
    capabilities: list[CapabilityStatus]
    dependencies: list[DependencyStatus]
