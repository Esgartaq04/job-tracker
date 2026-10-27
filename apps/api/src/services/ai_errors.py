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
    extension can explain: 428 no key, 424 key rejected, 503 off, 413/415/422 a bad
    resume, 429 and 402 the user's Claude account's limits (402 for both an empty balance
    and a spend limit), 502 the model failed.

    Never 401: the web app reads that as "signed out" and drops the session."""
    try:
        yield
    except ai.AIKeyMissing as exc:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, str(exc)) from exc
    except ai.AIKeyRejected as exc:
        raise HTTPException(status.HTTP_424_FAILED_DEPENDENCY, str(exc)) from exc
    except ai.AIUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ai.ResumeRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except ai.AIFailed as exc:
        logger.warning("AI call failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:
        kind = ai.sdk_error_kind(exc)
        if kind is None:
            raise
        if kind == "rate_limit":
            logger.info("AI call refused: the user's Claude account is rate-limited")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, ai.RATE_LIMITED) from exc
        if kind == "credit":
            logger.info("AI call refused: the user's Claude account is out of credit")
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, ai.OUT_OF_CREDIT) from exc
        if kind == "spend_limit":
            logger.info("AI call refused: the user's Claude account hit its spend limit")
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, ai.SPEND_LIMIT) from exc
        # Overload, timeouts, bad requests — logged in full, reported plainly.
        logger.exception("AI call failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, ai.AI_CALL_FAILED) from exc
