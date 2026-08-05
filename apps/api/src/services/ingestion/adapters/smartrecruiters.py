"""SmartRecruiters — jobs.smartrecruiters.com/{co}/{id} → public postings API."""

import re
from datetime import datetime
from urllib.parse import urlsplit

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import AdapterError, ATSAdapter
from src.services.ingestion.fetch import FetchError, fetch_json
from src.services.ingestion.normalize import _humanize, host_of, normalize_url

API = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}"
_ID = re.compile(r"(\d{9,})")


class SmartRecruitersAdapter(ATSAdapter):
    vendor = "smartrecruiters"

    def matches(self, url: str) -> bool:
        host = host_of(url) or ""
        return host.endswith("smartrecruiters.com") and self._parse(url) is not None

    def _parse(self, url: str) -> tuple[str, str] | None:
        segments = [s for s in urlsplit(normalize_url(url)).path.split("/") if s]
        if len(segments) < 2:
            return None
        match = _ID.search(segments[1])
        if not match:
            return None
        return segments[0], match.group(1)

    def fetch(self, url: str) -> ExtractedPosting:
        parsed = self._parse(url)
        if parsed is None:
            raise AdapterError("not a smartrecruiters posting URL")
        company_slug, posting_id = parsed

        try:
            payload = fetch_json(API.format(company=company_slug, posting_id=posting_id))
        except FetchError as exc:
            raise AdapterError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise AdapterError("unexpected smartrecruiters payload")

        location_data = payload.get("location") or {}
        location = (
            ", ".join(
                part
                for part in [
                    location_data.get("city"),
                    location_data.get("region"),
                    location_data.get("country"),
                ]
                if part
            )
            or None
        )

        sections = ((payload.get("jobAd") or {}).get("sections")) or {}
        description_html = "".join(
            f"<h3>{section.get('title', key)}</h3>{section.get('text', '')}"
            for key, section in sections.items()
            if isinstance(section, dict) and section.get("text")
        )

        posted_at = None
        if payload.get("releasedDate"):
            try:
                posted_at = datetime.fromisoformat(payload["releasedDate"].replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        type_of_employment = (payload.get("typeOfEmployment") or {}).get("label")

        return ExtractedPosting(
            company=(payload.get("company") or {}).get("name") or _humanize(company_slug),
            title=payload.get("name"),
            location=location,
            is_remote=location_data.get("remote")
            if location_data.get("remote") is not None
            else self.detect_remote(location),
            employment_type=self.guess_employment_type(payload.get("name"), type_of_employment),
            req_id=payload.get("refNumber") or posting_id,
            posted_at=posted_at,
            description_markdown=self.to_markdown(description_html),
            description_html=description_html or None,
            confidence=1.0,
        )
