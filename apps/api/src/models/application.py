import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base
from src.models.enums import AppStatus, IngestStatus
from src.models.types import JSONB, TimestampTZ, UUIDType, app_status_type
from src.models.util import utcnow


class Application(Base):
    """One tracked posting. `description_raw` is immutable; user edits live in
    `description_user` so "Restore original" always works (README §7.3)."""

    __tablename__ = "applications"
    __table_args__ = (
        sa.Index(
            "ux_app_user_url",
            "user_id",
            "canonical_url",
            unique=True,
            sqlite_where=sa.text("archived_at IS NULL"),
            postgresql_where=sa.text("archived_at IS NULL"),
        ),
        sa.Index(
            "ix_app_board",
            "user_id",
            "status",
            "board_position",
            sqlite_where=sa.text("archived_at IS NULL"),
            postgresql_where=sa.text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── source ────────────────────────────────────────────────────────────
    source_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_host: Mapped[str | None] = mapped_column(sa.Text)
    ats_vendor: Mapped[str | None] = mapped_column(sa.Text)

    # ── identity ──────────────────────────────────────────────────────────
    company: Mapped[str | None] = mapped_column(sa.Text)
    company_domain: Mapped[str | None] = mapped_column(sa.Text)
    title: Mapped[str | None] = mapped_column(sa.Text)
    location: Mapped[str | None] = mapped_column(sa.Text)
    is_remote: Mapped[bool | None] = mapped_column(sa.Boolean)
    employment_type: Mapped[str | None] = mapped_column(sa.Text)
    req_id: Mapped[str | None] = mapped_column(sa.Text)

    # ── compensation ──────────────────────────────────────────────────────
    salary_min: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(sa.String(3))
    salary_period: Mapped[str | None] = mapped_column(sa.Text)

    # ── description ───────────────────────────────────────────────────────
    description_raw: Mapped[str | None] = mapped_column(sa.Text)
    description_html: Mapped[str | None] = mapped_column(sa.Text)
    description_user: Mapped[str | None] = mapped_column(sa.Text)
    extraction_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ── lifecycle ─────────────────────────────────────────────────────────
    status: Mapped[AppStatus] = mapped_column(
        app_status_type(), nullable=False, default=AppStatus.saved
    )
    board_position: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    saved_at: Mapped[datetime] = mapped_column(
        TimestampTZ, nullable=False, default=utcnow, server_default=sa.func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    posted_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    closed_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    next_action_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    priority: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=0)

    ingest_status: Mapped[IngestStatus] = mapped_column(
        sa.Text, nullable=False, default=IngestStatus.pending
    )
    notes: Mapped[str | None] = mapped_column(sa.Text)
    archived_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    created_at: Mapped[datetime] = mapped_column(
        TimestampTZ, nullable=False, default=utcnow, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampTZ,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=sa.func.now(),
    )

    user = relationship("User", back_populates="applications", lazy="noload")
    events = relationship(
        "StatusEvent",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="StatusEvent.occurred_at",
        lazy="selectin",
    )
    tags = relationship("Tag", secondary="application_tags", lazy="selectin")

    @property
    def description(self) -> str | None:
        """What the UI shows: the user's edit shadows the extracted text."""
        return self.description_user or self.description_raw
