import uuid

import pytest

from src.core import crypto
from src.core.config import settings

ALICE, BOB = uuid.uuid4(), uuid.uuid4()
KEY = "sk-ant-api03-" + "x" * 40


def test_round_trip():
    sealed = crypto.seal(ALICE, KEY)
    assert sealed.startswith("v1:") and KEY not in sealed
    assert crypto.open_sealed(ALICE, sealed) == KEY


def test_two_seals_differ():  # fresh nonce each time
    assert crypto.seal(ALICE, KEY) != crypto.seal(ALICE, KEY)


def test_another_users_id_cannot_open_it():
    with pytest.raises(crypto.SealError):
        crypto.open_sealed(BOB, crypto.seal(ALICE, KEY))


def test_a_changed_secret_cannot_open_it(monkeypatch):
    sealed = crypto.seal(ALICE, KEY)
    monkeypatch.setattr(settings, "ai_key_secret", "a-different-secret")
    with pytest.raises(crypto.SealError):
        crypto.open_sealed(ALICE, sealed)


@pytest.mark.parametrize("junk", ["", "v1:", "v2:abc", "v1:!!!", "plain"])
def test_junk_raises_seal_error(junk):
    with pytest.raises(crypto.SealError):
        crypto.open_sealed(ALICE, junk)


def test_production_without_a_secret_refuses_to_start(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "ai_key_secret", None)
    with pytest.raises(RuntimeError, match="AI_KEY_SECRET"):
        crypto.check_configured()


def test_local_without_a_secret_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "environment", "local")
    monkeypatch.setattr(settings, "ai_key_secret", None)
    crypto.check_configured()
