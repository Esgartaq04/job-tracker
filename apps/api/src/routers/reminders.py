from typing import Annotated

from fastapi import APIRouter, Query

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
