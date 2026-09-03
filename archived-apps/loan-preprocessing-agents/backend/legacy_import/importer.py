from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from legacy_import.reader import LegacySnapshot
from models import AgentEvent, Application, MigrationAnomaly, User


@dataclass(frozen=True)
class MigrationReport:
    users_seen: int
    applications_seen: int
    events_seen: int
    anomalies_seen: int
    users_inserted: int
    applications_inserted: int
    events_inserted: int
    anomalies_inserted: int

    @property
    def total_inserted(self) -> int:
        return (
            self.users_inserted
            + self.applications_inserted
            + self.events_inserted
            + self.anomalies_inserted
        )


@dataclass(frozen=True)
class _PreparedApplication:
    values: dict
    owner_username: str


@dataclass(frozen=True)
class _PreparedEvent:
    source_id: str
    external_application_id: str
    stage: str
    occurred_at: datetime
    payload: object = field(compare=False)
    payload_semantics: tuple


def import_snapshot(snapshot: LegacySnapshot, session_factory, apply: bool) -> MigrationReport:
    users, applications, events = _prepare_rows(snapshot)
    seen = {
        "users_seen": len(snapshot.users),
        "applications_seen": len(snapshot.applications),
        "events_seen": len(snapshot.events),
        "anomalies_seen": len(snapshot.anomalies),
    }
    if not apply:
        return MigrationReport(
            **seen,
            users_inserted=0,
            applications_inserted=0,
            events_inserted=0,
            anomalies_inserted=0,
        )

    session = session_factory()
    try:
        users_inserted, users_by_username = _insert_users(session, users)
        applications_inserted, applications_by_external_id = _insert_applications(
            session,
            applications,
            users_by_username,
        )
        events_inserted = _insert_events(
            session,
            events,
            applications_by_external_id,
        )
        anomalies_inserted = _insert_anomalies(session, snapshot)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return MigrationReport(
        **seen,
        users_inserted=users_inserted,
        applications_inserted=applications_inserted,
        events_inserted=events_inserted,
        anomalies_inserted=anomalies_inserted,
    )


