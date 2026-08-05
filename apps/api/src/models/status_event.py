import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base
from src.models.enums import AppStatus, EventSource
from src.models.types import JSONB, TimestampTZ, UUIDType, app_status_type
from src.models.util import utcnow


class StatusEvent(Base):
    """Append-only transition log. Powers the timeline, the funnel, and (v2) the
    audit trail for AI-proposed transitions (README §5.2)."""

    __tablename__ = "status_events"

    # SQLite only auto-increments a plain INTEGER primary key, never a BIGINT.
    id: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        sa.ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[AppStatus | None] = mapped_column(app_status_type())
    to_status: Mapped[AppStatus] = mapped_column(app_status_type(), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        TimestampTZ, nullable=False, default=utcnow, server_default=sa.func.now()
    )
    source: Mapped[EventSource] = mapped_column(sa.Text, nullable=False, default=EventSource.manual)
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    note: Mapped[str | None] = mapped_column(sa.Text)
    evidence: Mapped[dict | None] = mapped_column(JSONB)

    application = relationship("Application", back_populates="events", lazy="noload")
