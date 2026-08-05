"""Status transitions and their side effects (README §7.1)."""

from datetime import datetime

from sqlalchemy.orm import Session

from src.models import Application, AppStatus, EventSource, StatusEvent
from src.models.util import utcnow


def apply_transition(
    db: Session,
    application: Application,
    to_status: AppStatus,
    *,
    source: EventSource = EventSource.manual,
    note: str | None = None,
    confidence: float | None = None,
    evidence: dict | None = None,
    occurred_at: datetime | None = None,
) -> StatusEvent | None:
    """Move a card and record the transition. No-ops (same status) write no event."""
    from_status = application.status
    if from_status == to_status:
        return None

    now = occurred_at or utcnow()

    # Side effects that must not be left to the client.
    if to_status == AppStatus.applied and application.applied_at is None:
        application.applied_at = now
    if to_status in (AppStatus.rejected, AppStatus.withdrawn) and application.closed_at is None:
        application.closed_at = now
    if to_status not in (AppStatus.rejected, AppStatus.withdrawn):
        # Re-opening a closed card clears the close stamp.
        application.closed_at = None

    application.status = to_status
    application.updated_at = now

    event = StatusEvent(
        application_id=application.id,
        from_status=from_status,
        to_status=to_status,
        occurred_at=now,
        source=source,
        confidence=confidence,
        note=note,
        evidence=evidence,
    )
    db.add(event)
    return event


def record_initial_event(
    db: Session,
    application: Application,
    *,
    source: EventSource = EventSource.manual,
    note: str | None = None,
) -> StatusEvent:
    """Every application starts its timeline with the status it was created in."""
    event = StatusEvent(
        application_id=application.id,
        from_status=None,
        to_status=application.status,
        occurred_at=application.saved_at,
        source=source,
        note=note,
    )
    db.add(event)
    return event
