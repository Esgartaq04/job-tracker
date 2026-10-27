import anthropic
import httpx
import pytest

from src.core.config import settings
from src.models import UserAIKey
from src.services import ai_keys

KEY = "sk-ant-api03-" + "k" * 40


def _status_error(cls, status: int):
    response = httpx.Response(status, request=httpx.Request("GET", "https://x"))
    return cls("nope", response=response, body=None)


def test_normalize_trims_paste_whitespace():
    assert ai_keys.normalize(f"  {KEY}\n") == KEY


def test_normalize_accepts_the_redactors_whole_alphabet():
    key = "sk-ant-api03-AbC_d-Ef0123456789" + "z" * 10
    assert ai_keys.normalize(key) == key


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "sk-proj-abc",
        "sk-ant-",
        "sk-ant-ab cd" + "x" * 20,
        "sk-ant-" + "x" * 400,
        # Outside the log redactor's alphabet, a key could ride an error trace past it.
        "sk-ant-" + "a" * 10 + "\x00" + "b" * 20,
        "sk-ant-" + "a" * 10 + "." + "b" * 20,
    ],
)
def test_normalize_rejects_what_is_not_a_claude_key(bad):
    with pytest.raises(ai_keys.KeyFormatError):
        ai_keys.normalize(bad)


def test_format_error_never_echoes_the_input():
    bad = "sk-proj-" + "s" * 30
    with pytest.raises(ai_keys.KeyFormatError) as caught:
        ai_keys.normalize(bad)
    assert bad not in str(caught.value)
    assert str(caught.value) == (
        "That doesn't look like a Claude API key. It should start with sk-ant-."
    )


def test_hint_is_last_four():
    assert ai_keys.hint_for(KEY) == "…kkkk"


def test_save_stores_ciphertext_not_the_key(db_session, user):
    row = ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    assert KEY not in row.ciphertext
    assert row.hint == "…kkkk"
    assert row.status == "ok"
    assert row.verified_at is not None
    assert ai_keys.read_key(db_session, user.id) == KEY


def test_saving_again_replaces_and_clears_rejected(db_session, user):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    ai_keys.mark_rejected(db_session, user.id)
    assert ai_keys.get_row(db_session, user.id).status == "rejected"
    new = "sk-ant-api03-" + "n" * 40
    ai_keys.save_key(db_session, user.id, new)
    db_session.commit()
    assert db_session.query(UserAIKey).count() == 1
    assert ai_keys.get_row(db_session, user.id).status == "ok"
    assert ai_keys.read_key(db_session, user.id) == new


def test_read_ignores_status(db_session, user):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    ai_keys.mark_rejected(db_session, user.id)
    assert ai_keys.read_key(db_session, user.id) == KEY


def test_mark_rejected_commits_the_callers_session(db_session, user):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    ai_keys.mark_rejected(db_session, user.id)
    db_session.rollback()  # nothing left pending: the flag must already be committed
    assert ai_keys.get_row(db_session, user.id).status == "rejected"


def test_mark_rejected_without_a_row_is_a_no_op(db_session, user):
    ai_keys.mark_rejected(db_session, user.id)
    assert ai_keys.get_row(db_session, user.id) is None


def test_a_loaded_key_does_not_show_in_its_repr(db_session, user):
    from src.services import ai

    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    saved = ai.user_key(db_session, user.id)
    assert saved.key == KEY
    assert KEY not in repr(saved) and KEY not in str(saved)


def test_mark_rejected_with_the_key_in_use_rejects_it(db_session, user):
    sealed = ai_keys.save_key(db_session, user.id, KEY).ciphertext
    db_session.commit()
    ai_keys.mark_rejected(db_session, user.id, ciphertext=sealed)
    assert ai_keys.get_row(db_session, user.id).status == "rejected"


def test_mark_rejected_leaves_a_key_saved_since_alone(db_session, user):
    from src.models import LLMCall
    from src.services import ai

    stale = ai_keys.save_key(db_session, user.id, KEY).ciphertext
    db_session.commit()
    new = "sk-ant-api03-" + "n" * 40
    ai_keys.save_key(db_session, user.id, new)
    db_session.commit()

    ai.reserve_call(db_session, user.id, "cleanup")
    ai_keys.mark_rejected(db_session, user.id, ciphertext=stale)
    db_session.rollback()  # it still commits the caller's work, match or not

    assert ai_keys.get_row(db_session, user.id).status == "ok"
    assert ai_keys.read_key(db_session, user.id) == new
    assert db_session.query(LLMCall).count() == 1


