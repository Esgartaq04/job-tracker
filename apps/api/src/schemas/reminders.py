from datetime import datetime

from pydantic import BaseModel

from src.schemas.application import ApplicationOut
from src.services.reminders import ReminderKind


class ReminderOut(BaseModel):
    kind: ReminderKind
    reason: str
    due_at: datetime | None
    #: Negative when overdue, positive when ahead; for a stale card, days since movement.
    days: int
    application: ApplicationOut


class RemindersOut(BaseModel):
    summary: str
    count: int
    items: list[ReminderOut]
