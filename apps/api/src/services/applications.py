"""Query, serialisation and tag helpers for applications."""

import uuid
from datetime import datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import Application, AppStatus, Tag
from src.models.enums import TERMINAL_STATUSES
from src.models.util import as_utc, utcnow
from src.schemas.application import ApplicationDetailOut, ApplicationOut


def user_applications(user_id: uuid.UUID, *, include_archived: bool = False) -> Select:
    stmt = select(Application).where(Application.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(Application.archived_at.is_(None))
    return stmt


def get_owned(db: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> Application | None:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user_id:
        return None
    return application


def apply_text_filter(stmt: Select, query: str) -> Select:
    """Full-text search on Postgres, LIKE on SQLite.

    The generated `search_vector` column exists only in the Postgres migration, so the
    dialect check keeps local/CI runs on SQLite working with the same endpoint.
    """
    if settings.is_sqlite:
        pattern = f"%{query.lower()}%"
        return stmt.where(
            or_(
                Application.company.ilike(pattern),
                Application.title.ilike(pattern),
                Application.location.ilike(pattern),
                Application.description_raw.ilike(pattern),
                Application.description_user.ilike(pattern),
            )
        )

    import re

    from sqlalchemy import func, literal_column

    # `plainto_tsquery` has no prefix matching, so typing "snow" would not find
    # "Snowflake" — which is exactly what a search box gets used for. Build the
    # query by hand instead, with every term prefix-matched.
    terms = re.findall(r"[\w']+", query.lower())
    if not terms:
        return stmt
    tsquery = " & ".join(f"{term}:*" for term in terms)
    return stmt.where(literal_column("search_vector").op("@@")(func.to_tsquery("english", tsquery)))


def days_between(start: datetime | None, end: datetime | None = None) -> int | None:
    if start is None:
        return None
    end = end or utcnow()
    return max((end - as_utc(start)).days, 0)


def compute_staleness(application: Application, now: datetime | None = None) -> str:
    """Amber at 14 days without movement, grey at 30 (README §7.1).

    "Movement" is the last status change, falling back to the applied/saved stamp.
    Terminal columns never go stale — they're already resolved.
    """
    if application.status in TERMINAL_STATUSES:
        return "none"

    now = now or utcnow()
    last_movement = as_utc(application.updated_at)
    if application.events:
        last_movement = max(
            [as_utc(event.occurred_at) for event in application.events] + [last_movement]
        )
    reference = as_utc(application.applied_at) or as_utc(application.saved_at)
    anchor = max(filter(None, [reference, last_movement])) if reference else last_movement

    idle_days = (now - anchor).days
    if idle_days >= settings.stale_dim_days:
        return "dim"
    if idle_days >= settings.stale_warn_days:
        return "warn"
    return "none"


def to_out(application: Application, *, detail: bool = False) -> ApplicationOut:
    model = ApplicationDetailOut if detail else ApplicationOut
    payload = model.model_validate(application)
    payload.description = application.description
    payload.days_since_applied = days_between(application.applied_at)
    payload.days_since_saved = days_between(application.saved_at)
    payload.staleness = compute_staleness(application)
    return payload


def resolve_tags(db: Session, user_id: uuid.UUID, names: list[str]) -> list[Tag]:
    """Get-or-create tags by name, scoped to the user."""
    cleaned = [name.strip() for name in names if name and name.strip()]
    if not cleaned:
        return []

    existing = {
        tag.name: tag
        for tag in db.scalars(
            select(Tag).where(Tag.user_id == user_id, Tag.name.in_(cleaned))
        ).all()
    }
    resolved: list[Tag] = []
    for name in dict.fromkeys(cleaned):
        tag = existing.get(name)
        if tag is None:
            tag = Tag(user_id=user_id, name=name)
            db.add(tag)
            db.flush()
        resolved.append(tag)
    return resolved


def parse_status(value: str) -> AppStatus:
    return AppStatus(value)
