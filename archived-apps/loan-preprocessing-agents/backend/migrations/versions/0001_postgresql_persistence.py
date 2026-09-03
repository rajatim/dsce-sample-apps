"""Create the PostgreSQL-compatible loan persistence schema.

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_id_str", sa.String(length=64), nullable=False),
        sa.Column("applicant_name", sa.String(length=255), nullable=False),
        sa.Column("loan_type", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("submitted_date", sa.Date(), nullable=False),
        sa.Column("validation_comments", sa.Text(), nullable=True),
        sa.Column("validation_details", _json_type(), nullable=True),
        sa.Column("input_snapshot", _json_type(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_applications_app_id_str",
        "applications",
        ["app_id_str"],
        unique=True,
    )
    op.create_index(
        "ix_applications_owner_id",
        "applications",
        ["owner_id"],
        unique=False,
    )

    op.create_table(
        "application_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("document_role", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("cos_object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_documents_application_id",
        "application_documents",
        ["application_id"],
        unique=False,
    )

    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_runs_application_id",
        "processing_runs",
        ["application_id"],
        unique=False,
    )

    op.create_table(
        "agent_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("external_application_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", _json_type(), nullable=False),
        sa.Column("legacy_source_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("legacy_source_id"),
    )
    op.create_index(
        "ix_agent_events_external_application_id",
        "agent_events",
        ["external_application_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_events_application_id_occurred_at",
        "agent_events",
        ["application_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "migration_anomalies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("external_application_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "kind",
            "source_id",
            name="uq_migration_anomalies_kind_source_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("migration_anomalies")

    op.drop_index(
        "ix_agent_events_application_id_occurred_at",
        table_name="agent_events",
    )
    op.drop_index(
        "ix_agent_events_external_application_id",
        table_name="agent_events",
    )
    op.drop_table("agent_events")

    op.drop_index(
        "ix_processing_runs_application_id",
        table_name="processing_runs",
    )
    op.drop_table("processing_runs")

    op.drop_index(
        "ix_application_documents_application_id",
        table_name="application_documents",
    )
    op.drop_table("application_documents")

    op.drop_index("ix_applications_owner_id", table_name="applications")
    op.drop_index("ix_applications_app_id_str", table_name="applications")
    op.drop_table("applications")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
