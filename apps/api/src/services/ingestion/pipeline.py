"""The tiered ingestion pipeline (README §4.1).

Tiers are attempted cheapest-first and the first useful result wins; later tiers
still run when the winner left holes (a JSON-LD block with no description, say),
and `ExtractedPosting.merge` fills them without overwriting what we already have.

One deliberate deviation from the doc's numbering: when a known-ATS adapter matches
the hostname we run it *before* fetching the page at all. The adapter hits a JSON API
that is both cheaper and more reliable than the HTML the JSON-LD tier would parse, so
fetching first would spend a request to lose a race we already know the answer to.

The record is never blocked on any of this: whatever the tiers produce, the card keeps
its URL, its guessed company, and the always-reachable manual fallback (Tier 5).
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import time as time_of_day

from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import Application, IngestJob, IngestStatus
from src.models.util import utcnow
from src.schemas.extraction import ExtractedPosting
from src.services import events
from src.services.applications import to_out
from src.services.ingestion import html as html_utils
from src.services.ingestion.adapters import AdapterError, find_adapter
from src.services.ingestion.fetch import FetchError, fetch_url
from src.services.ingestion.normalize import company_domain_for, company_guess_from_url, host_of
from src.services.ingestion.tiers import browser, generic, jsonld, llm

logger = logging.getLogger(__name__)


@dataclass
class IngestOutcome:
    posting: ExtractedPosting | None = None
    tiers_attempted: list[str] = field(default_factory=list)
    tier_succeeded: str | None = None
    error: str | None = None
    ats_vendor: str | None = None
    duration_ms: int = 0

    @property
    def status(self) -> IngestStatus:
        """`failed` means we learned nothing at all — the card still exists, it just
        needs the user (README §4.1, Tier 5). Anything less than company + title +
        description is `partial`, which is what turns the card amber."""
        posting = self.posting
        if posting is None or not (posting.title or posting.description_markdown):
            return IngestStatus.failed
        if posting.company and posting.title and posting.description_markdown:
            return IngestStatus.ok
        return IngestStatus.partial


def run_pipeline(
    url: str,
    *,
    html: str | None = None,
    text: str | None = None,
) -> IngestOutcome:
    """Pure extraction: no database, no side effects. `html` short-circuits the
    fetch (browser extension), `text` short-circuits everything (manual paste)."""
    started = time.perf_counter()
    outcome = IngestOutcome()

    def finish() -> IngestOutcome:
        outcome.duration_ms = int((time.perf_counter() - started) * 1000)
        return outcome

    def absorb(tier: str, candidate: ExtractedPosting | None) -> bool:
        """Record a tier attempt; returns True once we have everything we want."""
        outcome.tiers_attempted.append(tier)
        if candidate is None:
            return False
        outcome.posting = candidate if outcome.posting is None else outcome.posting.merge(candidate)
        if outcome.tier_succeeded is None and candidate.is_useful:
            outcome.tier_succeeded = tier
        return bool(
            outcome.posting.is_useful
            and outcome.posting.description_markdown
            and outcome.posting.company
        )

    # ── Tier 5 short-circuit: the user pasted the text themselves ─────────
    if text:
        cleaned = text.strip()
        absorb(
            "manual",
            ExtractedPosting(
                description_markdown=cleaned,
                company=company_guess_from_url(url) if url else None,
                confidence=1.0,
            ),
        )
        # The user typed it, so it counts as a success even without a parsed title.
        outcome.tier_succeeded = "manual"
        if llm.enabled() and outcome.posting and not outcome.posting.title:
            absorb("llm", llm.extract(cleaned, url=url))
        return finish()

    # ── Tier 1: known-host adapter ────────────────────────────────────────
    if html is None:
        adapter = find_adapter(url)
        if adapter is not None:
            outcome.ats_vendor = adapter.vendor
            try:
                if absorb(f"ats:{adapter.vendor}", adapter.fetch(url)):
                    return finish()
            except AdapterError as exc:
                outcome.error = f"{adapter.vendor}: {exc}"
                logger.info("adapter %s failed for %s: %s", adapter.vendor, url, exc)

    # ── Fetch once, then run the HTML tiers over the same document ────────
    page_html = html
    if page_html is None:
        try:
            raw = fetch_url(url)
            page_html = raw.html
            if raw.json_payload is not None and page_html is None:
                outcome.error = "response was JSON, not a job posting page"
        except FetchError as exc:
            outcome.error = str(exc)
            logger.info("fetch failed for %s: %s", url, exc)

    if page_html:
        if absorb("jsonld", jsonld.extract(page_html)):
            return finish()
        if absorb("generic", generic.extract(page_html, url)):
            return finish()

    # ── Tier 3: headless browser for JS-rendered pages ────────────────────
    if browser.enabled() and (not page_html or not _looks_complete(outcome.posting)):
        rendered = browser.render(url)
        outcome.tiers_attempted.append("browser")
        if rendered:
            page_html = rendered
            if absorb("jsonld-browser", jsonld.extract(rendered)):
                return finish()
            if absorb("generic-browser", generic.extract(rendered, url)):
                return finish()

    # ── Tier 4: LLM structuring over the cleaned text ─────────────────────
    if page_html and llm.enabled() and not _looks_complete(outcome.posting):
        cleaned = html_utils.html_to_text(html_utils.main_content_html(page_html))
        absorb("llm", llm.extract(cleaned, url=url))

    if outcome.posting is None and outcome.error is None:
        outcome.error = "no tier produced a usable posting"
    return finish()


def _looks_complete(posting: ExtractedPosting | None) -> bool:
    return bool(posting and posting.is_useful and posting.company and posting.description_markdown)


def ingest_application(db: Session, application_id: uuid.UUID) -> IngestOutcome:
    """Run the pipeline for a stored application, persist the result, record
    telemetry, and stream progress to the user's board."""
    application = db.get(Application, application_id)
    if application is None:
        raise ValueError(f"unknown application {application_id}")

    user_id = application.user_id
    events.publish(
        user_id,
        "ingest.started",
        {"application_id": str(application.id), "url": application.source_url},
    )

    outcome = run_pipeline(application.source_url)
    apply_outcome(db, application, outcome)
    db.flush()

    db.add(
        IngestJob(
            application_id=application.id,
            url=application.source_url,
            tier_attempted=outcome.tiers_attempted,
            tier_succeeded=outcome.tier_succeeded,
            attempts=1,
            error=outcome.error,
            duration_ms=outcome.duration_ms,
        )
    )
    db.commit()

    events.publish(
        user_id,
        "ingest.completed" if outcome.status != IngestStatus.failed else "ingest.failed",
        {
            "application_id": str(application.id),
            "ingest_status": outcome.status.value,
            "tier": outcome.tier_succeeded,
            "error": outcome.error,
            "application": to_out(application).model_dump(mode="json"),
        },
    )
    return outcome


