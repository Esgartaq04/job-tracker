"""How the AI features' expected failures reach a client."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status

from src.services import ai

logger = logging.getLogger(__name__)


@contextmanager
def ai_errors() -> Iterator[None]:
    """Map the reasons an AI call can't happen onto statuses the web app and the
    extension can explain: 503 off, 429 cap spent, 413/415/422 a bad resume, 502 the
    model failed."""
    try:
        yield
    except ai.AIUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ai.AIQuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ai.ResumeRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except ai.AIFailed as exc:
        logger.warning("AI call failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:
        if not ai.is_sdk_error(exc):
            raise
        # Rate limits, overload, timeouts — logged in full, reported plainly.
        logger.exception("AI call failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The AI service couldn't complete that. Try again shortly."
        ) from exc
