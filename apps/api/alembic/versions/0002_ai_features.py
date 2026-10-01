"""AI features — cleaned descriptions, stored cover letters, and per-user call metering.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("description_clean", sa.Text()))
    op.add_column("documents", sa.Column("content", sa.Text()))
    op.add_column("documents", sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.create_index("ix_documents_application_id", "documents", ["application_id"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_llm_calls_user_created", "llm_calls", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("llm_calls")
    op.drop_index("ix_documents_application_id", table_name="documents")
    op.drop_column("documents", "updated_at")
    op.drop_column("documents", "content")
    op.drop_column("applications", "description_clean")
