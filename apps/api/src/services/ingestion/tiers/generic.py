"""Tier 2 — generic HTML: readability-style main content plus og:/<title> metadata."""

import re

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import ATSAdapter
from src.services.ingestion.html import html_to_markdown, main_content_html, meta_fields
from src.services.ingestion.normalize import company_guess_from_url, host_of, registrable_domain

#: "Backend Engineering Intern at Datadog | Greenhouse" → title / company.
_TITLE_SPLIT = re.compile(r"\s+[-–—|·]\s+|\s+\bat\b\s+", re.I)

#: LinkedIn's title format, which carries all three fields we want:
#: "Ramp hiring Software Engineer Intern in New York, NY".
_HIRING_PATTERN = re.compile(
    r"^(?P<company>.{2,60}?)\s+hiring\s+(?P<title>.{2,120}?)(?:\s+in\s+(?P<location>.{2,80}))?$",
    re.I,
)

_BOARD_WORDS = {
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "smartrecruiters",
    "linkedin",
    "indeed",
    "glassdoor",
    "ziprecruiter",
    "monster",
    "dice",
    "careers",
    "jobs",
    "job board",
    "job application",
    "apply",
}


def _is_board_name(candidate: str | None, url: str) -> bool:
    """True when the "company" is really the site we're reading.

    The explicit list catches the well-known boards; the hostname check catches the
    rest without needing the list to keep growing — a page served by `acme-jobs.com`
    calling itself "Acme Jobs" is the board talking about itself, not the employer.
    """
    if not candidate:
        return False
    normalized = candidate.strip().lower()
    if normalized in _BOARD_WORDS:
        return True

    domain = registrable_domain(host_of(url)) or ""
    brand = domain.split(".")[0]
    if not brand or len(brand) < 4:
        return False
    squashed = re.sub(r"[^a-z0-9]", "", normalized)
    return bool(squashed) and (squashed == brand or squashed.startswith(brand))


#: A trailing " | LinkedIn" / " - Indeed.com" site stamp on the <title>.
_SITE_SUFFIX = re.compile(r"^(?P<head>.+?)\s+[|·–—-]\s+(?P<tail>[^|·–—-]{2,40})$")


def _strip_site_suffix(raw: str, url: str) -> str:
    """Drop the site's own name off the end of a <title>, so it can't be mistaken for
    part of the location or the company."""
    match = _SITE_SUFFIX.match(raw)
    if match and _is_board_name(match.group("tail"), url):
        return match.group("head").strip()
    return raw


def _split_title(raw: str | None, url: str) -> tuple[str | None, str | None, str | None]:
    """→ (title, company, location). Only LinkedIn-style titles carry a location."""
    if not raw:
        return None, None, None

    raw = _strip_site_suffix(raw.strip(), url)
    hiring = _HIRING_PATTERN.match(raw.strip())
    if hiring:
        return (
            hiring.group("title").strip(),
            hiring.group("company").strip(),
            (hiring.group("location") or "").strip() or None,
        )

    parts = [part.strip() for part in _TITLE_SPLIT.split(raw) if part.strip()]
    if not parts:
        return None, None, None

    title = parts[0]
    company = next(
        (candidate for candidate in parts[1:] if not _is_board_name(candidate, url)), None
    )
    return title or None, company, None


def extract(html: str, url: str) -> ExtractedPosting | None:
    meta = meta_fields(html)
    content_html = main_content_html(html)
    description = html_to_markdown(content_html)

    raw_title = meta.get("og:title") or meta.get("twitter:title") or meta.get("title")
    title, company_from_title, location_from_title = _split_title(raw_title, url)

    site_name = meta.get("og:site_name")
    company = next(
        (
            candidate
            for candidate in (site_name, company_from_title, company_guess_from_url(url))
            if candidate and not _is_board_name(candidate, url)
        ),
        None,
    )

    location = meta.get("og:locality") or meta.get("job:location") or location_from_title

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