def test_mark_rejected_checks_the_table_not_this_sessions_copy(db_session, user):
    """The replacement is saved by another request, so this session's copy of the row
    still holds the old ciphertext."""
    from src.core.db import SessionLocal

    stale = ai_keys.save_key(db_session, user.id, KEY).ciphertext
    db_session.commit()
    assert ai_keys.get_row(db_session, user.id).ciphertext == stale  # loaded here

    new = "sk-ant-api03-" + "n" * 40
    other = SessionLocal()
    try:
        ai_keys.save_key(other, user.id, new)
        other.commit()
    finally:
        other.close()

    ai_keys.mark_rejected(db_session, user.id, ciphertext=stale)
    assert ai_keys.get_row(db_session, user.id).status == "ok"
    assert ai_keys.read_key(db_session, user.id) == new


def test_no_row_reads_as_no_key(db_session, user):
    assert ai_keys.get_row(db_session, user.id) is None
    assert ai_keys.read_key(db_session, user.id) is None


def test_unreadable_row_reads_as_no_key(db_session, user, monkeypatch, caplog):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    monkeypatch.setattr(settings, "ai_key_secret", "rotated")
    with caplog.at_level("WARNING"):
        assert ai_keys.read_key(db_session, user.id) is None
    assert str(user.id) in caplog.text
    assert KEY not in caplog.text


def test_an_unreadable_key_is_reported_once_per_user(db_session, user, monkeypatch, caplog):
    """Every page load asks for the key's state, and an unreadable row stays unreadable
    until the user saves a new key: one line says so, not one per request."""
    from src.core.security import hash_password
    from src.models import User

    other = User(email="other@example.com", password_hash=hash_password("y" * 12))
    db_session.add(other)
    db_session.commit()
    for someone in (user, other):
        ai_keys.save_key(db_session, someone.id, KEY)
    db_session.commit()
    monkeypatch.setattr(settings, "ai_key_secret", "rotated")

    with caplog.at_level("WARNING", logger="src.services.ai_keys"):
        for _ in range(3):
            assert ai_keys.read_key(db_session, user.id) is None
            assert ai_keys.read_key(db_session, other.id) is None

    warned = [r.getMessage() for r in caplog.records if r.name == "src.services.ai_keys"]
    assert len(warned) == 2
    assert str(user.id) in warned[0] and str(other.id) in warned[1]
    assert KEY not in caplog.text


def test_delete(db_session, user):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    ai_keys.delete_key(db_session, user.id)
    db_session.commit()
    assert ai_keys.get_row(db_session, user.id) is None


def test_delete_without_a_row_is_a_no_op(db_session, user):
    ai_keys.delete_key(db_session, user.id)
    db_session.commit()
    assert ai_keys.get_row(db_session, user.id) is None


def test_deleting_the_user_deletes_the_key(db_session, user):
    ai_keys.save_key(db_session, user.id, KEY)
    db_session.commit()
    user_id = user.id
    db_session.delete(user)
    db_session.commit()
    assert ai_keys.get_row(db_session, user_id) is None


def test_verify_passes_the_key_to_the_seam(monkeypatch):
    seen = []
    monkeypatch.setattr(ai_keys, "_models_list", seen.append)
    ai_keys.verify(KEY)
    assert seen == [KEY]


@pytest.mark.parametrize(
    "error",
    [
        _status_error(anthropic.AuthenticationError, 401),
        _status_error(anthropic.PermissionDeniedError, 403),
    ],
)
def test_verify_maps_auth_failure(monkeypatch, error):
    def boom(api_key):
        raise error

    monkeypatch.setattr(ai_keys, "_models_list", boom)
    with pytest.raises(ai_keys.KeyNotAccepted) as caught:
        ai_keys.verify(KEY)
    assert str(caught.value) == "Claude didn't accept this key."


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=httpx.Request("GET", "https://x")),
        _status_error(anthropic.RateLimitError, 429),
        _status_error(anthropic.InternalServerError, 500),
    ],
)
def test_verify_maps_every_other_failure_to_cant_check(monkeypatch, error):
    def boom(api_key):
        raise error

    monkeypatch.setattr(ai_keys, "_models_list", boom)
    with pytest.raises(ai_keys.KeyCheckFailed) as caught:
        ai_keys.verify(KEY)
    assert str(caught.value) == "Couldn't check this key with Claude. Try again."
