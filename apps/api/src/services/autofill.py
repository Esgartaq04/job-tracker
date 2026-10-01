"""What goes in which application-form field (Phase 4b).

Rules first: the standard fields (name, email, phone, links, location) are matched by
the `autocomplete` attribute or by label, with no model involved. What's left goes to
the model with the resume profile, and its answers are checked: they must name a real
field, and pick a real option where there are options.

Some questions are never answered for the user, by rule or by model — work
authorization, sponsorship, demographics, salary, legal attestations. A wrong answer
there can cost the application or misstate something about the person, so they're
always handed back as "needs you". The extension also never submits the form.
"""

import json
import logging
import re

from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import settings
from src.schemas.autofill import (
    Assignment,
    AutofillPlan,
    AutofillRequest,
    FormField,
    NeedsUser,
    ResumeProfile,
)
from src.services import ai

logger = logging.getLogger(__name__)

SENSITIVE = re.compile(
    r"authori[sz]|sponsor|visa\b|citizen|immigration|work permit|right to work|"
    r"gender|sex\b|pronoun|race\b|racial|ethnic|hispanic|latino|veteran|military|"
    r"disabilit|sexual|orientation|transgender|lgbt|"
    r"salary|compensation|pay expect|desired pay|expected pay|"
    r"criminal|convict|felony|background check|drug test|"
    r"signature|sign here|certify|attest|acknowledg|consent|i agree|terms|privacy|"
    r"date of birth|birth ?date|\bage\b|social security|\bssn\b|national id|"
    r"relative|related to anyone|previously (been )?employed|worked (here|for us) before",
    re.IGNORECASE,
)

#: Free-text prompts that want the applicant's own words, not resume facts.
ESSAY = re.compile(
    r"why (do )?you|why are you|what interests you|tell us|describe a time|cover letter|"
    r"anything else|additional information|how did you hear|referr",
    re.IGNORECASE,
)

PROFILE_SYSTEM = (
    "You read resumes. Extract the candidate's details exactly as the resume states them. "
    "Never infer or invent: leave a field null, or a list empty, when the resume doesn't "
    "say. Use full URLs for links when the resume gives them. Dates stay as written."
)

MAP_SYSTEM = (
    "You fill in job application forms from a candidate's resume profile. For each form "
    "field you are given, answer with the value to enter, using only facts in the profile. "
    "For a field with options, the value must be exactly one of its options. Return null "
    "when the profile doesn't support an answer. Never answer questions about work "
    "authorization, visa sponsorship, citizenship, gender, race, ethnicity, veteran or "
    "disability status, sexual orientation, salary expectations, criminal history, or "
    "any consent, signature, or attestation — return null for those. Never write essay "
    "answers ('why do you want to work here', cover letters, 'anything else') — return "
    "null. Prefer null to a guess."
)


class _Answer(BaseModel):
    field_id: str
    value: str | None = None


class _Answers(BaseModel):
    answers: list[_Answer]


def read_profile(db: Session, user_id, resume: bytes, filename: str | None) -> ResumeProfile:
    blocks = ai.resume_content(resume, filename)
    client = ai.client()
    ai.reserve_call(db, user_id, "resume_profile")
    response = client.messages.parse(
        model=settings.llm_model,
        max_tokens=8000,
        system=PROFILE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [*blocks, {"type": "text", "text": "Extract my details."}],
            }
        ],
        output_format=ResumeProfile,
    )
    if response.parsed_output is None:
        raise ai.AIFailed("Couldn't read that resume. Try a PDF exported from your editor.")
    return response.parsed_output


# ── rules ───────────────────────────────────────────────────────────────────


def _text(field: FormField) -> str:
    return " ".join(
        part for part in (field.label, field.name, field.html_id, field.placeholder) if part
    ).lower()


def _profile_value(profile: ResumeProfile, key: str) -> str | None:
    if key == "full_name":
        return (
            profile.full_name
            or " ".join(part for part in (profile.first_name, profile.last_name) if part)
            or None
        )
    if key == "location":
        return (
            ", ".join(part for part in (profile.city, profile.region, profile.country) if part)
            or None
        )
    if key == "school":
        return profile.education[0].school if profile.education else None
    if key == "degree":
        return profile.education[0].degree if profile.education else None
    return getattr(profile, key, None)


#: The HTML `autocomplete` tokens worth trusting outright.
AUTOCOMPLETE = {
    "given-name": "first_name",
    "family-name": "last_name",
    "name": "full_name",
    "email": "email",
    "tel": "phone",
    "tel-national": "phone",
    "address-level2": "city",
    "address-level1": "region",
    "country-name": "country",
    "organization": "current_company",
    "organization-title": "current_title",
}

