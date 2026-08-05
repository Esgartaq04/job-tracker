"""Tier 4 — LLM structuring (README §8.1, candidate A).

"AI as plumbing, not as a feature": the user never sees a model, they see a card
that filled itself in. Runs only when the cheap tiers have failed, against a
schema-constrained output, on cleaned and truncated text.
"""

import logging
import os
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.core.config import settings
from src.schemas.extraction import ExtractedPosting

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You extract structured data from job postings. Use only what the posting "
    "states — never infer a company, salary, or location that is not present, and "
    "leave a field null instead of guessing. `description_markdown` is the posting's "
    "own text as clean Markdown, with navigation, cookie banners, and boilerplate "
    "removed. `confidence` is your own 0-1 estimate of how well this page matched a "
    "single job posting."
)


class LLMExtraction(BaseModel):
    """The LLM-facing schema. Kept flat and union-free so it maps cleanly onto a
    JSON Schema; `ExtractedPosting` is the richer internal type."""

    company: str | None = None
    title: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    employment_type: Literal["internship", "full_time", "co_op", "contract"] | None = None
    req_id: str | None = None
    posted_at: date | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: Literal["hourly", "monthly", "yearly"] | None = None
    required_skills: list[str] = Field(default_factory=list)
    description_markdown: str | None = None
    confidence: float = 0.0


class LLMUnavailable(RuntimeError):
    pass


def enabled() -> bool:
    return bool(settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))


def extract(text: str, *, url: str | None = None) -> ExtractedPosting | None:
    """Structure cleaned posting text. Returns None when the tier is unavailable
    or the model couldn't find a posting on the page."""
    if not enabled():
        logger.debug("LLM tier skipped: no API key configured")
        return None

    cleaned = (text or "").strip()
    if len(cleaned) < 200:
        return None
    # Cost control: the cheap tiers already stripped chrome; cap what's left.
    cleaned = cleaned[: settings.llm_max_input_chars]

    try:
        import anthropic
    except ImportError:  # pragma: no cover - optional dependency
        logger.info("LLM tier requested but the anthropic package is not installed")
        return None

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)

    prompt = f"Job posting URL: {url or 'unknown'}\n\n---\n{cleaned}\n---"
    try:
        response = client.messages.parse(
            model=settings.llm_model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=LLMExtraction,
        )
    except anthropic.APIError:
        logger.exception("LLM extraction failed for %s", url)
        return None

    parsed = response.parsed_output
    if parsed is None:
        logger.warning("LLM extraction returned no parsable output for %s", url)
        return None

    posting = ExtractedPosting(
        company=parsed.company,
        title=parsed.title,
        location=parsed.location,
        is_remote=parsed.is_remote,
        employment_type=parsed.employment_type,
        req_id=parsed.req_id,
        posted_at=parsed.posted_at,
        salary_min=parsed.salary_min,
        salary_max=parsed.salary_max,
        salary_currency=parsed.salary_currency,
        salary_period=parsed.salary_period,
        required_skills=parsed.required_skills,
        description_markdown=parsed.description_markdown,
        confidence=max(0.0, min(parsed.confidence, 1.0)),
    )
    return posting if posting.is_useful else None


def usage_note(posting: ExtractedPosting) -> dict:
    """Recorded into `extraction_meta` so the UI can flag low-confidence fields
    and so the Tier-4 fallback rate stays measurable (README §8.1, §11)."""
    return {
        "model": settings.llm_model,
        "confidence": posting.confidence,
        "needs_verification": posting.confidence < 0.6,
        "extracted_at": datetime.now().astimezone().isoformat(),
    }
