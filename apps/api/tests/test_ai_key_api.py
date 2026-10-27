import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.core.config import settings
from src.main import app
from src.models import UserAIKey
from src.routers import ai_key
from src.services import ai_keys

API = "/api/v1/ai-key"
KEY = "sk-ant-api03-" + "s" * 36 + "WXYZ"
EMPTY = {"has_key": False, "hint": None, "status": None, "updated_at": None}
BAD_FORMAT = "That doesn't look like a Claude API key. It should start with sk-ant-."
TOO_MANY = "Too many key attempts. Try again in an hour."


@pytest.fixture
def verifies(monkeypatch):
    monkeypatch.setattr(ai_keys, "_models_list", lambda api_key: None)


def test_starts_empty(auth_client):
    assert auth_client.get(API).json() == EMPTY


def test_save_returns_hint_never_key(auth_client, verifies):
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 200
    assert KEY not in response.text and response.json()["hint"] == "…WXYZ"
    got = auth_client.get(API)
    assert got.json()["has_key"] is True and KEY not in got.text


def test_saved_status_is_ok_and_dated(auth_client, verifies):
    body = auth_client.put(API, json={"api_key": KEY}).json()
    assert body["has_key"] is True and body["status"] == "ok"
    assert body["updated_at"] is not None
    assert auth_client.get(API).json() == body


def test_paste_whitespace_is_trimmed(auth_client, verifies):
    response = auth_client.put(API, json={"api_key": f"  {KEY}\n"})
    assert response.status_code == 200 and response.json()["hint"] == "…WXYZ"


def test_the_key_is_stored_sealed(auth_client, verifies, db_session):
    auth_client.put(API, json={"api_key": KEY})
    row = db_session.query(UserAIKey).one()
    assert KEY not in row.ciphertext and row.hint == "…WXYZ"


def test_bad_format_is_422_without_echo(auth_client):
    bad = "sk-ant-has space" + "q" * 30
    response = auth_client.put(API, json={"api_key": bad})
    assert response.status_code == 422 and "qqqq" not in response.text
    assert response.json()["detail"] == BAD_FORMAT


def test_oversized_body_is_422_without_echo(auth_client):
    huge = "sk-ant-" + "z" * 5000
    response = auth_client.put(API, json={"api_key": huge})
    assert response.status_code == 422 and "zzzzzzzz" not in response.text
    assert response.json()["detail"] == BAD_FORMAT


def test_a_key_with_control_characters_is_422_without_echo(auth_client):
    bad = "sk-ant-" + "p" * 20 + "\x00" + "r" * 20
    response = auth_client.put(API, json={"api_key": bad})
    assert (
        response.status_code == 422 and "pppp" not in response.text and "rrrr" not in response.text
    )
    assert response.json()["detail"] == BAD_FORMAT


def test_a_body_without_a_string_key_is_422(auth_client):
    assert auth_client.put(API, json={}).status_code == 422
    assert auth_client.put(API, json={"api_key": 12345}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"api_key": [KEY]}, id="key_in_a_list"),
        pytest.param({"apiKey": KEY}, id="misnamed_field"),
        pytest.param([KEY], id="bare_list"),
    ],
)
def test_a_malformed_body_is_422_without_echoing_the_key(auth_client, body):
    response = auth_client.put(API, json=body)
    assert response.status_code == 422
    assert KEY not in response.text and "ssssssss" not in response.text
    # Still FastAPI's shape, minus what can quote the input back.
    errors = response.json()["detail"]
    assert isinstance(errors, list) and errors
    for error in errors:
        assert {"type", "loc", "msg"} <= error.keys()
        assert "input" not in error and "ctx" not in error


def test_other_routes_keep_the_default_422(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": "pw-echoed-back"}
    )
    assert response.status_code == 422
    assert any("input" in error for error in response.json()["detail"])


def test_claude_refuses_key(auth_client, monkeypatch):
    def refuse(api_key):
        raise ai_keys.KeyNotAccepted("Claude didn't accept this key.")

    monkeypatch.setattr(ai_keys, "verify", refuse)
    response = auth_client.put(API, json={"api_key": KEY})
    assert (
        response.status_code == 422
        and response.json()["detail"] == "Claude didn't accept this key."
    )
    assert KEY not in response.text
    assert auth_client.get(API).json()["has_key"] is False


