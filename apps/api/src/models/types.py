"""Column types that render natively on Postgres and degrade cleanly on SQLite."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from src.models.enums import AppStatus

#: JSONB on Postgres, plain JSON on SQLite.
JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

#: Native uuid on Postgres, CHAR(32) elsewhere (SQLAlchemy 2.0 handles the conversion).
UUIDType = sa.Uuid(as_uuid=True)


def app_status_column(**kwargs) -> sa.Column:
    return sa.Column(app_status_type(), **kwargs)


def app_status_type() -> sa.Enum:
    """Postgres ENUM `app_status`; VARCHAR + CHECK on SQLite."""
    return sa.Enum(
        AppStatus,
        name="app_status",
        values_callable=lambda enum: [member.value for member in enum],
        native_enum=True,
        create_constraint=False,
    )


class UTCDateTime(sa.types.TypeDecorator):
    """`TIMESTAMPTZ` that stays timezone-aware on SQLite too.

    SQLite has no timezone-aware type, so values come back naive and a JSON response
    would silently lose its `Z`. Everything is stored as UTC and re-tagged on read,
    which keeps "days since applied" honest on both engines.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


TimestampTZ = UTCDateTime()
