import uuid

from pydantic import BaseModel, Field

from src.models.enums import IngestStatus
from src.schemas.application import ApplicationDetailOut


class IngestRequest(BaseModel):
    url: str
    mark_as_applied: bool = False


class IngestBatchRequest(BaseModel):
    """Multi-line paste in the quick-add bar (README §7.2)."""

    urls: list[str] = Field(min_length=1, max_length=50)
    mark_as_applied: bool = False


class DomHints(BaseModel):
    """What the extension could read off the rendered page. Hints only: the tiers still
    run, and a stale selector degrades to "no hint" rather than to a wrong record."""

    title: str | None = None
    company: str | None = None
    location: str | None = None


class IngestFromDomRequest(BaseModel):
    """Browser-extension path for sites that block server-side fetching (README §4.1)."""

    url: str
    html: str
    hints: DomHints | None = None
    #: Visible text, in case the HTML is too exotic for the readability pass.
    fallback_text: str | None = None
    mark_as_applied: bool = False


class IngestFromTextRequest(BaseModel):
    """Tier 5 — the manual fallback that is always reachable."""

    text: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    mark_as_applied: bool = False


class IngestAccepted(BaseModel):
    application_id: uuid.UUID
    ingest_status: IngestStatus
    duplicate: bool = False


class IngestBatchAccepted(BaseModel):
    accepted: list[IngestAccepted]


class IngestFromDomOut(ApplicationDetailOut):
    """The card the extension's save landed on. `duplicate` says it was already on the
    board, so the popup can say so — a URL that matched the wrong card used to look
    exactly like a successful save."""

    duplicate: bool = False
