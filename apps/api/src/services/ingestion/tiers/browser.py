"""Tier 3 — headless browser for JS-rendered postings.

Expensive (~3–8s and real memory), so it is opt-in: install the `browser` extra and set
`INGEST_BROWSER_ENABLED=1`. A process-wide semaphore keeps concurrency at 1 by default,
which is what makes this safe to run next to the API on Cloud Run (README §11).
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = int(os.getenv("INGEST_BROWSER_CONCURRENCY", "1"))
_semaphore = threading.Semaphore(_MAX_CONCURRENCY)


def enabled() -> bool:
    if os.getenv("INGEST_BROWSER_ENABLED", "").lower() not in ("1", "true", "yes"):
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        logger.info("browser tier requested but playwright is not installed")
        return False
    return True


def render(url: str, *, timeout_ms: int = 20_000) -> str | None:
    """Return fully rendered HTML, or None when the tier is unavailable or fails."""
    if not enabled():
        return None

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    executable = os.getenv("PLAYWRIGHT_CHROMIUM_PATH")
    with _semaphore:
        try:
            with sync_playwright() as playwright:
                launch_kwargs = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
                if executable:
                    launch_kwargs["executable_path"] = executable
                browser = playwright.chromium.launch(**launch_kwargs)
                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(1_500)
                    return page.content()
                finally:
                    browser.close()
        except PlaywrightError:
            logger.exception("browser tier failed for %s", url)
            return None
