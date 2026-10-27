import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base
from src.models.types import TimestampTZ, UUIDType
from src.models.util import utcnow


class UserAIKey(Base):
    """A user's own Claude API key, sealed (see `src.core.crypto`). One row per user.

    Lives apart from `users` so the ciphertext is never on the object that
    `get_current_user` loads for every request, where a future response model could
    serialise it by accident."""

    __tablename__ = "user_ai_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ciphertext: Mapped[str] = mapped_column(sa.Text, nullable=False)
    #: "…" plus the key's last four characters. The only part of the key shown to anyone.
    hint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    #: ok | rejected. Rejected means Claude refused the key on a real call; saving a new
    #: key sets it back to ok.
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="ok", server_default="ok")
    verified_at: Mapped[datetime] = mapped_column(
        TimestampTZ, nullable=False, default=utcnow, server_default=sa.func.now()
    )
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
