import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import AppStatus, EventSource, IngestStatus


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str | None = None


class StatusEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: AppStatus | None
    to_status: AppStatus
    occurred_at: datetime
    source: EventSource
    confidence: float | None = None
    note: str | None = None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_url: str
    canonical_url: str
    source_host: str | None = None
    ats_vendor: str | None = None

    company: str | None = None
    company_domain: str | None = None
    title: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    employment_type: str | None = None
    req_id: str | None = None

    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None

    description: str | None = None
    description_raw: str | None = None
    description_user: str | None = None
    extraction_meta: dict = Field(default_factory=dict)

    status: AppStatus
    board_position: float
    saved_at: datetime
    applied_at: datetime | None = None
    posted_at: datetime | None = None
    closed_at: datetime | None = None
    next_action_at: datetime | None = None
    priority: int = 0

    ingest_status: IngestStatus
    notes: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    tags: list[TagOut] = Field(default_factory=list)

    # Derived, board-facing fields (README §2, §7.1).
    days_since_applied: int | None = None
    days_since_saved: int | None = None
    staleness: str | None = None  # none | warn | dim


class ApplicationDetailOut(ApplicationOut):
    events: list[StatusEventOut] = Field(default_factory=list)


class ApplicationCreate(BaseModel):
    """Fully manual create (README §6). URL optional — typed-in applications are the
    Phase 1 path and must not be blocked on having a posting link."""

    source_url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    employment_type: str | None = None
    description: str | None = None
    notes: str | None = None
    status: AppStatus = AppStatus.saved
    applied_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class ApplicationUpdate(BaseModel):
    company: str | None = None
    company_domain: str | None = None
    title: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    employment_type: str | None = None
    req_id: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    description_user: str | None = None
    notes: str | None = None
    status: AppStatus | None = None
    applied_at: datetime | None = None
    posted_at: datetime | None = None
    next_action_at: datetime | None = None
    priority: int | None = None
    tags: list[str] | None = None


class MoveRequest(BaseModel):
    """Client sends neighbour ids, never a computed position — the server owns
    ranking so two tabs cannot disagree (README §6)."""

    to_status: AppStatus
    before_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None
    note: str | None = None


class NoteCreate(BaseModel):
    text: str


class BoardColumn(BaseModel):
    status: AppStatus
    count: int
    items: list[ApplicationOut]


class BoardOut(BaseModel):
    columns: list[BoardColumn]


class PageOut(BaseModel):
    items: list[ApplicationOut]
    next_cursor: str | None = None
    total: int


class ImportSkipped(BaseModel):
    line: int
    reason: str


class ImportReportOut(BaseModel):
    """What the import did — including, explicitly, what it refused to guess at."""

    summary: str
    created: int
    duplicates: int
    skipped: list[ImportSkipped] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
