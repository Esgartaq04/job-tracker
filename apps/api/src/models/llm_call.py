import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base
from src.models.types import TimestampTZ, UUIDType
from src.models.util import utcnow


class LLMCall(Base):
    """One model call made on a user's behalf. Exists so `llm_monthly_call_cap` is a
    limit rather than a number in a config file (README §8.3: track spend per user
    from day one, cap it, degrade when it's hit)."""

    __tablename__ = "llm_calls"
    __table_args__ = (sa.Index("ix_llm_calls_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: extraction | cleanup | cover_letter | resume_profile | autofill
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TimestampTZ, nullable=False, default=utcnow, server_default=sa.func.now()
    )
