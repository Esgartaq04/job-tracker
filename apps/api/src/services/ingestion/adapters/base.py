"""Adapter contract (README §4.1): `matches(url)` + `fetch(url)`.

Adding an ATS is a ~40-line file plus one registry entry.
"""

import re
from abc import ABC, abstractmethod

from src.schemas.extraction import ExtractedPosting
from src.services.ingestion.html import html_to_markdown


class AdapterError(RuntimeError):
    pass


class ATSAdapter(ABC):
    #: Stored on `applications.ats_vendor` and used for per-source analytics.
    vendor: str

    @abstractmethod
    def matches(self, url: str) -> bool: ...

    @abstractmethod
    def fetch(self, url: str) -> ExtractedPosting: ...

    # ── shared helpers ────────────────────────────────────────────────────
    @staticmethod
    def to_markdown(html: str | None) -> str | None:
        if not html:
            return None
        return html_to_markdown(html) or None

    @staticmethod
    def guess_employment_type(title: str | None, raw: str | None = None) -> str | None:
        haystack = " ".join(filter(None, [title, raw])).lower()
        if not haystack:
            return None
        if "intern" in haystack:
            return "internship"
        if "co-op" in haystack or "co op" in haystack or "coop" in haystack:
            return "co_op"
        if "contract" in haystack or "contractor" in haystack:
            return "contract"
        if "full time" in haystack or "full-time" in haystack or "fulltime" in haystack:
            return "full_time"
        return None

    @staticmethod
    def detect_remote(location: str | None, description: str | None = None) -> bool | None:
        if location and re.search(r"\bremote\b", location, re.I):
            return True
        if location:
            return False
        if description and re.search(r"\bfully remote\b", description, re.I):
            return True
        return None
