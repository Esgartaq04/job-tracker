import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base
from src.models.types import UUIDType


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (sa.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    color: Mapped[str | None] = mapped_column(sa.Text)


class ApplicationTag(Base):
    __tablename__ = "application_tags"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        sa.ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