def test_claude_unreachable(auth_client, monkeypatch):
    def down(api_key):
        raise ai_keys.KeyCheckFailed("Couldn't check this key with Claude. Try again.")

    monkeypatch.setattr(ai_keys, "verify", down)
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 502
    assert response.json()["detail"] == "Couldn't check this key with Claude. Try again."
    assert KEY not in response.text
    assert auth_client.get(API).json()["has_key"] is False


def test_real_verify_maps_through_the_endpoint(auth_client, monkeypatch):
    request = httpx.Request("GET", "https://x")

    def reject(api_key):
        raise anthropic.AuthenticationError(
            "nope", response=httpx.Response(401, request=request), body=None
        )

    monkeypatch.setattr(ai_keys, "_models_list", reject)
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 422
    assert response.json()["detail"] == "Claude didn't accept this key."

    def unreachable(api_key):
        raise anthropic.APIConnectionError(request=request)

    monkeypatch.setattr(ai_keys, "_models_list", unreachable)
    assert auth_client.put(API, json={"api_key": KEY}).status_code == 502


def test_a_refused_key_leaves_the_saved_one_alone(auth_client, verifies, monkeypatch):
    auth_client.put(API, json={"api_key": KEY})

    def refuse(api_key):
        raise ai_keys.KeyNotAccepted("Claude didn't accept this key.")

    monkeypatch.setattr(ai_keys, "verify", refuse)
    other = "sk-ant-api03-" + "o" * 36 + "ABCD"
    assert auth_client.put(API, json={"api_key": other}).status_code == 422
    got = auth_client.get(API).json()
    assert got["has_key"] is True and got["hint"] == "…WXYZ"


def test_replacing_a_rejected_key_clears_the_flag(auth_client, verifies, db_session):
    auth_client.put(API, json={"api_key": KEY})
    row = db_session.query(UserAIKey).one()
    ai_keys.mark_rejected(db_session, row.user_id)
    got = auth_client.get(API).json()
    assert got["has_key"] is True and got["status"] == "rejected" and got["hint"] == "…WXYZ"

    replacement = "sk-ant-api03-" + "n" * 36 + "NEW1"
    saved = auth_client.put(API, json={"api_key": replacement}).json()
    assert saved["status"] == "ok" and saved["hint"] == "…NEW1"
    assert auth_client.get(API).json()["status"] == "ok"


def test_delete(auth_client, verifies):
    auth_client.put(API, json={"api_key": KEY})
    assert auth_client.delete(API).status_code == 204
    assert auth_client.get(API).json()["has_key"] is False


def test_delete_without_a_key_is_204(auth_client):
    assert auth_client.delete(API).status_code == 204


def test_rotated_secret_reads_as_no_key(auth_client, verifies, monkeypatch):
    auth_client.put(API, json={"api_key": KEY})
    monkeypatch.setattr(settings, "ai_key_secret", "rotated")
    assert auth_client.get(API).json() == EMPTY


def test_saving_over_an_unreadable_key_replaces_it(auth_client, verifies, monkeypatch):
    auth_client.put(API, json={"api_key": KEY})
    monkeypatch.setattr(settings, "ai_key_secret", "rotated")
    assert auth_client.put(API, json={"api_key": KEY}).status_code == 200
    assert auth_client.get(API).json()["has_key"] is True


def test_every_endpoint_needs_a_session(client):
    assert client.get(API).status_code == 401
    assert client.put(API, json={"api_key": KEY}).status_code == 401
    assert client.delete(API).status_code == 401


def test_key_problems_are_never_401(auth_client, monkeypatch):
    """The web client treats any 401 as signed out and drops the session."""

    def refuse(api_key):
        raise ai_keys.KeyNotAccepted("Claude didn't accept this key.")

    monkeypatch.setattr(ai_keys, "verify", refuse)
    codes = {
        auth_client.put(API, json={"api_key": "sk-proj-nope"}).status_code,
        auth_client.put(API, json={"api_key": KEY}).status_code,
    }
    assert 401 not in codes


def test_eleventh_attempt_in_an_hour_is_429(auth_client, verifies):
    for _ in range(10):
        assert auth_client.put(API, json={"api_key": KEY}).status_code == 200
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 429 and response.json()["detail"] == TOO_MANY


def test_malformed_attempts_count_against_the_limit(auth_client, verifies):
    for _ in range(10):
        assert auth_client.put(API, json={"api_key": "sk-proj-nope"}).status_code == 422
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 429 and response.json()["detail"] == TOO_MANY


