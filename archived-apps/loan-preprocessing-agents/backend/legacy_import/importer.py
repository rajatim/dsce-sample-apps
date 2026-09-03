from dataclasses import dataclass
from datetime import date, datetime
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


def import_snapshot(snapshot: LegacySnapshot, session_factory, apply: bool) -> MigrationReport:
    users, applications = _prepare_rows(snapshot)
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
            snapshot,
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
) -> tuple[dict[str, dict], list[_PreparedApplication]]:
    users = {}
    usernames_by_legacy_id = {}
    for row in snapshot.users:
        username = row["username"]
        legacy_id = row["id"]
        previous_username = usernames_by_legacy_id.get(legacy_id)
        if previous_username is not None and previous_username != username:
            raise ValueError("legacy user id maps to multiple usernames")
        usernames_by_legacy_id[legacy_id] = username
        users.setdefault(
            username,
            {
                "username": username,
                "hashed_password": row["hashed_password"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "date_of_birth": _iso_date(row["date_of_birth"]),
            },
        )

    applications = []
    application_ids = set()
    for row in snapshot.applications:
        owner_username = usernames_by_legacy_id.get(row["owner_id"])
        if owner_username is None:
            raise ValueError("legacy application owner has no matching user")
        app_id_str = row["app_id_str"]
        if app_id_str in application_ids:
            continue
        application_ids.add(app_id_str)
        applications.append(
            _PreparedApplication(
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
        )
    return users, applications


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
    prepared_applications: list[_PreparedApplication],
    users_by_username: dict[str, User],
) -> tuple[int, dict[str, Application]]:
    external_ids = {item.values["app_id_str"] for item in prepared_applications}
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
    for item in prepared_applications:
        external_id = item.values["app_id_str"]
        if external_id in applications_by_external_id:
            continue
        application = Application(
            **item.values,
            owner_id=users_by_username[item.owner_username].id,
        )
        session.add(application)
        applications_by_external_id[external_id] = application
        inserted += 1
    session.flush()
    return inserted, applications_by_external_id


def _insert_events(
    session,
    snapshot: LegacySnapshot,
    applications_by_external_id: dict[str, Application],
) -> int:
    source_ids = {event.source_id for event in snapshot.events}
    existing_source_ids = (
        {
            source_id
            for (source_id,) in session.query(AgentEvent.legacy_source_id)
            .filter(AgentEvent.legacy_source_id.in_(source_ids))
            .all()
        }
        if source_ids
        else set()
    )
    inserted = 0
    for event in snapshot.events:
        if event.source_id in existing_source_ids:
            continue
        application = applications_by_external_id.get(event.external_application_id)
        session.add(
            AgentEvent(
                application_id=application.id if application is not None else None,
                external_application_id=event.external_application_id,
                stage=event.stage,
                occurred_at=event.occurred_at,
                payload=event.payload,
                legacy_source_id=event.source_id,
            )
        )
        existing_source_ids.add(event.source_id)
        inserted += 1
    return inserted


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
