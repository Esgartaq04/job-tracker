"""Initial schema — applications, status events, tags, documents, contacts, ingest jobs.

Mirrors the data model in README §5. Postgres gets the native `app_status` enum, JSONB,
the generated `search_vector` column and its GIN index; on SQLite (local dev and CI)
those degrade to VARCHAR/JSON and the search endpoint falls back to LIKE.

Revision ID: 0001
Revises:
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_STATUS_VALUES = (
    "saved",
    "applied",
    "oa",
    "phone_screen",
    "interview",
    "final",
    "offer",
    "rejected",
    "withdrawn",
    "ghosted",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _jsonb():
    return postgresql.JSONB() if _is_postgres() else sa.JSON()


def _app_status():
    """The enum type is created once, explicitly, above — `create_type=False` stops
    each column from re-emitting `CREATE TYPE` and failing the whole migration."""
    if _is_postgres():
        return postgresql.ENUM(*APP_STATUS_VALUES, name="app_status", create_type=False)
    return sa.Enum(*APP_STATUS_VALUES, name="app_status")


def upgrade() -> None:
    postgres = _is_postgres()

    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        op.execute(
            "CREATE TYPE app_status AS ENUM ("
            + ", ".join(f"'{value}'" for value in APP_STATUS_VALUES)
            + ")"
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # source
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("source_host", sa.Text()),
        sa.Column("ats_vendor", sa.Text()),
        # identity
        sa.Column("company", sa.Text()),
        sa.Column("company_domain", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column("is_remote", sa.Boolean()),
        sa.Column("employment_type", sa.Text()),
        sa.Column("req_id", sa.Text()),
        # compensation
        sa.Column("salary_min", sa.Numeric(12, 2)),
        sa.Column("salary_max", sa.Numeric(12, 2)),
        sa.Column("salary_currency", sa.String(3)),
        sa.Column("salary_period", sa.Text()),
        # description
        sa.Column("description_raw", sa.Text()),
        sa.Column("description_html", sa.Text()),
        sa.Column("description_user", sa.Text()),
        sa.Column("extraction_meta", _jsonb(), nullable=False, server_default="{}"),
        # lifecycle
        sa.Column("status", _app_status(), nullable=False, server_default="saved"),
        sa.Column("board_position", sa.Float(), nullable=False, server_default="1024"),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("next_action_at", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("ingest_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_applications_user_id", "applications", ["user_id"])
    op.create_index(
        "ux_app_user_url",
        "applications",
        ["user_id", "canonical_url"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
        sqlite_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_app_board",
        "applications",
        ["user_id", "status", "board_position"],
        postgresql_where=sa.text("archived_at IS NULL"),
        sqlite_where=sa.text("archived_at IS NULL"),
    )

    if postgres:
        # Generated column + GIN index power /search; SQLite falls back to LIKE.
        op.execute(
            """
            ALTER TABLE applications ADD COLUMN search_vector TSVECTOR
            GENERATED ALWAYS AS (
                to_tsvector('english',
                    coalesce(company, '') || ' ' || coalesce(title, '') || ' ' ||
                    coalesce(location, '') || ' ' ||
                    coalesce(description_user, description_raw, ''))
            ) STORED
            """
        )
        op.execute("CREATE INDEX ix_app_search ON applications USING GIN(search_vector)")

    op.create_table(
        "status_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", _app_status()),
        sa.Column("to_status", _app_status(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float()),
        sa.Column("note", sa.Text()),
        sa.Column("evidence", _jsonb()),
    )
    op.create_index("ix_status_events_application_id", "status_events", ["application_id"])

    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text()),
        sa.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )
    op.create_index("ix_tags_user_id", "tags", ["user_id"])

    op.create_table(
        "application_tags",
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="SET NULL"),
        ),
        sa.Column("kind", sa.Text()),
        sa.Column("label", sa.Text()),
        sa.Column("gcs_path", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
        ),
        sa.Column("name", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("role", sa.Text()),
        sa.Column("linkedin_url", sa.Text()),
        sa.Column("notes", sa.Text()),
    )
    op.create_index("ix_contacts_user_id", "contacts", ["user_id"])

    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
        ),
        sa.Column("url", sa.Text()),
        sa.Column("tier_attempted", _jsonb(), nullable=False, server_default="[]"),
        sa.Column("tier_succeeded", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ingest_jobs_application_id", "ingest_jobs", ["application_id"])


def downgrade() -> None:
    op.drop_table("ingest_jobs")
    op.drop_table("contacts")
    op.drop_table("documents")
    op.drop_table("application_tags")
    op.drop_table("tags")
    op.drop_table("status_events")
    op.drop_table("applications")
    op.drop_table("users")
    if _is_postgres():
        op.execute("DROP TYPE IF EXISTS app_status")
