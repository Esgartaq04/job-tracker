from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware UTC now. SQLite drops tzinfo on read; see `as_utc`."""
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes read back from SQLite."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