def test_refused_attempts_count_against_the_limit(auth_client, monkeypatch):
    def refuse(api_key):
        raise ai_keys.KeyNotAccepted("Claude didn't accept this key.")

    monkeypatch.setattr(ai_keys, "verify", refuse)
    for _ in range(10):
        assert auth_client.put(API, json={"api_key": KEY}).status_code == 422
    assert auth_client.put(API, json={"api_key": KEY}).status_code == 429


def test_reading_and_deleting_are_not_limited(auth_client, verifies):
    for _ in range(10):
        auth_client.put(API, json={"api_key": KEY})
    assert auth_client.put(API, json={"api_key": KEY}).status_code == 429
    assert auth_client.get(API).status_code == 200
    assert auth_client.delete(API).status_code == 204


def test_a_limited_attempt_does_not_reach_claude(auth_client, monkeypatch):
    calls = []
    monkeypatch.setattr(ai_keys, "_models_list", lambda api_key: calls.append(api_key))
    for _ in range(11):
        auth_client.put(API, json={"api_key": KEY})
    assert len(calls) == 10


def test_keys_are_per_user(client, auth_client, verifies):
    auth_client.put(API, json={"api_key": KEY})
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "another-long-pass"},
    ).json()
    response = client.get(API, headers={"Authorization": f"Bearer {other['access_token']}"})
    assert response.json()["has_key"] is False


def test_the_limit_is_per_user(auth_client, verifies):
    for _ in range(11):
        auth_client.put(API, json={"api_key": KEY})
    with TestClient(app) as other_client:
        token = other_client.post(
            "/api/v1/auth/register",
            json={"email": "other@example.com", "password": "another-long-pass"},
        ).json()["access_token"]
        response = other_client.put(
            API, json={"api_key": KEY}, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200


def test_a_lost_first_save_race_retries_once_as_an_update(auth_client, verifies, monkeypatch):
    """Two first-time PUTs can both see no row and race on the primary key. The loser
    gets an IntegrityError, rolls back, and saves again over the winner's row."""
    real_save = ai_keys.save_key
    calls = []

    def racing_save(db, user_id, api_key):
        calls.append(api_key)
        row = real_save(db, user_id, api_key)
        if len(calls) == 1:
            raise IntegrityError("INSERT INTO user_ai_keys", {}, Exception("duplicate key"))
        return row

    monkeypatch.setattr(ai_keys, "save_key", racing_save)
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 200 and response.json()["hint"] == "…WXYZ"
    assert len(calls) == 2
    assert auth_client.get(API).json()["has_key"] is True


def test_a_second_integrity_error_is_not_swallowed(auth_client, verifies, monkeypatch):
    calls = []

    def always_conflicts(db, user_id, api_key):
        calls.append(api_key)
        raise IntegrityError("INSERT INTO user_ai_keys", {}, Exception("duplicate key"))

    monkeypatch.setattr(ai_keys, "save_key", always_conflicts)
    with pytest.raises(IntegrityError):
        auth_client.put(API, json={"api_key": KEY})
    assert len(calls) == 2


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_window_allows_its_limit_then_refuses():
    window = ai_key.SlidingWindow(limit=3, seconds=60, clock=FakeClock())
    assert [window.allow("a") for _ in range(4)] == [True, True, True, False]


def test_window_is_per_key():
    window = ai_key.SlidingWindow(limit=1, seconds=60, clock=FakeClock())
    assert window.allow("a") is True
    assert window.allow("a") is False
    assert window.allow("b") is True


def test_window_slides():
    clock = FakeClock()
    window = ai_key.SlidingWindow(limit=2, seconds=60, clock=clock)
    assert window.allow("a") is True  # t=0
    clock.now += 30
    assert window.allow("a") is True  # t=30
    assert window.allow("a") is False
    clock.now += 30  # t=60: the first attempt has aged out, the second hasn't
    assert window.allow("a") is True
    assert window.allow("a") is False
    clock.now += 31  # t=91: the second has aged out too
    assert window.allow("a") is True


def test_refusals_do_not_extend_the_window():
    clock = FakeClock()
    window = ai_key.SlidingWindow(limit=1, seconds=60, clock=clock)
    assert window.allow("a") is True
    for _ in range(5):
        clock.now += 10
        assert window.allow("a") is False
    clock.now += 11  # t=61, one minute after the only counted attempt
    assert window.allow("a") is True


def test_window_reset_forgets_everyone():
    window = ai_key.SlidingWindow(limit=1, seconds=60, clock=FakeClock())
    window.allow("a")
    window.reset()
    assert window.allow("a") is True


def test_the_endpoint_limit_is_ten_per_hour():
    assert ai_key.attempts.limit == 10 and ai_key.attempts.seconds == 3600
