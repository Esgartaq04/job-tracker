import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base
from src.models.types import TimestampTZ, UUIDType
from src.models.util import utcnow


class LLMCall(Base):
    """One model call made on a user's behalf, on their own key. A usage record: the
    limits are the user's own Claude account's, not the app's."""

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
