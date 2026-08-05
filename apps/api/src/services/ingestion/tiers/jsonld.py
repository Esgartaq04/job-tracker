"""Tier 0 — schema.org JobPosting in <script type="application/ld+json">.

Free, fast, and common because it drives Google Jobs indexing (README §4.1).
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from selectolax.parser import HTMLParser

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import ATSAdapter
from src.services.ingestion.html import html_to_markdown

logger = logging.getLogger(__name__)

_EMPLOYMENT_MAP = {
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "FULL_TIME": "full_time",
    "FULLTIME": "full_time",
    "PART_TIME": None,
    "CONTRACTOR": "contract",
    "CONTRACT": "contract",
    "TEMPORARY": "contract",
}
_PERIOD_MAP = {
    "HOUR": "hourly",
    "HOURLY": "hourly",
    "MONTH": "monthly",
    "MONTHLY": "monthly",
    "YEAR": "yearly",
    "YEARLY": "yearly",
    "ANNUAL": "yearly",
}


def iter_json_ld(html: str):
    for node in HTMLParser(html).css('script[type="application/ld+json"]'):
        raw = node.text()
        if not raw or not raw.strip():
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            # Some sites emit trailing commas or concatenated objects; try the first
            # balanced object rather than giving up on the tier.
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                continue
            try:
                yield json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.debug("unparseable ld+json block")


def _flatten(payload: Any):
    if isinstance(payload, list):
        for item in payload:
            yield from _flatten(item)
    elif isinstance(payload, dict):
        if "@graph" in payload:
            yield from _flatten(payload["@graph"])
        else:
            yield payload


def find_job_posting(html: str) -> dict | None:
    for block in iter_json_ld(html):
        for node in _flatten(block):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(t).lower() == "jobposting" for t in types if t):
                return node
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("value"))
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        joined = ", ".join(part for part in parts if part)
        return joined or None
    return str(value)


def _location(node: dict) -> str | None:
    job_location = node.get("jobLocation")
    entries = job_location if isinstance(job_location, list) else [job_location]
    labels: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            label = _text(entry)
            if label:
                labels.append(label)
            continue
        address = entry.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry")
                if isinstance(address.get("addressCountry"), str)
                else _text(address.get("addressCountry")),
            ]
            label = ", ".join(part for part in parts if part)
        else:
            label = _text(address) or _text(entry.get("name"))
        if label:
            labels.append(label)
    return "; ".join(dict.fromkeys(labels)) or None


def _salary(node: dict) -> dict:
    base = node.get("baseSalary")
    if not isinstance(base, dict):
        return {}
    value = base.get("value")
    if not isinstance(value, dict):
        return {}
    minimum = value.get("minValue") or value.get("value")
    maximum = value.get("maxValue") or value.get("value")

    def _number(candidate) -> float | None:
        try:
            return float(candidate)
        except (TypeError, ValueError):
            return None

    return {
        "salary_min": _number(minimum),
        "salary_max": _number(maximum),
        "salary_currency": (base.get("currency") or value.get("currency") or None),
        "salary_period": _PERIOD_MAP.get(str(value.get("unitText") or "").upper()),
    }


def _posted_at(node: dict) -> datetime | None:
    raw = node.get("datePosted")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract(html: str) -> ExtractedPosting | None:
    node = find_job_posting(html)
    if node is None:
        return None

    description_html = node.get("description") if isinstance(node.get("description"), str) else None
    description_markdown = html_to_markdown(description_html) if description_html else None

    employment_raw = node.get("employmentType")
    employment_key = (
        str(
            employment_raw[0]
            if isinstance(employment_raw, list) and employment_raw
            else employment_raw or ""
        )
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )

    title = _text(node.get("title"))
    location = _location(node)
    remote = node.get("jobLocationType") == "TELECOMMUTE" or None

    posting = ExtractedPosting(
        company=_text(node.get("hiringOrganization")),
        title=title,
        location=location,
        is_remote=remote if remote else ATSAdapter.detect_remote(location, description_markdown),
        employment_type=_EMPLOYMENT_MAP.get(employment_key)
        or ATSAdapter.guess_employment_type(title),
        req_id=_text(node.get("identifier")),
        posted_at=_posted_at(node),
        description_markdown=description_markdown,
        description_html=description_html,
        confidence=0.95,
        **_salary(node),
    )
    return posting if posting.is_useful else None
