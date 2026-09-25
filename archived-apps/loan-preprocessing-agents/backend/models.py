from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    CHAR,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, validates

from database import Base


def _json_type():
    return JSON().with_variant(JSONB(), "postgresql")


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_iso_date(value):
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    date_of_birth = Column(Date, nullable=False)

    applications = relationship("Application", back_populates="owner")

    @validates("date_of_birth")
    def normalize_date_of_birth(self, key, value):
        return _parse_iso_date(value)


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    app_id_str = Column(String(64), unique=True, index=True, nullable=False)
    applicant_name = Column(String(255), nullable=False)
    loan_type = Column(String(100), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(64), nullable=False)
    submitted_date = Column(Date, nullable=False)
    validation_comments = Column(Text, nullable=True)
    validation_details = Column(_json_type(), nullable=True)
    input_snapshot = Column(_json_type(), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )

    owner = relationship("User", back_populates="applications")
    documents = relationship("ApplicationDocument", back_populates="application")
    processing_runs = relationship("ProcessingRun", back_populates="application")
    agent_events = relationship("AgentEvent", back_populates="application")

    @property
    def processing_failure(self):
        from services.processing_errors import describe_application_failure

        return describe_application_failure(self)

    @validates("submitted_date")
    def normalize_submitted_date(self, key, value):
        return _parse_iso_date(value)


class ApplicationDocument(Base):
    __tablename__ = "application_documents"

    id = Column(Integer, primary_key=True)
    application_id = Column(
        Integer,
        ForeignKey("applications.id"),
        index=True,
        nullable=False,
    )
    document_role = Column(String(64), nullable=False)
    original_filename = Column(Text, nullable=False)
    cos_object_key = Column(Text, nullable=False)
    content_type = Column(String(255), nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(CHAR(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    application = relationship("Application", back_populates="documents")


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id = Column(Integer, primary_key=True)
    application_id = Column(
        Integer,
        ForeignKey("applications.id"),
        index=True,
        nullable=False,
    )
    attempt_number = Column(Integer, nullable=False)
    status = Column(String(64), nullable=False)
    started_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_text = Column(Text, nullable=True)

    application = relationship("Application", back_populates="processing_runs")


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        Index(
            "ix_agent_events_application_id_occurred_at",
            "application_id",
            "occurred_at",
        ),
    )

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    application_id = Column(
        Integer,
        ForeignKey("applications.id"),
        nullable=True,
    )
    external_application_id = Column(String(64), index=True, nullable=False)
    stage = Column(String(64), nullable=False)
    occurred_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    payload = Column(_json_type(), nullable=False)
    legacy_source_id = Column(String(64), unique=True, nullable=True)

    application = relationship("Application", back_populates="agent_events")


class MigrationAnomaly(Base):
    __tablename__ = "migration_anomalies"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "source_id",
            name="uq_migration_anomalies_kind_source_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(64), nullable=False)
    external_application_id = Column(String(64), nullable=False)
    source_id = Column(String(64), nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
