"""The extension's autofill (Phase 4b): a profile read from a resume, the form fields
the extension found on a page, and what to put in them."""

from typing import Literal

from pydantic import BaseModel, Field


class Education(BaseModel):
    school: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None


class Experience(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    summary: str | None = None


class ResumeProfile(BaseModel):
    """What a resume says about its owner. Flat and union-free so it maps cleanly onto
    a JSON Schema for structured output. Every field is optional: absent beats guessed."""

    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)


FieldKind = Literal["text", "textarea", "select", "radio", "checkbox", "file"]


class FormField(BaseModel):
    """One control (or one radio/checkbox group) as the extension describes it."""

    id: str = Field(max_length=40)
    kind: FieldKind
    label: str = Field(default="", max_length=300)
    name: str | None = Field(default=None, max_length=200)
    html_id: str | None = Field(default=None, max_length=200)
    input_type: str | None = Field(default=None, max_length=40)
    autocomplete: str | None = Field(default=None, max_length=80)
    placeholder: str | None = Field(default=None, max_length=200)
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=300)
    #: For file inputs, what the label says it wants.
    file_role: Literal["resume", "cover_letter", "other"] | None = None


class AutofillRequest(BaseModel):
    page_url: str = Field(max_length=2000)
    fields: list[FormField] = Field(max_length=400)
    profile: ResumeProfile


class Assignment(BaseModel):
    field_id: str
    #: Text to type, or the option to pick for a select / radio / checkbox group.
    value: str | None = None
    #: For a file input: attach the resume the user uploaded.
    attach: Literal["resume"] | None = None
    source: Literal["rule", "ai"]


class NeedsUser(BaseModel):
    field_id: str
    label: str
    reason: str


class AutofillPlan(BaseModel):
    assignments: list[Assignment]
    needs_user: list[NeedsUser]
    #: Whether the model was asked about the fields no rule could place.
    used_ai: bool = False
