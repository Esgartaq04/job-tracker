import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Hashable

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from src.core.deps import CurrentUser, DbSession
from src.models import UserAIKey
from src.schemas.ai_key import AIKeyIn, AIKeyOut
from src.services import ai_keys

router = APIRouter(prefix="/ai-key", tags=["ai key"])

_TOO_MANY = "Too many key attempts. Try again in an hour."


class SlidingWindow:
    """At most `limit` allowed calls per key in any `seconds`-long span, in memory.

    Per process, which is enough while one uvicorn worker serves the API. A refused call
    isn't recorded, so hammering the endpoint doesn't extend the lockout."""

    def __init__(
        self,
        limit: int,
        seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.seconds = seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: defaultdict[Hashable, deque[float]] = defaultdict(deque)

    def allow(self, key: Hashable) -> bool:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


#: Verifying a key is a call to Claude, so PUT is throttled to keep this endpoint from
#: being used to test stolen keys in bulk. Every attempt counts, valid or not.
attempts = SlidingWindow(limit=10, seconds=3600)


def _out(row: UserAIKey) -> AIKeyOut:
    return AIKeyOut(has_key=True, hint=row.hint, status=row.status, updated_at=row.updated_at)


@router.get("", response_model=AIKeyOut)
def get_ai_key(user: CurrentUser, db: DbSession) -> AIKeyOut:
    """Whether the user has a key saved. A row that can't be opened (a changed
    `AI_KEY_SECRET`) counts as no key: the user is asked to enter it again."""
    row = ai_keys.get_row(db, user.id)
    if row is None or ai_keys.read_key(db, user.id) is None:
        return AIKeyOut(has_key=False)
    return _out(row)


@router.put("", response_model=AIKeyOut)
def put_ai_key(payload: AIKeyIn, user: CurrentUser, db: DbSession) -> AIKeyOut:
    """Check a pasted key's shape, confirm with Claude that it works, then save it
    sealed. The response carries the hint, never the key."""
    user_id: uuid.UUID = user.id
    if not attempts.allow(user_id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _TOO_MANY)

    try:
        api_key = ai_keys.normalize(payload.api_key.get_secret_value())
    except ai_keys.KeyFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    try:
        ai_keys.verify(api_key)
    except ai_keys.KeyNotAccepted as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ai_keys.KeyCheckFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    try:
        row = _save(db, user_id, api_key)
    except IntegrityError:
        # Two first-time saves can both find no row and collide on the primary key. The
        # winner's row exists now, so the second attempt updates it.
        db.rollback()
        row = _save(db, user_id, api_key)
    return _out(row)


def _save(db: DbSession, user_id: uuid.UUID, api_key: str) -> UserAIKey:
    row = ai_keys.save_key(db, user_id, api_key)
    db.commit()
    return row


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_key(user: CurrentUser, db: DbSession) -> Response:
    ai_keys.delete_key(db, user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
