from datetime import datetime, timezone

from database import SessionLocal
from models import AgentEvent, Application


def _payload_for(data: object) -> object:
    if isinstance(data, str):
        return {"message": data}
    return data


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def append_event(
    application_id: str,
    stage: str,
    data: object,
    occurred_at: datetime | None = None,
) -> None:
    """Persist one agent event in its own transaction."""
    session = SessionLocal()
    try:
        application = (
            session.query(Application)
            .filter(Application.app_id_str == application_id)
            .one_or_none()
        )
        session.add(
            AgentEvent(
                application_id=application.id if application else None,
                external_application_id=application_id,
                stage=stage,
                occurred_at=occurred_at or datetime.now(timezone.utc),
                payload=_payload_for(data),
            )
        )
        session.commit()
    finally:
        session.close()


def list_events(application_id: str) -> list[dict]:
    """Return an application's agent events in the existing API shape."""
    session = SessionLocal()
    try:
        events = (
            session.query(AgentEvent)
            .filter(AgentEvent.external_application_id == application_id)
            .order_by(AgentEvent.occurred_at, AgentEvent.id)
            .all()
        )
        return [
            {
                "application_id": event.external_application_id,
                "stage": event.stage,
                "timestamp": _utc_timestamp(event.occurred_at),
                "data": event.payload,
            }
            for event in events
        ]
    finally:
        session.close()