def apply_outcome(
    db: Session,
    application: Application,
    outcome: IngestOutcome,
    *,
    mark_manual: bool = False,
) -> Application:
    """Write extraction results onto an application without clobbering user edits."""
    posting = outcome.posting
    application.ingest_status = outcome.status
    application.source_host = application.source_host or host_of(application.source_url)
    application.ats_vendor = application.ats_vendor or outcome.ats_vendor
    application.company_domain = application.company_domain or company_domain_for(
        application.source_url
    )

    meta = dict(application.extraction_meta or {})
    # Placeholders written when the card was created ("Untitled", a company guessed
    # from the hostname) are not user edits — a real extraction is allowed to replace
    # them. Anything not listed here is either extracted or typed by the user, and wins.
    guessed = set(meta.get("guessed") or ())
    for placeholder in guessed:
        setattr(application, placeholder, None)

    meta.update(
        {
            "tiers_attempted": outcome.tiers_attempted,
            "tier": outcome.tier_succeeded,
            "duration_ms": outcome.duration_ms,
            "confidence": posting.confidence if posting else None,
            "needs_verification": bool(posting and posting.confidence < 0.6),
            "error": outcome.error,
            "extracted_at": utcnow().isoformat(),
            "manual": mark_manual,
        }
    )
    application.extraction_meta = meta

    if posting is None:
        # Degrade gracefully: keep the URL-derived label so the card is still readable
        # (README §4.1, mitigation 3), and keep it marked as a guess.
        application.company = application.company or company_guess_from_url(application.source_url)
        application.title = application.title or "Untitled"
        meta["guessed"] = sorted(guessed)
        application.extraction_meta = dict(meta)
        application.updated_at = utcnow()
        return application

    # Only fill blanks — the user's edits and any earlier, better tier win.
    application.company = (
        application.company or posting.company or company_guess_from_url(application.source_url)
    )
    application.title = application.title or posting.title or "Untitled"
    # Still a guess wherever extraction had nothing to offer.
    still_guessed = set()
    if not posting.company:
        still_guessed.add("company")
    if not posting.title:
        still_guessed.add("title")
    meta["guessed"] = sorted(still_guessed & guessed)
    application.location = application.location or posting.location
    if application.is_remote is None:
        application.is_remote = posting.is_remote
    application.employment_type = application.employment_type or posting.employment_type
    application.req_id = application.req_id or posting.req_id
    application.salary_min = application.salary_min or posting.salary_min
    application.salary_max = application.salary_max or posting.salary_max
    application.salary_currency = application.salary_currency or posting.salary_currency
    application.salary_period = application.salary_period or posting.salary_period

    if posting.posted_at and application.posted_at is None:
        posted = posting.posted_at
        application.posted_at = (
            posted
            if isinstance(posted, datetime)
            else datetime.combine(posted, time_of_day.min, tzinfo=UTC)
        )

    # `description_raw` is immutable once written — the archived copy is often the
    # only remaining record of a posting by interview time (README §4.1).
    if posting.description_markdown and not application.description_raw:
        application.description_raw = posting.description_markdown[: settings.max_description_chars]
    if posting.description_html and not application.description_html:
        application.description_html = posting.description_html[: settings.max_description_chars]
    if posting.required_skills:
        meta["required_skills"] = posting.required_skills
        application.extraction_meta = dict(meta)

    application.updated_at = utcnow()
    return application