def _prepare_rows(
    snapshot: LegacySnapshot,
) -> tuple[
    dict[str, dict],
    dict[str, _PreparedApplication],
    dict[str, _PreparedEvent],
]:
    users = {}
    usernames_by_legacy_id = {}
    for row in snapshot.users:
        username = row["username"]
        legacy_id = row["id"]
        prepared_user = {
            "username": username,
            "hashed_password": row["hashed_password"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "date_of_birth": _iso_date(row["date_of_birth"]),
        }
        previous_username = usernames_by_legacy_id.get(legacy_id)
        if previous_username is not None and previous_username != username:
            raise ValueError("legacy user id maps to multiple usernames")
        usernames_by_legacy_id[legacy_id] = username
        existing_user = users.get(username)
        if existing_user is not None and existing_user != prepared_user:
            raise ValueError("conflicting legacy user for username")
        users.setdefault(username, prepared_user)

    applications = {}
    for row in snapshot.applications:
        owner_username = usernames_by_legacy_id.get(row["owner_id"])
        if owner_username is None:
            raise ValueError("legacy application owner has no matching user")
        app_id_str = row["app_id_str"]
        prepared_application = _PreparedApplication(
            values={
                "app_id_str": app_id_str,
                "applicant_name": row["applicant_name"],
                "loan_type": row["loan_type"],
                "amount": _decimal(row["amount"]),
                "status": row["status"],
                "submitted_date": _iso_date(row["submitted_date"]),
                "validation_comments": row["validation_comments"],
            },
            owner_username=owner_username,
        )
        existing_application = applications.get(app_id_str)
        if (
            existing_application is not None
            and existing_application != prepared_application
        ):
            raise ValueError("conflicting legacy application for app_id_str")
        applications.setdefault(app_id_str, prepared_application)

    events = {}
    for event in snapshot.events:
        prepared_event = _PreparedEvent(
            source_id=event.source_id,
            external_application_id=event.external_application_id,
            stage=event.stage,
            occurred_at=_utc_datetime(event.occurred_at),
            payload=event.payload,
            payload_semantics=_json_semantics(event.payload),
        )
        existing_event = events.get(event.source_id)
        if existing_event is not None and existing_event != prepared_event:
            raise ValueError("conflicting legacy event for legacy_source_id")
        events.setdefault(event.source_id, prepared_event)
    return users, applications, events


def _iso_date(value) -> date:
    if isinstance(value, datetime):
        raise ValueError("legacy date must not include a time")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("invalid legacy ISO date") from None


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid legacy amount") from None


def _utc_datetime(value) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("invalid legacy event timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_semantics(value) -> tuple:
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("invalid legacy event payload")
        return ("number", number)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, (list, tuple)):
        return ("array", tuple(_json_semantics(item) for item in value))
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("invalid legacy event payload")
        return (
            "object",
            tuple(
                sorted(
                    (key, _json_semantics(item))
                    for key, item in value.items()
                )
            ),
        )
    raise ValueError("invalid legacy event payload")


def _insert_users(
    session,
    prepared_users: dict[str, dict],
) -> tuple[int, dict[str, User]]:
    usernames = set(prepared_users)
    existing = (
        session.query(User).filter(User.username.in_(usernames)).all()
        if usernames
        else []
    )
    users_by_username = {user.username: user for user in existing}
    inserted = 0
    for username, values in prepared_users.items():
        if username in users_by_username:
            continue
        user = User(**values)
        session.add(user)
        users_by_username[username] = user
        inserted += 1
    session.flush()
    return inserted, users_by_username


def _insert_applications(
    session,
    prepared_applications: dict[str, _PreparedApplication],
    users_by_username: dict[str, User],
) -> tuple[int, dict[str, Application]]:
    external_ids = set(prepared_applications)
    existing = (
        session.query(Application)
        .filter(Application.app_id_str.in_(external_ids))
        .all()
        if external_ids
        else []
    )
    applications_by_external_id = {
        application.app_id_str: application for application in existing
    }
    inserted = 0
    for item in prepared_applications.values():
        external_id = item.values["app_id_str"]
        owner_id = users_by_username[item.owner_username].id
        if external_id in applications_by_external_id:
            if not _application_matches(
                applications_by_external_id[external_id],
                item,
                owner_id,
            ):
                raise ValueError(
                    "target application conflicts with legacy app_id_str"
                )
            continue
        application = Application(
            **item.values,
            owner_id=owner_id,
        )
        session.add(application)
        applications_by_external_id[external_id] = application
        inserted += 1
    session.flush()
    return inserted, applications_by_external_id


def _application_matches(
    existing: Application,
    prepared: _PreparedApplication,
    owner_id: int,
) -> bool:
    values = prepared.values
    return (
        existing.owner_id == owner_id
        and existing.applicant_name == values["applicant_name"]
        and existing.loan_type == values["loan_type"]
        and existing.amount == values["amount"]
        and existing.status == values["status"]
        and existing.submitted_date == values["submitted_date"]
        and existing.validation_comments == values["validation_comments"]
    )


def _insert_events(
    session,
    prepared_events: dict[str, _PreparedEvent],
    applications_by_external_id: dict[str, Application],
) -> int:
    source_ids = set(prepared_events)
    existing_events = (
        session.query(AgentEvent)
        .filter(AgentEvent.legacy_source_id.in_(source_ids))
        .all()
        if source_ids
        else []
    )
    events_by_source_id = {
        event.legacy_source_id: event for event in existing_events
    }
    inserted = 0
    for event in prepared_events.values():
        application = applications_by_external_id.get(event.external_application_id)
        application_id = application.id if application is not None else None
        existing_event = events_by_source_id.get(event.source_id)
        if existing_event is not None:
            if not _event_matches(existing_event, event, application_id):
                raise ValueError("target event conflicts with legacy_source_id")
            continue
        new_event = AgentEvent(
            application_id=application_id,
            external_application_id=event.external_application_id,
            stage=event.stage,
            occurred_at=event.occurred_at,
            payload=event.payload,
            legacy_source_id=event.source_id,
        )
        session.add(new_event)
        events_by_source_id[event.source_id] = new_event
        inserted += 1
    return inserted


def _event_matches(
    existing: AgentEvent,
    prepared: _PreparedEvent,
    application_id: int | None,
) -> bool:
    return (
        existing.application_id == application_id
        and existing.external_application_id == prepared.external_application_id
        and existing.stage == prepared.stage
        and _utc_datetime(existing.occurred_at) == prepared.occurred_at
        and _json_semantics(existing.payload) == prepared.payload_semantics
    )


def _insert_anomalies(session, snapshot: LegacySnapshot) -> int:
    existing_keys = {
        (kind, source_id)
        for kind, source_id in session.query(
            MigrationAnomaly.kind,
            MigrationAnomaly.source_id,
        ).all()
    }
    inserted = 0
    for anomaly in snapshot.anomalies:
        key = (anomaly.kind, anomaly.source_id)
        if key in existing_keys:
            continue
        session.add(
            MigrationAnomaly(
                kind=anomaly.kind,
                external_application_id=anomaly.external_application_id,
                source_id=anomaly.source_id,
                details=anomaly.details,
            )
        )
        existing_keys.add(key)
        inserted += 1
    return inserted
