"""HTTP fetching with a canonical-URL cache (README §4.2)."""

import json
import logging
import time
from dataclasses import dataclass

import httpx

from src.core.config import settings
from src.schemas.extraction import RawPosting
from src.services.ingestion.normalize import canonicalize

logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    pass


@dataclass
class _CacheEntry:
    value: dict
    expires_at: float


class _MemoryCache:
    """Used when Redis isn't configured. Bounded so a long-running process can't grow
    without limit."""

    def __init__(self, max_entries: int = 256) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._max_entries = max_entries

    def get(self, key: str) -> dict | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            self._entries.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: dict, ttl: int) -> None:
        if len(self._entries) >= self._max_entries:
            oldest = min(self._entries, key=lambda k: self._entries[k].expires_at)
            self._entries.pop(oldest, None)
        self._entries[key] = _CacheEntry(value=value, expires_at=time.time() + ttl)


_memory_cache = _MemoryCache()


def _cache_key(url: str) -> str:
    return f"fetch:{canonicalize(url)}"


def cache_get(url: str) -> dict | None:
    key = _cache_key(url)
    if settings.redis_url:
        try:
            import redis

            raw = redis.Redis.from_url(settings.redis_url).get(key)
            return json.loads(raw) if raw else None
        except Exception:  # pragma: no cover - cache is best effort
            logger.exception("redis cache read failed")
            return None
    return _memory_cache.get(key)


def cache_set(url: str, payload: dict) -> None:
    key = _cache_key(url)
    ttl = settings.fetch_cache_ttl_seconds
    if settings.redis_url:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url).setex(key, ttl, json.dumps(payload))
            return
        except Exception:  # pragma: no cover - cache is best effort
            logger.exception("redis cache write failed")
    _memory_cache.set(key, payload, ttl)


def _client(**kwargs) -> httpx.Client:
    headers = {
        "User-Agent": settings.fetch_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    headers.update(kwargs.pop("headers", {}))
    return httpx.Client(
        headers=headers,
        timeout=settings.fetch_timeout_seconds,
        follow_redirects=True,
        **kwargs,
    )


def fetch_url(url: str, *, use_cache: bool = True) -> RawPosting:
    """GET a URL, returning HTML or parsed JSON. Cached by canonical URL."""
    if use_cache:
        cached = cache_get(url)
        if cached is not None:
            return RawPosting(**cached)

    try:
        with _client() as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed: {exc}") from exc

    if response.status_code >= 400:
        raise FetchError(f"fetch failed: HTTP {response.status_code}")

    content_type = response.headers.get("content-type", "")
    posting = RawPosting(
        url=str(response.url),
        status_code=response.status_code,
        content_type=content_type,
    )
    if "json" in content_type:
        try:
            posting.json_payload = response.json()
        except ValueError:
            posting.text = response.text[: settings.max_description_chars]
    else:
        posting.html = response.text[: settings.max_description_chars]

    if use_cache:
        cache_set(url, posting.model_dump())
    return posting


def fetch_json(url: str, *, use_cache: bool = True) -> dict | list:
    """GET a JSON endpoint (ATS adapters). Raises FetchError on non-JSON responses."""
    if use_cache:
        cached = cache_get(url)
        if cached is not None and cached.get("json_payload") is not None:
            return cached["json_payload"]

    try:
        with _client(headers={"Accept": "application/json"}) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed: {exc}") from exc

    if response.status_code >= 400:
        raise FetchError(f"fetch failed: HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise FetchError("expected JSON response") from exc

    if use_cache:
        cache_set(
            url,
            RawPosting(
                url=str(response.url),
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
                json_payload=payload,
            ).model_dump(),
        )
    return payload
