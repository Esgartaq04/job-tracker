from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

EmploymentType = Literal["internship", "full_time", "co_op", "contract"]
SalaryPeriod = Literal["hourly", "monthly", "yearly"]


class ExtractedPosting(BaseModel):
    """The shared extraction schema (README §8.1). Every tier — JSON-LD, ATS adapter,
    generic HTML, LLM — produces one of these, so the persistence step is written once."""

    company: str | None = None
    company_domain: str | None = None
    title: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    employment_type: EmploymentType | None = None
    req_id: str | None = None
    posted_at: date | datetime | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    required_skills: list[str] = Field(default_factory=list)
    description_markdown: str | None = None
    description_html: str | None = None
    confidence: float = 1.0

    def merge(self, other: "ExtractedPosting") -> "ExtractedPosting":
        """Fill this posting's gaps from `other`; never overwrite what we already have.
        Lets a cheap tier keep its wins when a later tier only adds a description."""
        merged = self.model_copy(deep=True)
        for field, value in other.model_dump(exclude_none=True).items():
            if field in {"confidence", "required_skills"}:
                continue
            if getattr(merged, field) in (None, "", []):
                setattr(merged, field, value)
        if not merged.required_skills:
            merged.required_skills = other.required_skills
        merged.confidence = min(self.confidence, other.confidence)
        return merged

    @property
    def is_useful(self) -> bool:
        """A tier "succeeded" only if it produced something worth showing on a card."""
        return bool(self.title and (self.company or self.description_markdown))


class RawPosting(BaseModel):
    """What a fetcher/adapter hands to the parsing step."""

    url: str
    status_code: int | None = None
    content_type: str | None = None
    html: str | None = None
    text: str | None = None
    json_payload: dict | list | None = None
