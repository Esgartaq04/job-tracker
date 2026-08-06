"""arq worker — the deployed shape of the ingestion queue and the reminder sweep
(README §3, §4, §10 Phase 3).

Runs as its own Cloud Run service so a Playwright render or a slow origin can't tie up
an API instance. Without `REDIS_URL` the API runs ingestion in-process and this worker
isn't needed at all — see `src/services/ingestion/queue.py`.

    arq worker.WorkerSettings
"""

import asyncio
import logging
import sys
import uuid
from pathlib import Path

# The worker imports the API package rather than duplicating the pipeline.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from arq import cron  # noqa: E402
from arq.connections import RedisSettings  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.services.ingestion.queue import run_ingest_now  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger("worker")


async def ingest_application(_ctx: dict, application_id: str) -> None:
    """The pipeline is synchronous (httpx + SQLAlchemy), so it runs in a thread and
    leaves the event loop free to pull the next job."""
    await asyncio.to_thread(run_ingest_now, uuid.UUID(application_id))


def _sweep() -> dict[str, int]:
    """Notify every user about what needs attention. Runs in a thread — sync DB."""
    from sqlalchemy import select

    from src.core.db import session_scope
    from src.models import User
    from src.services import reminders as reminder_service
    from src.services.notify import notify_user

    db = session_scope()
    counts = {"users": 0, "notified": 0, "reminders": 0}
    try:
        for user in db.scalars(select(User)).all():
            counts["users"] += 1
            found = reminder_service.collect(db, user.id)
            if not found:
                continue
            counts["notified"] += 1
            counts["reminders"] += len(found)
            notify_user(user.id, user.email, found)
            logger.info(
                "reminders for %s: %s", user.email, reminder_service.digest(found)
            )
    finally:
        db.close()
    return counts


async def sweep_reminders(_ctx: dict) -> dict[str, int]:
    """Daily: surface overdue follow-ups and cards that have gone quiet.

    Delivery is whatever is configured — a connected browser gets an SSE notification
    immediately; email is off until a provider exists (`src/services/notify.py`).
    """
    counts = await asyncio.to_thread(_sweep)
    logger.info(
        "reminder sweep: %(reminders)d reminders for %(notified)d of %(users)d users",
        counts,
    )
    return counts


async def startup(_ctx: dict) -> None:
    logger.info("worker ready (db=%s)", settings.database_url.split("@")[-1])


class WorkerSettings:
    functions = [ingest_application, sweep_reminders]
    cron_jobs = [
        cron(
            sweep_reminders,
            hour={settings.reminder_sweep_hour_utc},
            minute={0},
            # One instance runs it, not every replica.
            unique=True,
        )
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    max_jobs = 4
    job_timeout = 120
    keep_result = 3600
