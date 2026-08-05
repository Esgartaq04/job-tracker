"""Workday — {co}.wd*.myworkdayjobs.com/... → the CXS JSON endpoint derived from the path.

Workday tenants render postings client-side, so the HTML tiers get nothing useful; the
CXS endpoint behind the same path returns the whole posting as JSON.
"""

import re
from datetime import datetime
from urllib.parse import urlsplit

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.adapters.base import AdapterError, ATSAdapter
from src.services.ingestion.fetch import FetchError, fetch_json
from src.services.ingestion.normalize import _humanize, host_of, normalize_url

_HOST = re.compile(r"^(?P<tenant>[a-z0-9-]+)\.(?P<pod>wd\d+)\.myworkdayjobs\.com$")
_LOCALE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")


class WorkdayAdapter(ATSAdapter):
    vendor = "workday"

    def matches(self, url: str) -> bool:
        return bool(_HOST.match(host_of(url) or "")) and self._parse(url) is not None

    def _parse(self, url: str) -> tuple[str, str, str, str] | None:
        """→ (tenant, pod, site, job_path)"""
        parts = urlsplit(normalize_url(url))
        host_match = _HOST.match((parts.hostname or "").lower())
        if not host_match:
            return None

        segments = [s for s in parts.path.split("/") if s]
        if segments and _LOCALE.match(segments[0]):
            segments = segments[1:]
        if len(segments) < 2 or "job" not in segments:
            return None

        job_index = segments.index("job")
        site = segments[job_index - 1] if job_index >= 1 else None
        job_path = "/".join(segments[job_index:])
        if not site or not job_path:
            return None
        return host_match.group("tenant"), host_match.group("pod"), site, job_path

    def fetch(self, url: str) -> ExtractedPosting:
        parsed = self._parse(url)
        if parsed is None:
            raise AdapterError("not a workday posting URL")
        tenant, pod, site, job_path = parsed

        api = f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/{job_path}"
        try:
            payload = fetch_json(api)
        except FetchError as exc:
            raise AdapterError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise AdapterError("unexpected workday payload")

        info = payload.get("jobPostingInfo") or {}
        description_html = info.get("jobDescription")
        location = info.get("location")
        remote_type = (info.get("remoteType") or "").lower()

        posted_at = None
        for key in ("startDate", "postedOn"):
            value = info.get(key)
            if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
                try:
                    posted_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    break
                except ValueError:
                    continue

        return ExtractedPosting(
            company=_humanize(tenant),
            title=info.get("title"),
            location=location,
            is_remote=True if "remote" in remote_type else self.detect_remote(location),
            employment_type=self.guess_employment_type(info.get("title"), info.get("timeType")),
            req_id=info.get("jobReqId"),
            posted_at=posted_at,
            description_markdown=self.to_markdown(description_html),
            description_html=description_html,
            confidence=1.0,
        )
