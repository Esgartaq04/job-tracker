"""Description clean-up (Phase 5a).

Scraped descriptions carry the page around them: "Apply now", share buttons, cookie
notices, "similar jobs", footers. The model removes that and is told not to reword
anything, and `faithful()` checks it didn't: every run of words it returns has to
appear in the original. A clean-up that fails the check is thrown away and the raw
text stays on screen. A wrong job description is worse than a noisy one.
"""

import logging
import re
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import Application
from src.models.util import utcnow
from src.services import ai, events

logger = logging.getLogger(__name__)

#: The instruction, in the user's words.
CLEANUP_PROMPT = (
    "I have the following job description please clean it up. DONT reword or re write it:"
)

CLEANUP_SYSTEM = (
    "You clean up job descriptions that were scraped from web pages. Remove everything "
    "that is not part of the job posting itself: site navigation, cookie and privacy "
    "banners, 'Apply now' / 'Save' / 'Share' / 'Copy link' controls, sign-in prompts, "
    "lists of similar or recommended jobs, social links, and site footers. Keep every "
    "sentence of the posting exactly as written and in the same order — do not reword, "
    "summarize, shorten, correct, or add anything. You may fix line breaks and format "
    "headings and lists as Markdown. Reply with only the cleaned description: no "
    "preamble, no closing remarks, no code fences."
)

#: Below this there's nothing worth cleaning.
MIN_CHARS = 300
#: Above this the reply could outgrow max_tokens; leaving it raw beats truncating it.
MAX_CHARS = 60_000
#: Share of the cleaned text's 5-word runs that must appear verbatim in the original…
MIN_FAITHFUL = 0.97
#: …except that a handful may not, so a short posting survives a repeated heading or a
#: re-joined line. One reworded sentence costs far more runs than this.
UNMATCHED_ALLOWANCE = 8
#: A "clean-up" that kept less than this much of the original threw the posting away.
MIN_KEPT = 0.15

_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_WORD = re.compile(r"\w+", re.UNICODE)
_FENCE = re.compile(r"^```[a-z]*\n(.*)\n```$", re.DOTALL)


@dataclass
class Verdict:
    ok: bool
    reason: str | None = None
    faithful: float = 0.0
    kept: float = 0.0
    #: Not attempted (too short, too long) or not finished (cut off) — as opposed to
    #: attempted and caught rewording.
    skipped: bool = False

    @property
    def status(self) -> str:
        return "ok" if self.ok else "skipped" if self.skipped else "rejected"


def _words(text: str) -> list[str]:
    return _WORD.findall(_LINK.sub(r"\1", text).lower())


def _grams(words: list[str], n: int = 5) -> list[tuple[str, ...]]:
    if len(words) < n:
        return [tuple(words)] if words else []
    return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]


def faithful(raw: str, cleaned: str) -> Verdict:
    """Did the clean-up only delete? Compares word 5-grams, so Markdown, punctuation,
    and line breaks may change but wording may not."""
    raw_words, cleaned_words = _words(raw), _words(cleaned)
    if len(cleaned_words) < 5:
        return Verdict(False, "it came back empty")

    kept = len(cleaned_words) / max(len(raw_words), 1)
    raw_grams = set(_grams(raw_words))
    grams = _grams(cleaned_words)
    matched = sum(gram in raw_grams for gram in grams)
    share = matched / len(grams)
    allowed = max(len(grams) * (1 - MIN_FAITHFUL), UNMATCHED_ALLOWANCE)

    if len(grams) - matched > allowed or _substituted(raw_words, cleaned_words):
        return Verdict(False, "it reworded the description", share, kept)
    if kept < MIN_KEPT:
        return Verdict(False, "it removed most of the description", share, kept)
    return Verdict(True, None, share, kept)


def _substituted(raw_words: list[str], cleaned_words: list[str]) -> bool:
    """Whether any word was swapped or added, not just deleted. The 5-gram allowance
    alone lets one changed word through — "5+ years" becoming "3+ years" misses only
    five runs. Aligned word by word, any words the original doesn't have at that spot
    must repeat at least three words of it verbatim (a heading) — never one swapped word."""
    raw_text = f" {' '.join(raw_words)} "
    matcher = SequenceMatcher(None, raw_words, cleaned_words, autojunk=False)
    for op, _, _, j1, j2 in matcher.get_opcodes():
        if op in ("replace", "insert"):
            added = cleaned_words[j1:j2]
            if len(added) < 3 or f" {' '.join(added)} " not in raw_text:
                return True
    return False


def clean_description(db: Session, application: Application) -> Verdict:
    """Clean one application's description and record the outcome on the card.

    Raises `ai.AIUnavailable` / `ai.AIQuotaExceeded` *before* touching the card, so a
    caller decides whether that's an error (the button) or a no-op (the background run).
    Returns the verdict; on success `description_clean` is set.
    """
    raw = (application.description_raw or "").strip()
    if len(raw) < MIN_CHARS:
        return _record(application, Verdict(False, "it's too short to need it", skipped=True))
    if len(raw) > MAX_CHARS:
        return _record(application, Verdict(False, "it's too long to clean safely", skipped=True))

    client = ai.client()
    ai.reserve_call(db, application.user_id, "cleanup")

    response = client.messages.create(
        model=settings.llm_model,
        max_tokens=16_000,
        system=CLEANUP_SYSTEM,
        messages=[{"role": "user", "content": f"{CLEANUP_PROMPT}\n\n{raw}"}],
    )
    if getattr(response, "stop_reason", None) == "max_tokens":
        return _record(application, Verdict(False, "the clean-up was cut off", skipped=True))

    cleaned = ai.response_text(response)
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()

    verdict = faithful(raw, cleaned)
    if verdict.ok:
        application.description_clean = cleaned[: settings.max_description_chars]
    return _record(application, verdict)


def _record(application: Application, verdict: Verdict) -> Verdict:
    meta = dict(application.extraction_meta or {})
    meta["cleanup"] = {
        "status": verdict.status,
        "reason": verdict.reason,
        "faithful": round(verdict.faithful, 3),
        "kept": round(verdict.kept, 3),
        "model": settings.llm_model,
        "at": utcnow().isoformat(),
    }
    application.extraction_meta = meta
    application.updated_at = utcnow()
    return verdict


def run_cleanup(db: Session, application_id: uuid.UUID) -> None:
    """Background entry point (queue / worker): best effort, never raises for the
    expected reasons, and tells the board when the description changed."""
    application = db.get(Application, application_id)
    # Once a run has a verdict, re-ingesting the same immutable raw text would only buy
    # the same verdict again. Retrying is the "Clean up" button's job.
    if application is None or application.description_clean:
        return
    if (application.extraction_meta or {}).get("cleanup"):
        return
    try:
        verdict = clean_description(db, application)
    except (ai.AIUnavailable, ai.AIQuotaExceeded) as exc:
        logger.info("cleanup skipped for %s: %s", application_id, exc)
        db.rollback()
        return
    except ai.AIFailed as exc:
        verdict = _record(application, Verdict(False, str(exc), skipped=True))
    db.commit()
    events.publish(
        application.user_id,
        "application.updated",
        {"application_id": str(application.id), "cleanup": verdict.status},
    )
