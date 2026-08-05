"""Greenhouse — boards.greenhouse.io/{co}/jobs/{id} → boards-api.greenhouse.io."""

import re
from datetime import datetime

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import AdapterError, ATSAdapter
from src.services.ingestion.fetch import FetchError, fetch_json
from src.services.ingestion.normalize import _humanize, host_of, normalize_url

_URL = re.compile(
    r"^(?:boards|job-boards)\.greenhouse\.io$|^(?:boards|job-boards)\.eu\.greenhouse\.io$"
)
_PATH = re.compile(r"/(?:embed/job_app\?token=(?P<token>\d+)|(?P<co>[^/]+)/jobs/(?P<id>\d+))")

API = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"


class GreenhouseAdapter(ATSAdapter):
    vendor = "greenhouse"

    def matches(self, url: str) -> bool:
        host = host_of(url) or ""
        return bool(_URL.match(host)) and self._parse(url) is not None

    def _parse(self, url: str) -> tuple[str, str] | None:
        from urllib.parse import parse_qs, urlsplit

        parts = urlsplit(normalize_url(url))
        segments = [segment for segment in parts.path.split("/") if segment]

        if "jobs" in segments:
            index = segments.index("jobs")
            if index >= 1 and index + 1 < len(segments) and segments[index + 1].isdigit():
                return segments[index - 1], segments[index + 1]

        # Embedded board: /embed/job_app?token=123&for=company
        query = parse_qs(parts.query)
        token = (query.get("token") or [None])[0]
        company = (query.get("for") or [None])[0]
        if token and company:
            return company, token
        return None

    def fetch(self, url: str) -> ExtractedPosting:
        parsed = self._parse(url)
        if parsed is None:
            raise AdapterError("not a greenhouse job URL")
        company_slug, job_id = parsed

        try:
            payload = fetch_json(API.format(company=company_slug, job_id=job_id))
        except FetchError as exc:
            raise AdapterError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise AdapterError("unexpected greenhouse payload")

        description_html = payload.get("content") or ""
        # Greenhouse escapes the description HTML inside JSON.
        import html as html_lib

        description_html = html_lib.unescape(description_html)
        description = self.to_markdown(description_html)

        title = payload.get("title")
        location = (payload.get("location") or {}).get("name")
        company = (payload.get("company_name") or "").strip() or _humanize(company_slug)

        posted_at = None
        if payload.get("first_published"):
            try:
                posted_at = datetime.fromisoformat(
                    payload["first_published"].replace("Z", "+00:00")
                )
            except ValueError:
                posted_at = None

        return ExtractedPosting(
            company=company,
            title=title,
            location=location,
            is_remote=self.detect_remote(location, description),
            employment_type=self.guess_employment_type(title, location),
            req_id=str(payload.get("internal_job_id") or payload.get("id") or job_id),
            posted_at=posted_at,
            description_markdown=description,
            description_html=description_html or None,
            confidence=1.0,
        )
