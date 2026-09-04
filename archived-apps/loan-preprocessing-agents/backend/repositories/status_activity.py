from dataclasses import dataclass, replace
from datetime import datetime
from collections.abc import Mapping

from database import SessionLocal
from models import AgentEvent
from utils.agents import RETRYABLE_AGENT_MESSAGES


@dataclass(frozen=True)
class AgentActivity:
    agent_key: str
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None


_INVOCATION_MARKERS = {
    "Invoking Document Processor Agent": "document_processing_agent",
    "Invoking Document Validator Agent": "document_validation_agent",
    "Invoking Final Decision Agent": "final_decision_agent",
}


def _message(payload: object) -> str:
    if isinstance(payload, Mapping):
        value = payload.get("message")
        return value if isinstance(value, str) else ""
    return payload if isinstance(payload, str) else ""


def _is_failure(message: str) -> bool:
    normalized = message.casefold()
    return any(phrase in normalized for phrase in RETRYABLE_AGENT_MESSAGES)


def get_recent_agent_activity(
    session_factory=SessionLocal, limit: int = 500
) -> dict[str, AgentActivity]:
    """Summarize the most recent recognized agent responses without exposing payloads."""
    bounded_limit = max(0, min(limit, 500))
    session = session_factory()
    try:
        events = (
            session.query(AgentEvent)
            .order_by(AgentEvent.occurred_at.desc(), AgentEvent.id.desc())
            .limit(bounded_limit)
            .all()
        )
    finally:
        session.close()

    current_agents: dict[str, str] = {}
    activity: dict[str, AgentActivity] = {}
    for event in reversed(events):
        message = _message(event.payload)
        if event.stage == "invoke_agent":
            agent_key = _INVOCATION_MARKERS.get(message)
            if agent_key is not None:
                current_agents[event.external_application_id] = agent_key
                activity.setdefault(agent_key, AgentActivity(agent_key=agent_key))
        elif event.stage == "agent_response" and message:
            agent_key = current_agents.get(event.external_application_id)
            if agent_key is None:
                continue
            current = activity.setdefault(agent_key, AgentActivity(agent_key=agent_key))
            if _is_failure(message):
                activity[agent_key] = replace(current, last_failure_at=event.occurred_at)
            else:
                activity[agent_key] = replace(current, last_success_at=event.occurred_at)

    return activity