#: Label / name patterns, most specific first.
LABEL_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"first[\s_-]*name|given[\s_-]*name|\bfname\b"), "first_name"),
    (re.compile(r"last[\s_-]*name|surname|family[\s_-]*name|\blname\b"), "last_name"),
    (re.compile(r"linkedin"), "linkedin_url"),
    (re.compile(r"github"), "github_url"),
    (re.compile(r"e-?mail"), "email"),
    (re.compile(r"phone|mobile|\btel\b"), "phone"),
    (re.compile(r"portfolio|personal (web)?site|website|\burl\b"), "website_url"),
    (re.compile(r"full[\s_-]*name|legal[\s_-]*name"), "full_name"),
    (re.compile(r"current (company|employer)|most recent (company|employer)"), "current_company"),
    (re.compile(r"current (job )?title|current role|most recent title"), "current_title"),
    (re.compile(r"\bcity\b"), "city"),
    (re.compile(r"\b(state|province|region)\b"), "region"),
    (re.compile(r"\bcountry\b"), "country"),
    # Not "address": a street address wants a street, not "Chicago, IL".
    (re.compile(r"location|where are you based|where do you live"), "location"),
    (re.compile(r"school|university|college|institution"), "school"),
    (re.compile(r"\bdegree\b"), "degree"),
]


def _rule_for(field: FormField) -> str | None:
    token = (field.autocomplete or "").lower().split()[-1:] or [""]
    if token[0] in AUTOCOMPLETE:
        return AUTOCOMPLETE[token[0]]
    # A field labelled just "Name" is the applicant's; "Name of your school" is not.
    if re.fullmatch(r"(your |full |legal )?name", field.label.strip().lower()):
        return "full_name"
    text = _text(field)
    for pattern, key in LABEL_RULES:
        if pattern.search(text):
            return key
    return None


def _pick_option(field: FormField, value: str | None) -> str | None:
    """The field's own option matching `value`, or None. A select can only take what
    it offers, so "USA" has to become "United States" or nothing."""
    if value is None:
        return None
    if not field.options:
        return value
    wanted = value.strip().lower()
    for option in field.options:
        if option.strip().lower() == wanted:
            return option
    # Whole words only, and nothing too short to mean anything: "US" must not land on
    # "Australia", nor "No" on "North Carolina".
    for option in field.options:
        have = option.strip().lower()
        if min(len(have), len(wanted)) >= 3 and (
            _has_words(have, wanted) or _has_words(wanted, have)
        ):
            return option
    return None


def _has_words(text: str, words: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(words)}(?!\w)", text) is not None


def plan(db: Session, user_id, request: AutofillRequest) -> AutofillPlan:
    assignments: list[Assignment] = []
    needs: list[NeedsUser] = []
    leftover: list[FormField] = []
    profile = request.profile

    for field in request.fields:
        label = field.label or field.name or field.placeholder or "Unlabelled field"
        if field.kind == "file":
            if field.file_role == "resume":
                assignments.append(Assignment(field_id=field.id, attach="resume", source="rule"))
            elif field.required or field.file_role == "cover_letter":
                needs.append(
                    NeedsUser(field_id=field.id, label=label, reason="attach this file yourself")
                )
            continue
        if SENSITIVE.search(_text(field)):
            needs.append(
                NeedsUser(field_id=field.id, label=label, reason="only you can answer this")
            )
            continue

        key = _rule_for(field)
        value = _pick_option(field, _profile_value(profile, key)) if key else None
        if value:
            assignments.append(Assignment(field_id=field.id, value=value, source="rule"))
        elif field.kind == "textarea" and ESSAY.search(_text(field)):
            needs.append(
                NeedsUser(field_id=field.id, label=label, reason="this wants your own words")
            )
        else:
            leftover.append(field)

    used_ai = False
    answers = _ask_model(db, user_id, profile, leftover) if leftover else None
    if answers is not None:
        used_ai = True
        by_id = {field.id: field for field in leftover}
        for answer in answers:
            field = by_id.pop(answer.field_id, None)
            value = _pick_option(field, answer.value) if field else None
            if field is not None and value and not SENSITIVE.search(value):
                assignments.append(Assignment(field_id=field.id, value=value, source="ai"))
            elif field is not None:
                by_id[field.id] = field
        leftover = list(by_id.values())

    for field in leftover:
        if field.required:
            label = field.label or field.name or field.placeholder or "Unlabelled field"
            needs.append(NeedsUser(field_id=field.id, label=label, reason="not on your resume"))

    return AutofillPlan(assignments=assignments, needs_user=needs, used_ai=used_ai)


def _ask_model(
    db: Session, user_id, profile: ResumeProfile, fields: list[FormField]
) -> list[_Answer] | None:
    """The model's answers, or None when it wasn't asked (no key, cap spent)."""
    try:
        client = ai.client()
        ai.reserve_call(db, user_id, "autofill")
    except (ai.AIUnavailable, ai.AIQuotaExceeded) as exc:
        logger.info("autofill without AI: %s", exc)
        return None

    described = [
        {
            "field_id": field.id,
            "label": field.label or field.name or field.placeholder,
            "kind": field.kind,
            "options": field.options or None,
            "required": field.required,
        }
        for field in fields
    ]
    prompt = (
        f"<profile>\n{profile.model_dump_json(exclude_none=True)}\n</profile>\n"
        f"<fields>\n{json.dumps(described)}\n</fields>\n"
        "Answer every field_id."
    )
    try:
        response = client.messages.parse(
            model=settings.llm_model,
            max_tokens=8000,
            system=MAP_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=_Answers,
        )
    except Exception as exc:
        if not ai.is_sdk_error(exc):
            raise
        logger.exception("autofill mapping failed")
        return []
    return response.parsed_output.answers if response.parsed_output else []
