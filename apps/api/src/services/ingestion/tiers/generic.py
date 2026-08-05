"""Tier 2 — generic HTML: readability-style main content plus og:/<title> metadata."""

import re

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import ATSAdapter
from src.services.ingestion.html import html_to_markdown, main_content_html, meta_fields
from src.services.ingestion.normalize import company_guess_from_url

#: "Backend Engineering Intern at Datadog | Greenhouse" → title / company.
_TITLE_SPLIT = re.compile(r"\s+[-–—|·]\s+|\s+\bat\b\s+", re.I)

_BOARD_WORDS = {
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "smartrecruiters",
    "careers",
    "jobs",
    "job board",
    "job application",
    "apply",
}


def _split_title(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    parts = [part.strip() for part in _TITLE_SPLIT.split(raw) if part.strip()]
    if not parts:
        return None, None
    title = parts[0]
    company = None
    for candidate in parts[1:]:
        if candidate.lower() in _BOARD_WORDS:
            continue
        company = candidate
        break
    return title or None, company


def extract(html: str, url: str) -> ExtractedPosting | None:
    meta = meta_fields(html)
    content_html = main_content_html(html)
    description = html_to_markdown(content_html)

    raw_title = meta.get("og:title") or meta.get("twitter:title") or meta.get("title")
    title, company_from_title = _split_title(raw_title)

    company = meta.get("og:site_name") or company_from_title or company_guess_from_url(url)
    if company and company.lower() in _BOARD_WORDS:
        company = company_from_title or company_guess_from_url(url)

    location = meta.get("og:locality") or meta.get("job:location")

    posting = ExtractedPosting(
        company=company,
        title=title,
        location=location,
        is_remote=ATSAdapter.detect_remote(location, description),
        employment_type=ATSAdapter.guess_employment_type(title, description[:2000] or None),
        description_markdown=description or None,
        description_html=content_html or None,
        # Metadata scraping guesses; the UI marks sub-0.6 fields for verification.
        confidence=0.55,
    )
    # A page that yields a title but three lines of text is a cookie wall, not a posting.
    if posting.title and len(description) < 200:
        posting.confidence = 0.3
    return posting if (posting.title or description) else None
