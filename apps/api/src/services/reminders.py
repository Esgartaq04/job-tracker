"""What needs a nudge, and why (README §7.1, §10 Phase 3).

Staleness alone answers "which cards have gone quiet"; a reminder answers "what should
I do today". Both land here so the board badge, the worker sweep, and any future email
all agree on the definition rather than each inventing one.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import Application
from src.models.enums import TERMINAL_STATUSES
from src.models.util import as_utc, utcnow
from src.services.applications import compute_staleness, user_applications

logger = logging.getLogger(__name__)


class ReminderKind(StrEnum):
    overdue = "overdue"  # next_action_at has passed
    due_today = "due_today"
    upcoming = "upcoming"  # within the look-ahead window
    stale = "stale"  # no movement, no action set


@dataclass
class Reminder:
    application: Application
    kind: ReminderKind
    due_at: datetime | None
    days: int  # negative when overdue, positive when ahead

    @property
    def reason(self) -> str:
        if self.kind is ReminderKind.overdue:
            return f"Follow-up was due {abs(self.days)}d ago"
        if self.kind is ReminderKind.due_today:
            return "Follow-up due today"
        if self.kind is ReminderKind.upcoming:
            return f"Follow-up in {self.days}d"
        idle = self.days
        return f"No movement in {idle}d"


#: How far ahead a reminder is worth surfacing. Beyond this it's just noise.
LOOK_AHEAD_DAYS = 7


def collect(
    db: Session, user_id: uuid.UUID, *, now: datetime | None = None, look_ahead: int | None = None
) -> list[Reminder]:
    """Everything that wants attention, most urgent first.

    A card with an explicit `next_action_at` is reported on that date and never also
    reported as stale — the user has already said what they intend to do, so nagging
    about silence on top of it is noise.
    """
    now = now or utcnow()
    horizon = now + timedelta(days=look_ahead if look_ahead is not None else LOOK_AHEAD_DAYS)

    reminders: list[Reminder] = []
    for application in db.scalars(user_applications(user_id)).unique().all():
        if application.status in TERMINAL_STATUSES:
            continue

        due_at = as_utc(application.next_action_at)
        if due_at is not None:
            if due_at > horizon:
                continue
            days = (due_at.date() - now.date()).days
            kind = (
                ReminderKind.due_today
                if days == 0
                else ReminderKind.overdue
                if days < 0
                else ReminderKind.upcoming
            )
            reminders.append(Reminder(application, kind, due_at, days))
            continue

        if compute_staleness(application, now) != "none":
            anchor = as_utc(application.applied_at) or as_utc(application.saved_at)
            reminders.append(Reminder(application, ReminderKind.stale, None, (now - anchor).days))

    order = {
        ReminderKind.overdue: 0,
        ReminderKind.due_today: 1,
        ReminderKind.upcoming: 2,
        ReminderKind.stale: 3,
    }
    reminders.sort(key=lambda reminder: (order[reminder.kind], -reminder.days))
    return reminders


def digest(reminders: list[Reminder]) -> str:
    """One-line summary — what a notification or an email subject says."""
    if not reminders:
        return "Nothing needs attention"

    counts: dict[ReminderKind, int] = {}
    for reminder in reminders:
        counts[reminder.kind] = counts.get(reminder.kind, 0) + 1

    parts = []
    if counts.get(ReminderKind.overdue):
        parts.append(f"{counts[ReminderKind.overdue]} overdue")
    if counts.get(ReminderKind.due_today):
        parts.append(f"{counts[ReminderKind.due_today]} due today")
    if counts.get(ReminderKind.stale):
        parts.append(f"{counts[ReminderKind.stale]} gone quiet ({settings.stale_warn_days}d+)")
    if not parts and counts.get(ReminderKind.upcoming):
        parts.append(f"{counts[ReminderKind.upcoming]} coming up")
    return ", ".join(parts)


def sweep(db: Session) -> dict[str, int]:
    """Notify every user about what needs attention.

    Two callers, one definition: the arq cron in `apps/worker/worker.py` when Redis is
    deployed, and `POST /reminders/sweep` when it isn't (docs/DEPLOYMENT.md §3.4). Both
    are idempotent — running it twice in a day sends the same digest again, which is a
    better failure than a day with no digest at all.
    """
    # Imported here: notify imports this module, so a module-level import would cycle.
    from src.models import User
    from src.services.notify import notify_user

    counts = {"users": 0, "notified": 0, "reminders": 0}
    for user in db.scalars(select(User)).all():
        counts["users"] += 1
        found = collect(db, user.id)
        if not found:
            continue
        counts["notified"] += 1
        counts["reminders"] += len(found)
        notify_user(user.id, user.email, found)
        logger.info("reminders for %s: %s", user.email, digest(found))
    return counts
