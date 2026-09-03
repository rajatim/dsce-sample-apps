import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class LegacyEvent:
    source_id: str
    external_application_id: str
    stage: str
    occurred_at: datetime
    payload: object


@dataclass(frozen=True)
class MigrationAnomaly:
    kind: str
    external_application_id: str
    source_id: str
    details: str


@dataclass(frozen=True)
class LegacySnapshot:
    users: list[dict]
    applications: list[dict]
    events: list[LegacyEvent]
    anomalies: list[MigrationAnomaly]


def load_legacy_snapshot(sqlite_path: Path, logs_path: Path) -> LegacySnapshot:
    users, applications = _read_sqlite_rows(sqlite_path)
    events = _read_tinydb_events(logs_path)
    application_ids = {row["app_id_str"] for row in applications}
    anomalies = []
    reported_application_ids = set()
    for event in events:
        if (
            event.external_application_id not in application_ids
            and event.external_application_id not in reported_application_ids
        ):
            anomalies.append(
                MigrationAnomaly(
                    kind="orphan_agent_event",
                    external_application_id=event.external_application_id,
                    source_id=event.source_id,
                    details="No matching legacy application row",
                )
            )
            reported_application_ids.add(event.external_application_id)
    return LegacySnapshot(users, applications, events, anomalies)


def _read_sqlite_rows(sqlite_path: Path) -> tuple[list[dict], list[dict]]:
    sqlite_uri = f"{sqlite_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(sqlite_uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        users = [dict(row) for row in connection.execute("SELECT * FROM users")]
        applications = [
            dict(row) for row in connection.execute("SELECT * FROM applications")
        ]
    finally:
        connection.close()
    return users, applications


def _read_tinydb_events(logs_path: Path) -> list[LegacyEvent]:
    with logs_path.open(encoding="utf-8") as logs_file:
        documents = json.load(logs_file)["_default"]

    return [
        LegacyEvent(
            source_id=str(document_id),
            external_application_id=document["application_id"],
            stage=document["stage"],
            occurred_at=_parse_timestamp(document["timestamp"]),
            payload=_parse_payload(document["data"]),
        )
        for document_id, document in sorted(
            documents.items(), key=lambda item: int(item[0])
        )
    ]


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _parse_payload(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"message": value}
