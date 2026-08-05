"""Ashby — jobs.ashbyhq.com/{co}/{uuid} → public posting API."""

import re
from datetime import datetime
from urllib.parse import urlsplit

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import AdapterError, ATSAdapter
from src.services.ingestion.fetch import FetchError, fetch_json
from src.services.ingestion.normalize import _humanize, host_of, normalize_url

API = "https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true"
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class AshbyAdapter(ATSAdapter):
    vendor = "ashby"

    def matches(self, url: str) -> bool:
        return (host_of(url) or "") == "jobs.ashbyhq.com" and self._parse(url) is not None

    def _parse(self, url: str) -> tuple[str, str] | None:
        segments = [s for s in urlsplit(normalize_url(url)).path.split("/") if s]
        if len(segments) >= 2 and _UUID.match(segments[1]):
            return segments[0], segments[1]
        return None

    def fetch(self, url: str) -> ExtractedPosting:
        parsed = self._parse(url)
        if parsed is None:
            raise AdapterError("not an ashby posting URL")
        company_slug, posting_id = parsed

        try:
            payload = fetch_json(API.format(company=company_slug))
        except FetchError as exc:
            raise AdapterError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise AdapterError("unexpected ashby payload")

        job = next(
            (item for item in payload.get("jobs") or [] if item.get("id") == posting_id),
            None,
        )
        if job is None:
            raise AdapterError("posting not found on this ashby board")

        location = job.get("location")
        description_html = job.get("descriptionHtml")
        posted_at = None
        if job.get("publishedAt"):
            try:
                posted_at = datetime.fromisoformat(job["publishedAt"].replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        compensation = job.get("compensation") or {}
        summary = compensation.get("summaryComponents") or []
        salary_min = salary_max = None
        salary_currency = salary_period = None
        if summary:
            first = summary[0]
            salary_min = first.get("minValue")
            salary_max = first.get("maxValue")
            salary_currency = first.get("currencyCode")
            interval = (first.get("interval") or "").lower()
            salary_period = {
                "1 hour": "hourly",
                "1 month": "monthly",
                "1 year": "yearly",
            }.get(interval)

        return ExtractedPosting(
            company=payload.get("name") or _humanize(company_slug),
            title=job.get("title"),
            location=location,
            is_remote=job.get("isRemote")
            if job.get("isRemote") is not None
            else self.detect_remote(location),
            employment_type=self.guess_employment_type(job.get("title"), job.get("employmentType")),
            req_id=posting_id,
            posted_at=posted_at,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_period=salary_period,
            description_markdown=self.to_markdown(description_html)
            or (job.get("descriptionPlain") or None),
            description_html=description_html,
            confidence=1.0,
        )
