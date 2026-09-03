from datetime import datetime, timezone
import os
import re

from sqlalchemy import func

from database import SessionLocal
from models import Application, ApplicationDocument, ProcessingRun


def _safe_error_text(error_text: str | None) -> str | None:
    if error_text is None:
        return None

    safe_text = error_text
    wxo_api_key = os.getenv("WXO_API_KEY")
    if wxo_api_key:
        safe_text = safe_text.replace(wxo_api_key, "[REDACTED]")
    safe_text = re.sub(
        r"(?i)authorization['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?[^'\"\s,;}]+",
        "Authorization: [REDACTED]",
        safe_text,
    )
    safe_text = re.sub(
        r"(?i)bearer\s+[^'\"\s,;}]+",
        "Bearer [REDACTED]",
        safe_text,
    )
    safe_text = re.sub(
        r"(?i)(wxo_api_key\s*[:=]\s*)[^'\"\s,;}]+",
        r"\1[REDACTED]",
        safe_text,
    )
    return safe_text


def record_document(
    application_id: int,
    document_role: str,
    original_filename: str,
    cos_object_key: str,
    content_type: str | None,
    size_bytes: int,
    sha256: str,
) -> ApplicationDocument:
    """Persist document metadata without storing the document contents."""
    session = SessionLocal()
    try:
        record = ApplicationDocument(
            application_id=application_id,
            document_role=document_role,
            original_filename=original_filename,
            cos_object_key=cos_object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        session.expunge(record)
        return record
    finally:
        session.close()


def start_processing_run(application_id: int) -> int:
    """Create the next processing attempt for an application."""
    session = SessionLocal()
    try:
        session.query(Application).filter(
            Application.id == application_id
        ).with_for_update().one()
        latest_attempt = (
            session.query(func.max(ProcessingRun.attempt_number))
            .filter(ProcessingRun.application_id == application_id)
            .scalar()
        )
        run = ProcessingRun(
            application_id=application_id,
            attempt_number=(latest_attempt or 0) + 1,
            status="processing",
        )
        session.add(run)
        session.commit()
        return run.id
    finally:
        session.close()


def finish_processing_run(
    run_id: int,
    status: str,
    error_text: str | None = None,
) -> None:
    """Record a processing run's terminal result."""
    session = SessionLocal()
    try:
        run = session.query(ProcessingRun).filter(ProcessingRun.id == run_id).one()
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.error_text = _safe_error_text(error_text)
        session.commit()
    finally:
        session.close()
