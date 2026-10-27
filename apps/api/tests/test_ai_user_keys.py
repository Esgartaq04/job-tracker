"""Every AI call runs on the key of the user it's for, and each way that key can fail
reaches the user as its own status and message — never a 401, which signs them out."""

import uuid

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
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


def test_one_users_call_never_runs_on_another_users_key(auth_client, real_keys):
    bob_key = "sk-ant-api03-" + "z" * 40
    with TestClient(app) as bob:
        token = bob.post(
            f"{API}/auth/register",
            json={"email": "bob@example.com", "password": "another-long-pass"},
        ).json()["access_token"]
        bob.headers["Authorization"] = f"Bearer {token}"
        assert bob.put(f"{API}/ai-key", json={"api_key": bob_key}).status_code == 200
        # Alice's is the key saved most recently, so "the latest key" would be hers.
        assert auth_client.put(f"{API}/ai-key", json={"api_key": ALICE_KEY}).status_code == 200

        app_ = saved_with_description(bob, fake=real_keys)
        real_keys.reply("About the role ...")
        response = bob.post(f"{API}/applications/{app_['id']}/clean-description")

    assert response.status_code == 200, response.text
    assert real_keys.keys and real_keys.keys[-1] == bob_key
    assert ALICE_KEY not in real_keys.keys


def test_a_call_on_a_replaced_key_leaves_the_new_key_ok(
    auth_client, real_keys, db_session, monkeypatch
):
    """A call loaded the old key, and the user saved a new one while it waited on Claude.
    Claude refusing the old key must not mark the new one rejected."""
    auth_client.put(f"{API}/ai-key", json={"api_key": ALICE_KEY})
    me = uuid.UUID(auth_client.get(f"{API}/auth/me").json()["id"])
    stale = ai.client_for(db_session, me)

    new_key = "sk-ant-api03-" + "b" * 40
    assert auth_client.put(f"{API}/ai-key", json={"api_key": new_key}).status_code == 200

    def refuse(**_):
        raise auth_error()

    monkeypatch.setattr(real_keys.messages, "create", refuse)
    with pytest.raises(ai.AIKeyRejected):
        stale.messages.create(model="m", max_tokens=1, messages=[])

    state = auth_client.get(f"{API}/ai-key").json()
    assert state["status"] == "ok" and state["hint"] == "…" + new_key[-4:]
    assert real_keys.keys == [ALICE_KEY]


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


#: What Anthropic says when an account reaches the spend limit its owner set.
USAGE_LIMIT = (
    "You have reached your specified API usage limits. "
    "You will regain access on 2026-11-01 at 00:00 UTC."
)


def _bad_request(message: str) -> anthropic.BadRequestError:
    request = httpx.Request("POST", "https://x")
    return anthropic.BadRequestError(
        message, response=httpx.Response(400, request=request), body=None
    )


def _rate_limited() -> anthropic.RateLimitError:
    request = httpx.Request("POST", "https://x")
    return anthropic.RateLimitError(
        "slow down", response=httpx.Response(429, request=request), body=None
    )


@pytest.mark.parametrize(
    "make_error,status,detail",
    [
        pytest.param(_rate_limited, 429, ai.RATE_LIMITED, id="rate_limit"),
        pytest.param(
            lambda: _bad_request("Your credit balance is too low"),
            402,
            ai.OUT_OF_CREDIT,
            id="credit",
        ),
        pytest.param(lambda: _bad_request(USAGE_LIMIT), 402, ai.SPEND_LIMIT, id="spend_limit"),
    ],
)
def test_account_limits_are_reported_as_the_users(
    auth_client, fake_ai, monkeypatch, make_error, status, detail
):
    app = saved_with_description(auth_client, fake=fake_ai)
    err = make_error()

    def fail(**_):
        raise err

    monkeypatch.setattr(fake_ai.messages, "create", fail)
    response = auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert response.status_code == status and response.json()["detail"] == detail


@pytest.mark.parametrize(
    "make_error,kind",
    [
        pytest.param(lambda: _bad_request(USAGE_LIMIT), "spend_limit", id="usage_limit"),
        pytest.param(
            lambda: _bad_request("Your credit balance is too low to access the API"),
            "credit",
            id="credit_balance",
        ),
        pytest.param(lambda: _bad_request("max_tokens: too large"), "other", id="other_400"),
    ],
)
def test_sdk_error_kind_tells_a_spend_limit_from_an_empty_account(make_error, kind):
    assert ai.sdk_error_kind(make_error()) == kind


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
