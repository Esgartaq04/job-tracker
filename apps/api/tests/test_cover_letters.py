"""Phase 5b — cover letters from the cleaned description and a resume that's never kept."""

import io

from fastapi.testclient import TestClient

from src.models import Document
from tests.test_ai import NOISY, POSTING, make_docx, saved_with_description

API = "/api/v1"
PDF = b"%PDF-1.7\n% a resume that only the model will read"
LETTER = (
    "Dear Ramp hiring team,\n\nI built a double-entry ledger at school...\n\n"
    "Sincerely,\nEsteven Garcia"
)


def cleaned_listing(client: TestClient, fake_ai) -> dict:
    application = saved_with_description(client)
    fake_ai.reply(POSTING)
    response = client.post(f"{API}/applications/{application['id']}/clean-description")
    assert response.json()["description_clean"]
    return application


def generate(client: TestClient, application_id: str, data: bytes = PDF, **form):
    return client.post(
        f"{API}/applications/{application_id}/cover-letter",
        files={"resume": ("resume.pdf", data, "application/pdf")},
        data=form,
    )


def test_a_letter_is_written_from_the_clean_description_and_the_resume(
    auth_client: TestClient, fake_ai
):
    application = cleaned_listing(auth_client, fake_ai)
    fake_ai.reply(LETTER)

    response = generate(auth_client, application["id"], notes="Mention my referral from Ana")
    assert response.status_code == 200, response.text
    assert response.json()["content"] == LETTER

    request = fake_ai.requests[-1]
    resume_block, prompt_block = request["messages"][0]["content"]
    assert resume_block["type"] == "document"
    assert "ledger service" in prompt_block["text"], "the cleaned description is sent"
    assert "Accept all cookies" not in prompt_block["text"], "the page chrome is not"
    assert "referral from Ana" in prompt_block["text"]
    assert "never invent" in request["system"]


def test_the_resume_is_not_stored(auth_client: TestClient, fake_ai, db_session):
    application = cleaned_listing(auth_client, fake_ai)
    fake_ai.reply(LETTER)
    generate(auth_client, application["id"])

    documents = db_session.query(Document).all()
    assert [document.kind for document in documents] == ["cover_letter"]
    assert all(b"resume" not in (document.content or "").encode() for document in documents)
    assert all(document.gcs_path is None for document in documents)


def test_regenerating_replaces_the_letter(auth_client: TestClient, fake_ai):
    application = cleaned_listing(auth_client, fake_ai)
    fake_ai.reply(LETTER).reply("Dear team,\n\nSecond draft.\n\nBest,\nEsteven")
    first = generate(auth_client, application["id"]).json()
    second = generate(auth_client, application["id"]).json()

    assert second["id"] == first["id"]
    fetched = auth_client.get(f"{API}/applications/{application['id']}/cover-letter").json()
    assert fetched["content"].startswith("Dear team")


def test_a_word_resume_works_too(auth_client: TestClient, fake_ai):
    application = cleaned_listing(auth_client, fake_ai)
    fake_ai.reply(LETTER)
    response = auth_client.post(
        f"{API}/applications/{application['id']}/cover-letter",
        files={"resume": ("resume.docx", make_docx("Esteven Garcia", "Ledger project"), "x")},
    )
    assert response.status_code == 200
    resume_block = fake_ai.requests[-1]["messages"][0]["content"][0]
    assert "Ledger project" in resume_block["text"]


def test_edits_are_saved_and_the_docx_downloads(auth_client: TestClient, fake_ai):
    import docx

    application = cleaned_listing(auth_client, fake_ai)
    fake_ai.reply(LETTER)
    generate(auth_client, application["id"])

    edited = "Dear Ramp team,\n\nMy edited letter.\n\nSincerely,\nEsteven Garcia"
    response = auth_client.patch(
        f"{API}/applications/{application['id']}/cover-letter", json={"content": edited}
    )
    assert response.json()["content"] == edited

    download = auth_client.get(f"{API}/applications/{application['id']}/cover-letter.docx")
    assert download.status_code == 200
    assert (
        "Cover%20Letter%20-%20Ramp%20-%20Backend%20Intern.docx"
        in (download.headers["content-disposition"])
    )
    paragraphs = [p.text for p in docx.Document(io.BytesIO(download.content)).paragraphs]
    assert paragraphs == ["Dear Ramp team,", "My edited letter.", "Sincerely,\nEsteven Garcia"]


def test_a_letter_waits_for_the_clean_up(auth_client: TestClient, fake_ai):
    application = saved_with_description(auth_client)
    response = generate(auth_client, application["id"])
    assert response.status_code == 409
    assert "cleaned up" in response.json()["detail"]


def test_a_declined_clean_up_falls_back_to_the_original(auth_client: TestClient, fake_ai):
    application = saved_with_description(auth_client)
    fake_ai.reply("Totally different words that share nothing with the posting at all.")
    auth_client.post(f"{API}/applications/{application['id']}/clean-description")

    fake_ai.reply(LETTER)
    assert generate(auth_client, application["id"]).status_code == 200
    assert "Accept all cookies" in fake_ai.requests[-1]["messages"][0]["content"][1]["text"]


def test_a_bad_resume_is_refused_before_any_model_call(auth_client: TestClient, fake_ai):
    application = cleaned_listing(auth_client, fake_ai)
    calls = len(fake_ai.requests)
    response = generate(auth_client, application["id"], data=b"not a resume")
    assert response.status_code == 415
    assert len(fake_ai.requests) == calls


def test_someone_elses_listing_is_not_found(auth_client: TestClient, fake_ai, client):
    application = cleaned_listing(auth_client, fake_ai)
    other = client.post(
        f"{API}/auth/register", json={"email": "other@example.com", "password": "another-pass-1"}
    ).json()["access_token"]
    response = client.get(
        f"{API}/applications/{application['id']}/cover-letter",
        headers={"Authorization": f"Bearer {other}"},
    )
    assert response.status_code == 404


def test_there_is_no_letter_until_one_is_generated(auth_client: TestClient):
    application = saved_with_description(auth_client, NOISY, ai_on=False)
    response = auth_client.get(f"{API}/applications/{application['id']}/cover-letter")
    assert response.status_code == 404
