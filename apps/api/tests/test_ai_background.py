"""Background ingestion and clean-up without a usable key: the skipped AI step is
recorded, no clean-up is queued for a user who can't run one, and a key Claude refuses
in the middle of an ingest costs the AI step and nothing else."""

import pytest

from src.models import Application
from src.schemas.extraction import RawPosting
from src.services import ai, ai_keys
from src.services.ingestion import pipeline
from tests.conftest import auth_error

API = "/api/v1"
KEY = "sk-ant-api03-" + "r" * 40
LONG_PAGE = "<html><body><main>" + "We are hiring someone great. " * 40 + "</main></body></html>"
URL = "https://example.com/jobs/1"


@pytest.fixture
def served_page(monkeypatch) -> None:
    """The background ingest fetches `URL`; serve it LONG_PAGE rather than the internet."""
    monkeypatch.setattr(pipeline, "fetch_url", lambda url: RawPosting(url=url, html=LONG_PAGE))


def a_saved_card(db_session, user) -> Application:
    application = Application(user_id=user.id, source_url=URL, canonical_url=URL)
    db_session.add(application)
    db_session.commit()
    return application


def test_tier4_without_a_client_is_recorded_as_skipped():
    outcome = pipeline.run_pipeline(URL, html=LONG_PAGE, llm_client=None)
    assert outcome.llm_skipped is True and "llm" not in outcome.tiers_attempted


def test_pasted_text_without_a_client_is_recorded_as_skipped():
    outcome = pipeline.run_pipeline(URL, text="About the role. " * 30, llm_client=None)
    assert outcome.llm_skipped is True and "llm" not in outcome.tiers_attempted


def test_nothing_is_skipped_when_tier4_never_applied():
    # A page whose JSON-LD already has company, title and description never needs the model.
    complete = (
        "<html><head><script type='application/ld+json'>"
        '{"@context":"https://schema.org","@type":"JobPosting","title":"Backend Intern",'
        '"description":"' + "Build the ledger. " * 30 + '",'
        '"hiringOrganization":{"@type":"Organization","name":"Ramp"}}'
        "</script></head><body></body></html>"
    )
    outcome = pipeline.run_pipeline(URL, html=complete, llm_client=None)
    assert outcome.llm_skipped is False


def test_a_client_that_ran_is_not_recorded_as_skipped(db_session, user, real_keys):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    real_keys.parsed(None)
    outcome = pipeline.run_pipeline(
        URL, html=LONG_PAGE, llm_client=ai.client_for(db_session, user.id)
    )
    assert outcome.llm_skipped is False and "llm" in outcome.tiers_attempted


def test_no_key_lands_in_extraction_meta(db_session, user):
    application = Application(user_id=user.id, source_url=URL, canonical_url=URL)
    db_session.add(application)
    db_session.flush()
    outcome = pipeline.run_pipeline(application.source_url, html=LONG_PAGE, llm_client=None)
    pipeline.apply_outcome(db_session, application, outcome)
    assert application.extraction_meta["llm"] == "no_key"


def test_a_later_ingest_with_a_key_clears_the_no_key_note(db_session, user):
    application = Application(
        user_id=user.id,
        source_url=URL,
        canonical_url=URL,
        extraction_meta={"llm": "no_key"},
    )
    db_session.add(application)
    db_session.flush()
    outcome = pipeline.IngestOutcome(llm_skipped=False)
    pipeline.apply_outcome(db_session, application, outcome)
    assert "llm" not in application.extraction_meta


def test_no_cleanup_is_queued_without_a_key(auth_client, cleanups):
    auth_client.post(
        f"{API}/ingest/from-text",
        json={"text": "About the role " * 30, "company": "Ramp", "title": "Intern"},
    )
    assert cleanups == []


def test_a_cleanup_is_queued_once_the_user_has_a_key(auth_client, real_keys, cleanups):
    auth_client.put(f"{API}/ai-key", json={"api_key": KEY})
    real_keys.parsed(None)
    response = auth_client.post(
        f"{API}/ingest/from-text",
        json={"text": "About the role " * 30, "company": "Ramp", "title": "Intern"},
    )
    assert [str(i) for i in cleanups] == [response.json()["id"]]


def test_no_cleanup_is_queued_from_the_extension_without_a_key(auth_client, cleanups):
    response = auth_client.post(
        f"{API}/ingest/from-dom",
        json={"url": URL, "html": LONG_PAGE},
    )
    assert response.status_code == 200, response.text
    assert response.json()["extraction_meta"]["llm"] == "no_key"
    assert cleanups == []


def test_no_cleanup_is_queued_after_a_background_ingest_without_a_key(
    db_session, user, served_page, cleanups
):
    application = a_saved_card(db_session, user)

    pipeline.ingest_application(db_session, application.id)

    assert cleanups == []
    assert application.extraction_meta["llm"] == "no_key"


def test_a_cleanup_is_queued_after_a_background_ingest_with_a_key(
    db_session, user, real_keys, served_page, cleanups
):
    ai_keys.save_key(db_session, user.id, KEY)
    application = a_saved_card(db_session, user)
    real_keys.parsed(None)

    pipeline.ingest_application(db_session, application.id)

    assert cleanups == [application.id]


def test_a_key_revoked_mid_ingest_still_finishes(db_session, user, real_keys, monkeypatch):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()

    def refuse(**_):
        raise auth_error()

    monkeypatch.setattr(real_keys.messages, "parse", refuse)
    client = ai.client_for(db_session, user.id)
    outcome = pipeline.run_pipeline(URL, html=LONG_PAGE, llm_client=client)
    assert outcome.posting is not None  # generic tier still produced the card
    db_session.expire_all()
    assert ai_keys.get_row(db_session, user.id).status == "rejected"


def test_a_key_revoked_mid_background_ingest_queues_no_cleanup(
    db_session, user, real_keys, served_page, cleanups, monkeypatch
):
    ai_keys.save_key(db_session, user.id, KEY)
    application = a_saved_card(db_session, user)

    def refuse(**_):
        raise auth_error()

    monkeypatch.setattr(real_keys.messages, "parse", refuse)

    pipeline.ingest_application(db_session, application.id)

    assert application.description_raw, "the card was still filled in"
    assert ai_keys.get_row(db_session, user.id).status == "rejected"
    assert cleanups == []
