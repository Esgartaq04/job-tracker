"""Everything the AI features share: the client, the per-user monthly cap, and how a
resume gets into a request.

Four features call a model — Tier 4 extraction, description clean-up, cover letters,
and the extension's autofill — and each degrades the same two ways: no key (the
feature is off) or the user's monthly cap is spent (README §8.3). Keeping both here
means a new feature can't forget the cap.
"""

import base64
import io
import logging
import os
import uuid
import zipfile
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.llm_call import LLMCall

logger = logging.getLogger(__name__)

#: Well past any real resume, well short of what a free instance wants in memory.
MAX_RESUME_BYTES = 5 * 1024 * 1024


class AIUnavailable(RuntimeError):
    """No API key, or the `anthropic` package isn't installed."""


class AIQuotaExceeded(RuntimeError):
    """This user has spent `llm_monthly_call_cap` calls this month."""


class AIFailed(RuntimeError):
    """The model answered, but not with something usable (a refusal, an empty reply)."""


class ResumeRejected(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def enabled() -> bool:
    return bool(settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))


def client():
    """An Anthropic client, or `AIUnavailable` saying why there isn't one."""
    if not enabled():
        raise AIUnavailable("AI features are off: no ANTHROPIC_API_KEY is configured.")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise AIUnavailable("AI features are off: the anthropic package isn't installed.") from exc
    return anthropic.Anthropic(api_key=settings.anthropic_api_key or None)


def is_sdk_error(exc: Exception) -> bool:
    """An error from the API itself: rate limits, overload, timeouts, bad requests."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover - optional dependency
        return False
    return isinstance(exc, anthropic.APIError)


def _month_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def calls_this_month(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(LLMCall)
            .where(LLMCall.user_id == user_id, LLMCall.created_at >= _month_start())
        )
        or 0
    )


def under_cap(db: Session, user_id: uuid.UUID) -> bool:
    return calls_this_month(db, user_id) < settings.llm_monthly_call_cap


def reserve_call(db: Session, user_id: uuid.UUID, kind: str) -> None:
    """Count a call before making it. Raises when the cap is spent, so a feature
    degrades to its no-AI path instead of running up a bill."""
    if not under_cap(db, user_id):
        raise AIQuotaExceeded(
            f"You've used this month's {settings.llm_monthly_call_cap} AI calls. "
            "They reset on the 1st."
        )
    db.add(LLMCall(user_id=user_id, kind=kind))
    db.flush()


def record_call(db: Session, user_id: uuid.UUID, kind: str) -> None:
    """Count a call that already happened (Tier 4 runs inside the pure pipeline)."""
    db.add(LLMCall(user_id=user_id, kind=kind))


def resume_content(data: bytes, filename: str | None = None) -> list[dict]:
    """Content blocks that put a resume in front of the model.

    A PDF goes in as a document block: the model reads its layout directly, so no PDF
    parser is needed here. A DOCX is unpacked to text. Nothing is written anywhere —
    the bytes live for the length of one request.
    """
    if not data:
        raise ResumeRejected(422, "The resume file is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise ResumeRejected(413, "That resume is over 5 MB. Export a smaller PDF and try again.")

    if data.startswith(b"%PDF"):
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
                "title": filename or "resume.pdf",
            }
        ]

    if _is_docx(data):
        text = docx_text(data)
        if not text.strip():
            raise ResumeRejected(422, "That Word file has no text in it.")
        return [{"type": "text", "text": f"<resume>\n{text}\n</resume>"}]

    raise ResumeRejected(415, "Upload your resume as a PDF or a Word (.docx) file.")


def _is_docx(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def docx_text(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    lines = [paragraph.text for paragraph in document.paragraphs]
    # Resumes love tables for layout; their text matters as much as the paragraphs'.
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(dict.fromkeys(cells)))
    return "\n".join(line for line in lines if line.strip())


def response_text(response) -> str:
    """The text of a Messages API response, after checking it actually finished."""
    if getattr(response, "stop_reason", None) == "refusal":
        raise AIFailed("The AI declined this request.")
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise AIFailed("The AI returned an empty reply. Try again.")
    return text
