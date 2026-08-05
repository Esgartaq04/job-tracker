import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base
from src.models.types import JSONB, TimestampTZ, UUIDType
from src.models.util import utcnow


class IngestJob(Base):
    """Per-attempt pipeline telemetry — the thing that makes a failed paste debuggable
    from the URL alone (README §4.1)."""

    __tablename__ = "ingest_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str | None] = mapped_column(sa.Text)
    # Postgres would use TEXT[]; JSON keeps the column portable to SQLite.
    tier_attempted: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tier_succeeded: Mapped[str | None] = mapped_column(sa.Text)
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(sa.Text)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = mapped_column(
        TimestampTZ, nullable=False, default=utcnow, server_default=sa.func.now()
    )
