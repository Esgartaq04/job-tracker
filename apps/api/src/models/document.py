import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base
from src.models.types import TimestampTZ, UUIDType
from src.models.util import utcnow


class Document(Base):
    """Which resume version went to which company (README §5), and the cover letters
    generated for a listing. A cover letter's text lives in `content`; resumes are
    never stored — they're uploaded for one call and discarded."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str | None] = mapped_column(sa.Text)  # resume | cover_letter | portfolio
    label: Mapped[str | None] = mapped_column(sa.Text)
    gcs_path: Mapped[str | None] = mapped_column(sa.Text)
    content: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        TimestampTZ, nullable=False, default=utcnow, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(TimestampTZ, onupdate=utcnow)


class Contact(Base):
    """Recruiters and referrals."""

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("applications.id", ondelete="CASCADE")
    )
    name: Mapped[str | None] = mapped_column(sa.Text)
    email: Mapped[str | None] = mapped_column(sa.Text)
    role: Mapped[str | None] = mapped_column(sa.Text)
    linkedin_url: Mapped[str | None] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
