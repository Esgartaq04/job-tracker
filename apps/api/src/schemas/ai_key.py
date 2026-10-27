from datetime import datetime
from typing import Literal

from pydantic import BaseModel, SecretStr


class AIKeyIn(BaseModel):
    # A SecretStr so the key never shows in a repr or a log line. No constraints on it:
    # pydantic can echo the raw input back in a 422 body when one fails, so the key's shape
    # and length are checked by `ai_keys.normalize`, whose error never repeats the input.
    api_key: SecretStr


class AIKeyOut(BaseModel):
    """Whether a key is saved and how to recognise it. Never the key itself."""

    has_key: bool
    #: "…" plus the key's last four characters.
    hint: str | None = None
    #: `rejected` means Claude refused the saved key on a real call; the user replaces it.
    status: Literal["ok", "rejected"] | None = None
    updated_at: datetime | None = None
