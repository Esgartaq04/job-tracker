"""arq worker — the deployed shape of the ingestion queue (README §3, §4).

Runs as its own Cloud Run service so a Playwright render or a slow origin can't tie
up an API instance. Without `REDIS_URL` the API runs ingestion in-process instead and
this worker isn't needed at all — see `src/services/ingestion/queue.py`.

    arq worker.WorkerSettings
"""

import asyncio
import logging
import sys
import uuid
from pathlib import Path

# The worker imports the API package rather than duplicating the pipeline.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

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


async def sweep_stale(_ctx: dict) -> None:
    """Nightly: log how many applications have gone quiet. Phase 3 turns this into
    the reminder emails; for now it's the signal that the sweep is wired up."""
    from sqlalchemy import select

    from src.core.db import session_scope
    from src.models import Application
    from src.services.applications import compute_staleness

    db = session_scope()
    try:
        rows = db.scalars(select(Application).where(Application.archived_at.is_(None))).all()
        stale = [row for row in rows if compute_staleness(row) != "none"]
        logger.info("stale sweep: %d of %d applications need a nudge", len(stale), len(rows))
    finally:
        db.close()


async def startup(_ctx: dict) -> None:
    logger.info("worker ready (db=%s)", settings.database_url.split("@")[-1])


class WorkerSettings:
    functions = [ingest_application]
    cron_jobs = []  # populated in Phase 3 alongside reminders
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    max_jobs = 4
    job_timeout = 120
    keep_result = 3600
