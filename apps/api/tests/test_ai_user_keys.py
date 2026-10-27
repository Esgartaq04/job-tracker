"""Every AI call runs on the key of the user it's for, and each way that key can fail
reaches the user as its own status and message — never a 401, which signs them out."""

import uuid

import anthropic
import httpx
import pytest

from src.services import ai, ai_keys
from tests.conftest import auth_error
from tests.test_ai import saved_with_description

API = "/api/v1"
ALICE_KEY = "sk-ant-api03-" + "a" * 40


def test_clean_up_without_a_key_is_428(auth_client):
    app = saved_with_description(auth_client)
    response = auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert response.status_code == 428 and response.json()["detail"] == ai.MISSING_KEY


def test_calls_use_the_callers_own_key(auth_client, real_keys):
    auth_client.put(f"{API}/ai-key", json={"api_key": ALICE_KEY})
    app = saved_with_description(auth_client, fake=real_keys)
    real_keys.reply("About the role ...")
    auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert set(real_keys.keys) == {ALICE_KEY}


def test_a_rejected_key_flips_status_and_is_424(auth_client, real_keys, monkeypatch):
    auth_client.put(f"{API}/ai-key", json={"api_key": ALICE_KEY})
    app = saved_with_description(auth_client, fake=real_keys)

    def refuse(**_):
        raise auth_error()

    monkeypatch.setattr(real_keys.messages, "create", refuse)
    response = auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert response.status_code == 424 and response.json()["detail"] == ai.REJECTED_KEY
    assert auth_client.get(f"{API}/ai-key").json()["status"] == "rejected"
    # and the next call short-circuits without reaching Claude
    again = auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert again.status_code == 424


def test_replacing_a_rejected_key_works_again(auth_client, real_keys, db_session):
    auth_client.put(f"{API}/ai-key", json={"api_key": ALICE_KEY})
    me = uuid.UUID(auth_client.get(f"{API}/auth/me").json()["id"])
    ai_keys.mark_rejected(db_session, me)
    new_key = "sk-ant-api03-" + "b" * 40
    auth_client.put(f"{API}/ai-key", json={"api_key": new_key})
    app = saved_with_description(auth_client, fake=real_keys)
    real_keys.reply("About the role ...")
    assert auth_client.post(f"{API}/applications/{app['id']}/clean-description").status_code == 200
    assert real_keys.keys[-1] == new_key


@pytest.mark.parametrize(
    "kind,status,detail",
    [
        ("rate_limit", 429, ai.RATE_LIMITED),
        ("credit", 402, ai.OUT_OF_CREDIT),
    ],
)
def test_account_limits_are_reported_as_the_users(
    auth_client, fake_ai, monkeypatch, kind, status, detail
):
    app = saved_with_description(auth_client, fake=fake_ai)
    req = httpx.Request("POST", "https://x")
    err = (
        anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)
        if kind == "rate_limit"
        else anthropic.BadRequestError(
            "Your credit balance is too low", response=httpx.Response(400, request=req), body=None
        )
    )

    def fail(**_):
        raise err

    monkeypatch.setattr(fake_ai.messages, "create", fail)
    response = auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert response.status_code == status and response.json()["detail"] == detail


def test_any_other_claude_failure_is_a_502_with_plain_copy(auth_client, fake_ai, monkeypatch):
    app = saved_with_description(auth_client, fake=fake_ai)
    err = anthropic.InternalServerError(
        "overloaded",
        response=httpx.Response(500, request=httpx.Request("POST", "https://x")),
        body=None,
    )

    def fail(**_):
        raise err

    monkeypatch.setattr(fake_ai.messages, "create", fail)
    response = auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert response.status_code == 502 and response.json()["detail"] == ai.AI_CALL_FAILED


def test_no_ai_error_is_ever_401(auth_client, real_keys, monkeypatch):
    auth_client.put(f"{API}/ai-key", json={"api_key": ALICE_KEY})
    app = saved_with_description(auth_client, fake=real_keys)

    def refuse(**_):
        raise auth_error()

    monkeypatch.setattr(real_keys.messages, "create", refuse)
    assert auth_client.post(f"{API}/applications/{app['id']}/clean-description").status_code != 401
