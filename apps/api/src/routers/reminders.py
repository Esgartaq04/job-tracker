import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from src.core.config import settings
from src.core.deps import CurrentUser, DbSession
from src.schemas.reminders import ReminderOut, RemindersOut
from src.services import reminders as reminder_service
from src.services.applications import to_out

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("", response_model=RemindersOut)
def list_reminders(
    user: CurrentUser,
    db: DbSession,
    look_ahead: Annotated[int, Query(ge=0, le=60)] = reminder_service.LOOK_AHEAD_DAYS,
) -> RemindersOut:
    """What needs attention: overdue and due follow-ups first, then cards gone quiet."""
    found = reminder_service.collect(db, user.id, look_ahead=look_ahead)
    return RemindersOut(
        summary=reminder_service.digest(found),
        count=len(found),
        items=[
            ReminderOut(
                kind=reminder.kind,
                reason=reminder.reason,
                due_at=reminder.due_at,
                days=reminder.days,
                application=to_out(reminder.application),
            )
            for reminder in found
        ],
    )


@router.post("/sweep", include_in_schema=False)
def run_sweep(
    db: DbSession,
    x_sweep_secret: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    """Run the daily reminder sweep on demand, for an external scheduler.

    Without Redis there is no worker and so no arq cron, which is the one reminder
    feature that disappears in the free deployment (docs/DEPLOYMENT.md §3.4). `GET
    /reminders` still computes on demand, so this restores only the unprompted push.

    Both failures are 404 rather than 401/403: an unconfigured deployment shouldn't
    advertise that the route exists, and neither should a wrong guess.
    """
    configured = settings.sweep_secret
    if not configured or not x_sweep_secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Constant-time: the secret is guessable a byte at a time otherwise.
    if not secrets.compare_digest(x_sweep_secret, configured):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    counts = reminder_service.sweep(db)
    db.commit()
    return counts
