"""Sealing for the Claude API key each user saves.

The key is sealed with AES-256-GCM before it touches the database. The AES key is derived
from `AI_KEY_SECRET`, and the user's id is bound in as associated data, so a sealed value
copied onto another user's row won't open. Losing the secret orphans every saved key: users
re-enter theirs, nothing else breaks.
"""

import base64
import logging
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.core.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "v1:"
_NONCE_BYTES = 12
_HKDF_INFO = b"job-tracker ai-key v1"
_LOCAL_FALLBACK_SECRET = "job-tracker-local-dev-only"

_warned_about_fallback = False


class SealError(Exception):
    """A sealed value that can't be opened: wrong format, wrong user, wrong secret, or
    tampered with. Deliberately says nothing about which."""


def check_configured() -> None:
    """Refuse to boot a deployed process that would seal keys with the public fallback."""
    if settings.environment != "local" and not settings.ai_key_secret:
        raise RuntimeError("AI_KEY_SECRET must be set outside local development")


def _secret() -> str:
    global _warned_about_fallback
    if settings.ai_key_secret:
        return settings.ai_key_secret
    if not _warned_about_fallback:
        logger.warning("AI_KEY_SECRET is not set; using the local development fallback")
        _warned_about_fallback = True
    return _LOCAL_FALLBACK_SECRET


def _aes_key() -> bytes:
    # Derived per call: it's cheap, and it keeps a changed secret effective immediately.
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(
        _secret().encode()
    )


def seal(user_id: uuid.UUID, plaintext: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_aes_key()).encrypt(nonce, plaintext.encode(), user_id.bytes)
    return _PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode()


def open_sealed(user_id: uuid.UUID, envelope: str) -> str:
    if not envelope.startswith(_PREFIX):
        raise SealError("unrecognized envelope")
    try:
        raw = base64.b64decode(envelope[len(_PREFIX) :], altchars=b"-_", validate=True)
        nonce, ciphertext = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        return AESGCM(_aes_key()).decrypt(nonce, ciphertext, user_id.bytes).decode()
    except (ValueError, InvalidTag) as exc:  # bad base64, short nonce, bad tag, bad utf-8
        raise SealError("could not open the sealed value") from exc
