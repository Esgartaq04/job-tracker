"""Each user's own Claude API key: format check, verification, and sealed storage.

Everything that touches a key's plaintext goes through here, so there is one place to
audit. A key is never logged: the only identifier in a log line is the user's id.
"""

import logging
import uuid

import anthropic
from sqlalchemy import update
from sqlalchemy.orm import Session

from src.core import crypto, redact
from src.models.user_ai_key import UserAIKey
from src.models.util import utcnow

logger = logging.getLogger(__name__)

_MIN_LENGTH, _MAX_LENGTH = 20, 300

_BAD_FORMAT = "That doesn't look like a Claude API key. It should start with sk-ant-."
_NOT_ACCEPTED = "Claude didn't accept this key."
_CANT_CHECK = "Couldn't check this key with Claude. Try again."


class KeyFormatError(ValueError):
    """The input isn't shaped like a Claude key. The message is safe to show the user."""


class KeyNotAccepted(Exception):
    """Claude answered the key with an authentication or permission error."""


class KeyCheckFailed(Exception):
    """The key couldn't be checked: Claude was unreachable, slow, or erroring."""


def normalize(raw: str) -> str:
    """Trim paste whitespace and check the key looks like a Claude key, before spending a
    network call on it. Raises `KeyFormatError` without echoing the input."""
    key = raw.strip()
    # Only the log redactor's alphabet gets through. A key with other characters in it (a
    # control character, a dot) wouldn't match the redactor's pattern, so it could carry
    # past it in an error trace.
    if not _MIN_LENGTH <= len(key) <= _MAX_LENGTH or not redact.KEY_PATTERN.fullmatch(key):
        raise KeyFormatError(_BAD_FORMAT)
    return key


def hint_for(api_key: str) -> str:
    return "…" + api_key[-4:]


def get_row(db: Session, user_id: uuid.UUID) -> UserAIKey | None:
    return db.get(UserAIKey, user_id)


def read_key(db: Session, user_id: uuid.UUID) -> str | None:
    """The user's plaintext key, or None when there's no row or it can't be opened (a
    changed `AI_KEY_SECRET`, tampering). Unreadable is treated as missing: the user
    re-enters it. Ignores `status`; deciding what a rejected key means is the caller's."""
    row = get_row(db, user_id)
    return None if row is None else open_key(row)


#: Users whose stored key was reported unreadable. It stays unreadable until they save a
#: new one, and every page load asks, so this process says so once per user.
_reported_unreadable: set[uuid.UUID] = set()


def open_key(row: UserAIKey) -> str | None:
    """`row`'s plaintext key, or None when it can't be opened. `read_key` for a caller
    that already has the row."""
    try:
        return crypto.open_sealed(row.user_id, row.ciphertext)
    except crypto.SealError:
        if row.user_id not in _reported_unreadable:
            _reported_unreadable.add(row.user_id)
            logger.warning("stored AI key for %s can't be opened", row.user_id)
        return None


def save_key(db: Session, user_id: uuid.UUID, api_key: str) -> UserAIKey:
    """Seal and store `api_key`, replacing any earlier one and clearing `rejected`. The
    caller has just verified it. Flushes; the caller commits."""
    now = utcnow()
    row = get_row(db, user_id)
    if row is None:
        row = UserAIKey(user_id=user_id, created_at=now)
        db.add(row)
    row.ciphertext = crypto.seal(user_id, api_key)
    row.hint = hint_for(api_key)
    row.status = "ok"
    row.verified_at = now
    row.updated_at = now
    db.flush()
    return row


def delete_key(db: Session, user_id: uuid.UUID) -> None:
    row = get_row(db, user_id)
    if row is not None:
        db.delete(row)
        db.flush()


def mark_rejected(db: Session, user_id: uuid.UUID, ciphertext: str | None = None) -> None:
    """Record that Claude refused this user's saved key, and commit `db`.

    With `ciphertext`, only while the row still holds that sealed key: a call that loaded
    the key before the user replaced it must not reject the replacement. The check is in
    the UPDATE itself, against the table rather than this session's copy of the row,
    which can predate a save made by another request.

    The commit is deliberate and takes the caller's pending work with it (the `LLMCall`
    row for the attempt, which did happen), whether or not the row matched. It runs on
    the caller's session because a second connection would block on SQLite's write lock,
    which that session already holds once `reserve_call` has flushed."""
    query = update(UserAIKey).where(UserAIKey.user_id == user_id)
    if ciphertext is not None:
        query = query.where(UserAIKey.ciphertext == ciphertext)
    db.execute(query.values(status="rejected"), execution_options={"synchronize_session": False})
    # This session's copy may be stale either way; the next read reloads it.
    cached = db.identity_map.get(db.identity_key(UserAIKey, user_id))
    if cached is not None:
        db.expire(cached)
    db.commit()


def _models_list(api_key: str) -> None:
    """The one call `verify` makes. It costs no tokens, and Claude checks the key before
    anything else. A seam so tests don't reach the network."""
    with anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=10) as client:
        client.models.list(limit=1)


def verify(api_key: str) -> None:
    """Ask Claude whether it accepts `api_key`. Raises `KeyNotAccepted` when it refuses
    and `KeyCheckFailed` when it can't tell."""
    try:
        _models_list(api_key)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise KeyNotAccepted(_NOT_ACCEPTED) from exc
    except anthropic.APIError as exc:
        raise KeyCheckFailed(_CANT_CHECK) from exc
