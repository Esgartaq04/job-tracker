"""Lever — jobs.lever.co/{co}/{uuid} → api.lever.co/v0/postings/{co}/{uuid}."""

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import AdapterError, ATSAdapter
from src.services.ingestion.fetch import FetchError, fetch_json
from src.services.ingestion.normalize import _humanize, host_of, normalize_url

API = "https://api.lever.co/v0/postings/{company}/{posting_id}"
_ID = re.compile(r"^[0-9a-fA-F-]{8,}$")


class LeverAdapter(ATSAdapter):
    vendor = "lever"

    def matches(self, url: str) -> bool:
        return (host_of(url) or "") == "jobs.lever.co" and self._parse(url) is not None

    def _parse(self, url: str) -> tuple[str, str] | None:
        segments = [s for s in urlsplit(normalize_url(url)).path.split("/") if s]
        if len(segments) >= 2 and _ID.match(segments[1]):
            return segments[0], segments[1]
        return None

    def fetch(self, url: str) -> ExtractedPosting:
        parsed = self._parse(url)
        if parsed is None:
            raise AdapterError("not a lever posting URL")
        company_slug, posting_id = parsed

        try:
            payload = fetch_json(API.format(company=company_slug, posting_id=posting_id))
        except FetchError as exc:
            raise AdapterError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise AdapterError("unexpected lever payload")

        categories = payload.get("categories") or {}
        location = categories.get("location")
        commitment = (categories.get("commitment") or "").lower() or None

        description_html = "".join(
            filter(
                None,
                [
                    payload.get("descriptionHtml") or payload.get("description") or "",
                    *[
                        f"<h3>{section.get('text', '')}</h3>{section.get('content', '')}"
                        for section in payload.get("lists") or []
                    ],
                    payload.get("additionalHtml") or payload.get("additional") or "",
                ],
            )
        )

        posted_at = None
        if payload.get("createdAt"):
            try:
                posted_at = datetime.fromtimestamp(payload["createdAt"] / 1000, tz=UTC)
            except (TypeError, ValueError, OSError):
                posted_at = None

        employment_type = None
        if commitment:
            employment_type = self.guess_employment_type(commitment) or self.guess_employment_type(
                payload.get("text")
            )
        else:
            employment_type = self.guess_employment_type(payload.get("text"))

        workplace = (payload.get("workplaceType") or "").lower()
        is_remote = True if workplace == "remote" else self.detect_remote(location)

        return ExtractedPosting(
            company=_humanize(company_slug),
            title=payload.get("text"),
            location=location,
            is_remote=is_remote,
            employment_type=employment_type,
            req_id=posting_id,
            posted_at=posted_at,
            description_markdown=self.to_markdown(description_html),
            description_html=description_html or None,
            confidence=1.0,
        )
