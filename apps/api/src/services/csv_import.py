"""CSV import (README §10, Phase 3).

Most people already track applications in a spreadsheet, so the first thing they want
from this app is their history in it — a board that starts empty is a board they abandon.

The parser is forgiving on purpose: headers vary wildly between the spreadsheet
templates people copy from each other, and a strict importer just means the file gets
rejected and the user gives up. What it refuses to do is guess about *identity* — a row
without a company or a title is skipped and reported, never invented.
"""

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from src.models import Application, AppStatus, IngestStatus
from src.models.util import utcnow
from src.services import ranking
from src.services.applications import resolve_tags, user_applications
from src.services.ingestion.normalize import canonicalize, company_domain_for, host_of
from src.services.transitions import record_initial_event

#: Header synonyms, normalised to lowercase with punctuation stripped.
COLUMN_ALIASES: dict[str, str] = {
    "company": "company",
    "employer": "company",
    "organization": "company",
    "organisation": "company",
    "companyname": "company",
    "title": "title",
    "role": "title",
    "position": "title",
    "jobtitle": "title",
    "url": "source_url",
    "link": "source_url",
    "joburl": "source_url",
    "joblink": "source_url",
    "postingurl": "source_url",
    "posting": "source_url",
    "status": "status",
    "stage": "status",
    "location": "location",
    "city": "location",
    "notes": "notes",
    "note": "notes",
    "comments": "notes",
    "tags": "tags",
    "labels": "tags",
    "dateapplied": "applied_at",
    "applieddate": "applied_at",
    "appliedon": "applied_at",
    "applied": "applied_at",
    "datesaved": "saved_at",
    "date": "saved_at",
}

#: Free-text status values people actually write, mapped onto the enum.
STATUS_ALIASES: dict[str, AppStatus] = {
    "saved": AppStatus.saved,
    "bookmarked": AppStatus.saved,
    "wishlist": AppStatus.saved,
    "tosubmit": AppStatus.saved,
    "applied": AppStatus.applied,
    "submitted": AppStatus.applied,
    "inprogress": AppStatus.applied,
    "oa": AppStatus.oa,
    "onlineassessment": AppStatus.oa,
    "assessment": AppStatus.oa,
    "codingchallenge": AppStatus.oa,
    "hackerrank": AppStatus.oa,
    "phonescreen": AppStatus.phone_screen,
    "recruiterscreen": AppStatus.phone_screen,
    "screen": AppStatus.phone_screen,
    "interview": AppStatus.interview,
    "technical": AppStatus.interview,
    "onsite": AppStatus.final,
    "final": AppStatus.final,
    "finalround": AppStatus.final,
    "superday": AppStatus.final,
    "offer": AppStatus.offer,
    "accepted": AppStatus.offer,
    "rejected": AppStatus.rejected,
    "rejection": AppStatus.rejected,
    "declined": AppStatus.rejected,
    "no": AppStatus.rejected,
    "withdrawn": AppStatus.withdrawn,
    "withdrew": AppStatus.withdrawn,
    "ghosted": AppStatus.ghosted,
    "noresponse": AppStatus.ghosted,
}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%d %b %Y",
    "%B %d, %Y",
)


@dataclass
class ImportReport:
    created: int = 0
    duplicates: int = 0
    skipped: list[dict] = field(default_factory=list)
    unmapped_columns: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{self.created} imported"]
        if self.duplicates:
            parts.append(f"{self.duplicates} already tracked")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        return ", ".join(parts)


def _normalize_header(header: str) -> str:
    return "".join(character for character in header.lower() if character.isalnum())


def _parse_date(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=utcnow().tzinfo)
        except ValueError:
            continue
    try:  # ISO with time, which is what our own export writes
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_status(value: str) -> AppStatus | None:
    key = "".join(character for character in (value or "").lower() if character.isalnum())
    if not key:
        return None
    return STATUS_ALIASES.get(key)


def import_csv(db: Session, user_id: uuid.UUID, content: bytes) -> ImportReport:
    """Create applications from a CSV. Rows that can't be identified are reported,
    not guessed at; rows already on the board are counted as duplicates."""
    report = ImportReport()

    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return report

    mapping = {
        original: COLUMN_ALIASES.get(_normalize_header(original))
        for original in reader.fieldnames
        if original
    }
    report.unmapped_columns = sorted(
        original for original, mapped in mapping.items() if mapped is None
    )

    # One query rather than one per row: spreadsheets run to hundreds of lines.
    existing_urls = {
        row.canonical_url
        for row in db.scalars(user_applications(user_id)).unique().all()
        if row.canonical_url
    }
    existing_pairs = {
        ((row.company or "").strip().lower(), (row.title or "").strip().lower())
        for row in db.scalars(user_applications(user_id)).unique().all()
    }

    for line, raw_row in enumerate(reader, start=2):  # line 1 is the header
        row = {}
        for original, mapped in mapping.items():
            if mapped and raw_row.get(original) is not None:
                row[mapped] = (raw_row[original] or "").strip()

        company = row.get("company") or None
        title = row.get("title") or None
        source_url = row.get("source_url") or None

        if not company and not title:
            report.skipped.append({"line": line, "reason": "no company or title"})
            continue

        canonical = None
        if source_url:
            try:
                canonical = canonicalize(source_url)
            except ValueError:
                # A malformed URL isn't fatal — the rest of the row is still a record.
                source_url = None

        if canonical and canonical in existing_urls:
            report.duplicates += 1
            continue
        pair = ((company or "").lower(), (title or "").lower())
        if not canonical and pair in existing_pairs:
            report.duplicates += 1
            continue

        status = _parse_status(row.get("status", "")) or AppStatus.saved
        applied_at = _parse_date(row.get("applied_at", ""))
        saved_at = _parse_date(row.get("saved_at", "")) or applied_at or utcnow()

        # A row that records an application date is an application, whatever the
        # status column happened to say.
        if applied_at and status is AppStatus.saved:
            status = AppStatus.applied

        application = Application(
            user_id=user_id,
            source_url=source_url or f"import:{uuid.uuid4()}",
            canonical_url=canonical or f"import:{uuid.uuid4()}",
            source_host=host_of(source_url) if source_url else None,
            company_domain=company_domain_for(source_url) if source_url else None,
            company=company,
            title=title or "Untitled",
            location=row.get("location") or None,
            notes=row.get("notes") or None,
            status=status,
            saved_at=saved_at,
            applied_at=applied_at or (utcnow() if status is not AppStatus.saved else None),
            ingest_status=IngestStatus.partial if source_url else IngestStatus.ok,
            board_position=ranking.next_position(db, user_id, status),
        )

        tags = [tag.strip() for tag in (row.get("tags") or "").split(",") if tag.strip()]
        if tags:
            application.tags = resolve_tags(db, user_id, tags)

        db.add(application)
        db.flush()
        record_initial_event(db, application)

        if canonical:
            existing_urls.add(canonical)
        existing_pairs.add(pair)
        report.created += 1

    db.flush()
    return report
