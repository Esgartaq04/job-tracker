"""Server-sent event fan-out for ingest progress and (v2) email-derived updates.

Two backends, picked by configuration:

* **In-memory** (no ``REDIS_URL``) — the API process is also running ingestion, so a
  process-local hub is enough. Publishing is thread-safe because the pipeline runs in
  a worker thread.
* **Redis pub/sub** (``REDIS_URL`` set) — the worker is a separate process, so events
  travel over a channel per user. When Redis is configured it is the *only* path, so
  a subscriber never sees an event twice.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from src.core.config import settings
from src.models.util import utcnow

logger = logging.getLogger(__name__)

_QUEUE_MAX = 256


def channel_for(user_id: uuid.UUID) -> str:
    return f"events:{user_id}"


class EventHub:
    """Process-local pub/sub used when Redis isn't configured."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _deliver(self, user_id: uuid.UUID, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(user_id, ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover - slow consumer
                logger.warning("dropping SSE event for %s: queue full", user_id)

    def publish(self, user_id: uuid.UUID, payload: dict[str, Any]) -> None:
        """Safe to call from any thread."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                self._deliver(user_id, payload)
            else:
                loop.call_soon_threadsafe(self._deliver, user_id, payload)
        else:
            self._deliver(user_id, payload)

    async def subscribe(self, user_id: uuid.UUID) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subscribers.setdefault(user_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(user_id)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(user_id, None)


hub = EventHub()


def publish(user_id: uuid.UUID, event_type: str, data: dict[str, Any]) -> None:
    """Publish an event to whichever backend is configured."""
    payload = {"type": event_type, "at": utcnow().isoformat(), "data": data}

    if settings.redis_url:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url)
            client.publish(channel_for(user_id), json.dumps(payload, default=str))
            return
        except Exception:  # pragma: no cover - Redis outage must not break ingestion
            logger.exception("redis publish failed; falling back to in-memory hub")

    hub.publish(user_id, payload)


async def stream(user_id: uuid.UUID) -> AsyncIterator[dict[str, Any]]:
    """Async iterator of events for one user."""
    if settings.redis_url:
        try:
            import redis.asyncio as aioredis

            client = aioredis.Redis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(channel_for(user_id))
            try:
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    yield json.loads(message["data"])
            finally:
                await pubsub.unsubscribe(channel_for(user_id))
                await pubsub.aclose()
                await client.aclose()
            return
        except Exception:  # pragma: no cover - degrade rather than drop the connection
            logger.exception("redis subscribe failed; falling back to in-memory hub")

    async for payload in hub.subscribe(user_id):
        yield payload


def sse_format(payload: dict[str, Any]) -> str:
    return f"event: {payload['type']}\ndata: {json.dumps(payload, default=str)}\n\n"
