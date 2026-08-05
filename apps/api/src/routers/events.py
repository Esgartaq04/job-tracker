import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.core.deps import CurrentUser
from src.services import events as event_service

router = APIRouter(tags=["events"])

#: Comment frames keep proxies (and Cloud Run's 5-minute idle timeout) from
#: closing an otherwise-quiet connection.
HEARTBEAT_SECONDS = 20


@router.get("/events")
async def stream_events(user: CurrentUser) -> StreamingResponse:
    """SSE: ingest progress now, email-derived updates in v2 (README §6).

    `EventSource` can't set an Authorization header, so this route also accepts
    `?access_token=` — see `get_current_user`.
    """

    async def publisher() -> AsyncIterator[str]:
        yield ": connected\n\n"
        stream = event_service.stream(user.id)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(stream.__anext__(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                except StopAsyncIteration:
                    break
                yield event_service.sse_format(payload)
        except asyncio.CancelledError:  # client went away
            raise
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/events/test", include_in_schema=False)
async def emit_test_event(user: CurrentUser) -> dict:
    """Publish a no-op event — useful when checking that SSE reaches the browser."""
    event_service.publish(user.id, "ping", {"message": "pong"})
    return json.loads('{"ok": true}')
