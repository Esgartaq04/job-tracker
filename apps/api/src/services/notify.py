"""Reminder delivery.

The tracker has two channels it can use without asking anyone for credentials: the SSE
stream (a connected browser gets a notification immediately) and the log. Email needs a
provider, so it sits behind this interface with a logging implementation as the default
— the sweep, the digest and the templates all work today, and turning email on later is
a settings change plus one class, not a rewrite.
"""

import logging
import uuid
from typing import Protocol

from src.core.config import settings
from src.services import events
from src.services.reminders import Reminder, digest

logger = logging.getLogger(__name__)


class Sender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class LoggingSender:
    """The default. Writes what it *would* send, so the digest is verifiable in a log
    without pretending a message was delivered."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info(
            "reminder digest not sent (no email provider configured): to=%s subject=%s",
            to,
            subject,
        )
        logger.debug("digest body:\n%s", body)


def get_sender() -> Sender:
    # When a provider is configured, construct it here. Deliberately not implemented
    # against a provider we can't exercise — see docs/STATUS.md.
    return LoggingSender()


def render_digest(reminders: list[Reminder]) -> tuple[str, str]:
    """→ (subject, body). Plain text: this is a nudge, not a newsletter."""
    subject = f"Job tracker — {digest(reminders)}"

    lines = []
    for reminder in reminders:
        application = reminder.application
        label = f"{application.company or 'Unknown'} — {application.title or 'Untitled'}"
        lines.append(f"- {label}: {reminder.reason}")

    body = "\n".join(
        [
            digest(reminders),
            "",
            *lines,
            "",
            "Open the board to act on these.",
        ]
    )
    return subject, body


def notify_user(user_id: uuid.UUID, email: str, reminders: list[Reminder]) -> None:
    """Push to any connected browser, then hand the digest to the sender."""
    if not reminders:
        return

    events.publish(
        user_id,
        "reminder.due",
        {
            "summary": digest(reminders),
            "count": len(reminders),
            "items": [
                {
                    "application_id": str(reminder.application.id),
                    "company": reminder.application.company,
                    "title": reminder.application.title,
                    "kind": reminder.kind.value,
                    "reason": reminder.reason,
                }
                # A notification is a nudge, not a report — link to the board for the rest.
                for reminder in reminders[:5]
            ],
        },
    )

    if settings.reminder_email_enabled:
        subject, body = render_digest(reminders)
        get_sender().send(to=email, subject=subject, body=body)
