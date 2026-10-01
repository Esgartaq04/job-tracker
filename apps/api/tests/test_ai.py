"""Phase 5a — the description clean-up — and the plumbing every AI feature shares:
the monthly cap and resume intake."""

import io

import pytest
from fastapi.testclient import TestClient

from src.core.config import settings
from src.services import ai
from src.services.ai_text import CLEANUP_PROMPT, faithful

API = "/api/v1"

POSTING = (
    "About the role\n"
    "You will build the ledger service that moves money between accounts in real time. "
    "You will work with Go, Postgres and Kafka, and you will own features end to end.\n"
    "What we look for\n"
    "Experience shipping backend services. Comfort with SQL. Curiosity about payments.\n"
    "Benefits include health coverage, a learning stipend and flexible hours. "
)
NOISY = (
    "Skip to main content\nSign in\nApply now\nShare\nCopy link\n"
    + POSTING
    + "\nSimilar jobs\nSenior Engineer at Brex\nData Analyst at Plaid\n"
    "© 2026 Example Corp · Privacy · Cookies · Accept all cookies"
)


def saved_with_description(client: TestClient, text: str = NOISY, ai_on: bool = True) -> dict:
    """A card with a scraped-looking description. With a key configured, saving pasted
    text also runs Tier 4 — answered here with "nothing found" so the tests below only
    see the clean-up call."""
    if ai_on and ai.enabled():
        ai.client().parsed(None)
    response = client.post(
        f"{API}/ingest/from-text",
        json={"text": text, "company": "Ramp", "title": "Backend Intern"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── the fidelity check ──────────────────────────────────────────────────────


def test_deleting_noise_is_faithful():
    verdict = faithful(NOISY, "## About the role\n\n" + POSTING)
    assert verdict.ok, verdict.reason


def test_rewording_is_caught():
    reworded = POSTING.replace(
        "You will build the ledger service that moves money between accounts in real time.",
        "In this position you'll create our real-time ledger platform for transfers.",
    ).replace(
        "Experience shipping backend services. Comfort with SQL.",
        "You have delivered backend systems and know SQL well.",
    )
    verdict = faithful(NOISY, reworded)
    assert not verdict.ok
    assert "reworded" in verdict.reason


def test_throwing_the_posting_away_is_caught():
    verdict = faithful(NOISY * 3, "About the role. You will build the ledger service.")
    assert not verdict.ok


# ── the clean-up end to end ─────────────────────────────────────────────────


def test_saving_a_job_queues_its_clean_up(auth_client: TestClient, cleanups: list):
    application = saved_with_description(auth_client)
    assert [str(i) for i in cleanups] == [application["id"]]


def test_a_faithful_clean_up_becomes_the_description(auth_client: TestClient, fake_ai):
    application = saved_with_description(auth_client)
    fake_ai.reply("## About the role\n\n" + POSTING)

    response = auth_client.post(f"{API}/applications/{application['id']}/clean-description")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["description_clean"].startswith("## About the role")
    assert body["description"] == body["description_clean"]
    assert "Accept all cookies" in body["description_raw"], "the original is never touched"
    assert body["extraction_meta"]["cleanup"]["status"] == "ok"

    # The user's own wording, then the raw description.
    sent = fake_ai.requests[-1]["messages"][0]["content"]
    assert sent.startswith(CLEANUP_PROMPT)
    assert "Accept all cookies" in sent


def test_a_reworded_clean_up_is_thrown_away(auth_client: TestClient, fake_ai):
    application = saved_with_description(auth_client)
    fake_ai.reply("This is an exciting opportunity to build payment systems with Go and Kafka!")

    body = auth_client.post(f"{API}/applications/{application['id']}/clean-description").json()
    assert body["description_clean"] is None
    assert body["description"] == body["description_raw"]
    assert body["extraction_meta"]["cleanup"]["status"] == "rejected"


def test_a_users_edit_still_wins_over_the_clean_up(auth_client: TestClient, fake_ai):
    application = saved_with_description(auth_client)
    fake_ai.reply(POSTING)
    auth_client.post(f"{API}/applications/{application['id']}/clean-description")

    auth_client.patch(
        f"{API}/applications/{application['id']}", json={"description_user": "My notes"}
    )
    body = auth_client.get(f"{API}/applications/{application['id']}").json()
    assert body["description"] == "My notes"
    assert body["description_clean"]


def test_the_background_clean_up_updates_the_card(auth_client: TestClient, fake_ai, db_session):
    import uuid

    from src.services.ai_text import run_cleanup

    application = saved_with_description(auth_client)
    fake_ai.reply(POSTING)
    run_cleanup(db_session, uuid.UUID(application["id"]))

    body = auth_client.get(f"{API}/applications/{application['id']}").json()
    assert body["description_clean"].startswith("About the role")


def test_clean_up_without_a_key_says_why(auth_client: TestClient):
    application = saved_with_description(auth_client)
    response = auth_client.post(f"{API}/applications/{application['id']}/clean-description")
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_the_monthly_cap_is_enforced(auth_client: TestClient, fake_ai, monkeypatch):
    first = saved_with_description(auth_client)
    second = saved_with_description(auth_client, NOISY + " Second posting.")
    # Both saves ran Tier 4, and those count too: one call left.
    monkeypatch.setattr(settings, "llm_monthly_call_cap", 3)

    fake_ai.reply(POSTING)
    allowed = auth_client.post(f"{API}/applications/{first['id']}/clean-description")
    assert allowed.status_code == 200

    response = auth_client.post(f"{API}/applications/{second['id']}/clean-description")
    assert response.status_code == 429
    assert "reset" in response.json()["detail"]


# ── resume intake ───────────────────────────────────────────────────────────


def make_docx(*paragraphs: str) -> bytes:
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_a_pdf_resume_goes_to_the_model_as_a_document():
    [block] = ai.resume_content(b"%PDF-1.7 fake resume", "me.pdf")
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_a_word_resume_is_read_as_text():
    [block] = ai.resume_content(make_docx("Esteven Garcia", "Software Engineer Intern, Ramp"))
    assert block["type"] == "text"
    assert "Software Engineer Intern, Ramp" in block["text"]


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"", 422),
        (b"just some text", 415),
        (b"PK\x03\x04 not really a docx", 415),
        (b"%PDF" + b"0" * ai.MAX_RESUME_BYTES, 413),
    ],
)
def test_unusable_resumes_are_rejected(data: bytes, status: int):
    with pytest.raises(ai.ResumeRejected) as caught:
        ai.resume_content(data)
    assert caught.value.status_code == status
