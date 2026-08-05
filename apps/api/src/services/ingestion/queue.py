"""Enqueue ingestion work.

Two backends behind one call:

* **arq** when ``REDIS_URL`` is set — the deployed shape from README §3, with the
  worker as its own Cloud Run service.
* **Thread pool** otherwise — keeps `docker compose up` and the test suite to a
  single process. The pipeline is synchronous (httpx + SQLAlchemy), so a thread is
  the honest primitive here; the API stays responsive because `POST /ingest` returns
  the provisional record before any of this runs.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from src.core.config import settings
from src.core.db import session_scope

logger = logging.getLogger(__name__)

#: Bounded so a 50-URL paste can't open 50 sockets at once (README §11: rate-limit hard).
_MAX_WORKERS = 4
_executor: ThreadPoolExecutor | None = None

ARQ_QUEUE = "job_tracker:ingest"


def _pool() -> ThreadPoolExecutor:
    """Created on first use and re-created after a shutdown, so a process that
    restarts its app lifespan (tests, `uvicorn --reload`) can still enqueue."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="ingest")
    return _executor


def run_ingest_now(application_id: uuid.UUID) -> None:
    """Execute one ingestion with its own session. Safe to call from any thread."""
    from src.services.ingestion.pipeline import ingest_application

    db = session_scope()
    try:
        ingest_application(db, application_id)
    except Exception:
        logger.exception("ingestion failed for %s", application_id)
        db.rollback()
    finally:
        db.close()


def enqueue_ingest(application_id: uuid.UUID) -> None:
    if settings.redis_url:
        try:
            _enqueue_arq(application_id)
            return
        except Exception:  # pragma: no cover - queue outage must not lose the card
            logger.exception("arq enqueue failed; running ingestion in-process")
    _pool().submit(run_ingest_now, application_id)


def _enqueue_arq(application_id: uuid.UUID) -> None:
    import asyncio

    from arq import create_pool
    from arq.connections import RedisSettings

    async def _push() -> None:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await redis.enqueue_job("ingest_application", str(application_id))
        finally:
            await redis.aclose()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_push())
        return
    loop.create_task(_push())


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=False)
        _executor = None
