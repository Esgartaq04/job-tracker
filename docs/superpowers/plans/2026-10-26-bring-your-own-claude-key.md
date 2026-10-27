# Bring Your Own Claude Key — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every user stores their own Anthropic API key, encrypted on the server, and
every AI feature runs on the key of the user it runs for. The server-wide key and the
monthly cap go away.

**Architecture:**
- `src/core/crypto.py` seals keys with AES-256-GCM. The AES key is derived from a new
  `AI_KEY_SECRET`, and the user's id is the associated data.
- `src/services/ai_keys.py` stores, reads and verifies keys in a new `user_ai_keys`
  table.
- `src/services/ai.py` builds a client per user. `UserClient` wraps it and flips the key
  to `rejected` when Claude refuses it.
- The web app gets a key dialog off the 👤 menu, plus "add your key" states on the AI
  surfaces.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pydantic v2, `cryptography`,
`anthropic`, pytest. React + TanStack Query + zustand, vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-26-bring-your-own-claude-key-design.md`

## Global Constraints

- Claude (Anthropic) keys only. No other providers, no shared or fallback key, no
  model picker.
- A key never appears in an API response, log line, error message, arq payload,
  `localStorage`, the zustand stores, or the TanStack Query cache. The only exception is
  the 4-character `hint`.
- No AI error ever returns HTTP **401**. `apps/web/src/api/client.ts` treats 401 as
  "signed out" and drops the session.
- Error statuses:

  | status | meaning |
  |---|---|
  | 428 | key missing |
  | 424 | key rejected |
  | 402 | Claude account out of credit |
  | 429 | Claude account rate-limited |
  | 503 | `anthropic` not importable |
  | 502 | model failed or other SDK error |

  `detail` is always a plain string, because the extension shows it as is.
- Exact copy:
  - Missing: `Add your Claude API key (👤 → Claude API key) to use this.`
  - Rejected: `Claude rejected your saved key. Replace it under 👤 → Claude API key.`
  - Credit: `Your Claude account is out of credit. Add credit at console.anthropic.com, then try again.`
  - Rate limit: `Your Claude account hit its rate limit. Try again in a minute.`
  - PUT, not accepted: `Claude didn't accept this key.`
  - PUT, can't check: `Couldn't check this key with Claude. Try again.`
  - PUT, bad format: `That doesn't look like a Claude API key. It should start with sk-ant-.`
  - PUT, too many attempts: `Too many key attempts. Try again in an hour.`
- Crypto:
  - The stored envelope is `v1:` followed by url-safe base64 of `nonce(12 bytes) ‖ ciphertext`.
  - The AES key is HKDF-SHA256 of `AI_KEY_SECRET`, `length=32`, `salt=None`,
    `info=b"job-tracker ai-key v1"`.
  - The associated data is `user_id.bytes`.
- Outside `environment == "local"`, the API and the worker refuse to start without
  `AI_KEY_SECRET`. Locally the fallback is `"job-tracker-local-dev-only"`, with one
  warning log.
- Both SQLite (tests, local) and Postgres (CI, prod) must pass.
- The API commands, from `apps/api`, must all pass at the end of every task:
  - `pytest -q`
  - `ruff check src tests scripts`
  - `ruff format --check src tests scripts`
- The web commands, from `apps/web`, must pass at the end of every web task:
  - `npm run typecheck`
  - `npm test`
  - `npm run build`

## Review Focus

These five inputs aren't covered by the spec's main path but are the most likely to
bite. Each one has a test pinned in the owning task.

1. **A key pasted with a trailing newline or space** from the Anthropic console is
   accepted after trimming. Internal whitespace is still rejected. (Task 2)
2. **`AI_KEY_SECRET` changed between deploys.** The stored row can't be decrypted, so
   `GET /ai-key` reports `has_key: false` and AI features say "add your key". They
   don't 500 and don't show a stale hint. (Task 3)
3. **Replacing a rejected key** sets `status` back to `ok`, and AI works again on the new
   key. (Task 2, Task 4)
4. **A key revoked while a background ingest runs.** The card still finishes from the
   other tiers, nothing crashes, and the row flips to `rejected`. (Task 5)
5. **Extension autofill with no key.** The plan comes back with a reason AI wasn't used,
   and the side panel shows it, instead of quietly filling fewer fields. (Task 5)

---

### Task 1: Secrets plumbing — encryption, startup check, log redaction, dependencies

**Files:**
- Create: `apps/api/src/core/crypto.py`
- Create: `apps/api/src/core/redact.py`
- Modify: `apps/api/src/core/config.py` (add `ai_key_secret`)
- Modify: `apps/api/src/main.py`: install the redaction filter after
  `logging.basicConfig`, and call `crypto.check_configured()` at the top of `lifespan`
- Modify: `apps/worker/worker.py`: the same two calls in `startup`
- Modify: `apps/api/pyproject.toml`
  - Move `anthropic>=0.40` into `dependencies` and delete the `llm` extra.
  - Add `cryptography>=42` to `dependencies`.
- Modify: `apps/api/Dockerfile:18`: change `pip install ".[llm]"` to `pip install .`
- Modify: `apps/api/tests/test_packaging.py`: replace
  `test_the_image_carries_the_llm_extra` with `test_anthropic_is_a_core_dependency`.
  Task 4 adapts the Tier 4 import test.
- Test: `apps/api/tests/test_crypto.py`, `apps/api/tests/test_redact.py`

**Interfaces:**
- Produces:
  - `crypto.seal(user_id: uuid.UUID, plaintext: str) -> str`
  - `crypto.open_sealed(user_id: uuid.UUID, envelope: str) -> str`, which raises
    `crypto.SealError` on any failure (bad prefix, bad base64, auth tag mismatch)
  - `crypto.check_configured() -> None`
  - `redact.KEY_PATTERN`, `redact.RedactKeys(logging.Filter)`, `redact.install() -> None`
  - `settings.ai_key_secret: str | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_crypto.py
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
```

```python
# tests/test_redact.py
import logging
from src.core import redact

def record(msg, *args):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)

def test_a_key_in_the_message_is_redacted():
    r = record("calling with sk-ant-api03-AbC_123-xyz now")
    assert redact.RedactKeys().filter(r) is True
    assert "AbC_123" not in r.getMessage() and "sk-ant-…redacted" in r.getMessage()

def test_a_key_in_the_args_is_redacted():
    r = record("key=%s", "sk-ant-api03-SECRETSECRET")
    redact.RedactKeys().filter(r)
    assert "SECRETSECRET" not in r.getMessage()

def test_install_puts_the_filter_on_root_handlers():
    redact.install()
    assert any(isinstance(f, redact.RedactKeys)
               for h in logging.getLogger().handlers for f in h.filters)

def test_install_is_idempotent():
    redact.install(); redact.install()
    for h in logging.getLogger().handlers:
        assert sum(isinstance(f, redact.RedactKeys) for f in h.filters) <= 1
```

```python
# tests/test_packaging.py — replaces test_the_image_carries_the_llm_extra
def test_anthropic_is_a_core_dependency():
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    assert any(d.startswith("anthropic") for d in deps)
    assert "llm" not in declared_extras()
```
Use whatever names the file already uses for the pyproject path and the TOML reader.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest tests/test_crypto.py tests/test_redact.py tests/test_packaging.py -q`

Expected: FAIL. `crypto`/`redact` can't be imported, and the packaging assertion fails.

- [ ] **Step 3: Implement**
  - **`crypto.py`:**
    - Use `cryptography.hazmat.primitives.ciphers.aead.AESGCM` and `HKDF`, with the
      constants from Global Constraints.
    - `_secret()` returns `settings.ai_key_secret`, or the local fallback (logging the
      warning once). Derive the AES key per call; it's cheap, and it keeps the
      monkeypatch tests honest.
    - `check_configured()` raises `RuntimeError("AI_KEY_SECRET must be set outside local
      development")` when `settings.environment != "local"` and the secret is unset.
  - **`redact.py`:**
    - `KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")`.
    - The filter rewrites `record.msg` when it's a `str`, and every `str` in
      `record.args` (tuple or dict), then returns `True`.
    - `install()` adds a single instance to every handler on the root, `uvicorn`,
      `uvicorn.error` and `uvicorn.access` loggers, skipping any handler that already
      has one.
  - **Wiring:** do the `main.py` and `worker.py` wiring and the dependency changes listed
    under Files.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `pip install -e ".[dev]" && pytest -q && ruff check src tests scripts && ruff format --check src tests scripts`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api apps/worker
git commit -m "Add key sealing, log redaction, and make anthropic a core dependency"
```

---

### Task 2: Key storage — table, migration, `ai_keys` service

**Files:**
- Create: `apps/api/src/models/user_ai_key.py`. Export `UserAIKey` from
  `src/models/__init__.py`.
- Create: `apps/api/alembic/versions/0003_user_ai_keys.py` (`revision="0003"`,
  `down_revision="0002"`)
- Create: `apps/api/src/services/ai_keys.py`
- Test: `apps/api/tests/test_ai_keys.py`

**Interfaces:**
- Consumes: `crypto.seal`, `crypto.open_sealed`, `crypto.SealError` (Task 1)
- Produces:
  - **Model:** `UserAIKey`, table `user_ai_keys`, with these columns:
    - `user_id`: UUID, PK, FK `users.id` `ON DELETE CASCADE`
    - `ciphertext`: Text, not null
    - `hint`: Text, not null
    - `status`: Text, not null, default `"ok"`
    - `verified_at`, `created_at`, `updated_at`: `TimestampTZ`
  - **Exceptions:** `ai_keys.KeyFormatError(ValueError)`,
    `ai_keys.KeyNotAccepted(Exception)`, `ai_keys.KeyCheckFailed(Exception)`. Each
    message is the Global Constraints copy.
  - **Functions:**
    - `ai_keys.normalize(raw: str) -> str`
    - `ai_keys.hint_for(api_key: str) -> str` returns `"…" + api_key[-4:]`
    - `ai_keys.get_row(db, user_id) -> UserAIKey | None`
    - `ai_keys.read_key(db, user_id) -> str | None`. Returns None when there's no row or
      it can't be opened. Ignores `status`.
    - `ai_keys.save_key(db, user_id, api_key: str) -> UserAIKey`. Upserts, sets
      `status="ok"` and the timestamps, flushes, and does not commit.
    - `ai_keys.delete_key(db, user_id) -> None` (flush)
    - `ai_keys.mark_rejected(db, user_id) -> None`. Sets `status="rejected"` and
      **commits `db`**. The caller's pending `LLMCall` row commits with it, which is
      intended: the attempt happened. It uses the caller's session because a second
      connection would block on SQLite's write lock, which that session already holds
      after `reserve_call` flushed.
    - `ai_keys.verify(api_key: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_keys.py
import pytest
from src.core.config import settings
from src.models import UserAIKey
from src.services import ai_keys

KEY = "sk-ant-api03-" + "k" * 40

def test_normalize_trims_paste_whitespace():
    assert ai_keys.normalize(f"  {KEY}\n") == KEY

@pytest.mark.parametrize("bad", ["", "sk-proj-abc", "sk-ant-", "sk-ant-ab cd" + "x" * 20, "sk-ant-" + "x" * 400])
def test_normalize_rejects_what_is_not_a_claude_key(bad):
    with pytest.raises(ai_keys.KeyFormatError):
        ai_keys.normalize(bad)

def test_hint_is_last_four():
    assert ai_keys.hint_for(KEY) == "…kkkk"

def test_save_stores_ciphertext_not_the_key(db_session, user):
    row = ai_keys.save_key(db_session, user.id, KEY); db_session.commit()
    assert KEY not in row.ciphertext and row.hint == "…kkkk" and row.status == "ok"
    assert ai_keys.read_key(db_session, user.id) == KEY

def test_saving_again_replaces_and_clears_rejected(db_session, user):
    ai_keys.save_key(db_session, user.id, KEY); db_session.commit()
    ai_keys.mark_rejected(db_session, user.id)
    assert ai_keys.get_row(db_session, user.id).status == "rejected"
    new = "sk-ant-api03-" + "n" * 40
    ai_keys.save_key(db_session, user.id, new); db_session.commit()
    assert db_session.query(UserAIKey).count() == 1
    assert ai_keys.get_row(db_session, user.id).status == "ok"
    assert ai_keys.read_key(db_session, user.id) == new

def test_unreadable_row_reads_as_no_key(db_session, user, monkeypatch):
    ai_keys.save_key(db_session, user.id, KEY); db_session.commit()
    monkeypatch.setattr(settings, "ai_key_secret", "rotated")
    assert ai_keys.read_key(db_session, user.id) is None

def test_delete(db_session, user):
    ai_keys.save_key(db_session, user.id, KEY); db_session.commit()
    ai_keys.delete_key(db_session, user.id); db_session.commit()
    assert ai_keys.get_row(db_session, user.id) is None

def test_verify_maps_auth_failure(monkeypatch):
    import anthropic, httpx
    def boom(api_key):
        raise anthropic.AuthenticationError("bad", response=httpx.Response(401, request=httpx.Request("GET", "https://x")), body=None)
    monkeypatch.setattr(ai_keys, "_models_list", boom)
    with pytest.raises(ai_keys.KeyNotAccepted):
        ai_keys.verify(KEY)

def test_verify_maps_connection_failure(monkeypatch):
    import anthropic, httpx
    def boom(api_key):
        raise anthropic.APIConnectionError(request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr(ai_keys, "_models_list", boom)
    with pytest.raises(ai_keys.KeyCheckFailed):
        ai_keys.verify(KEY)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest tests/test_ai_keys.py -q`

Expected: FAIL with an ImportError for `UserAIKey` / `ai_keys`.

- [ ] **Step 3: Implement**
  - **`normalize`:** strip, then require all of the following:
    - starts with `sk-ant-`
    - `20 <= len <= 300`
    - no whitespace inside
  - **`verify`:** calls a module-level seam
    `_models_list(api_key: str) -> None`, which does
    `anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=10).models.list(limit=1)`.
    - `AuthenticationError` / `PermissionDeniedError` → `KeyNotAccepted`
    - any other `anthropic.APIError` → `KeyCheckFailed`
  - **`read_key`:** catches `crypto.SealError`, logs `"stored AI key for %s can't be
    opened"` with the user id only, and returns None.
  - **Migration:** create the table to match the model. It must work on SQLite and
    Postgres, following `0002`'s column style.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `pytest -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "Store users' Claude keys sealed in user_ai_keys"
```

---

### Task 3: `/ai-key` endpoints

**Files:**
- Create: `apps/api/src/schemas/ai_key.py`
- Create: `apps/api/src/routers/ai_key.py`. Register it in `src/main.py`'s router
  tuple.
- Modify: `apps/api/tests/conftest.py`: add an autouse fixture that calls
  `ai_key.attempts.reset()`
- Test: `apps/api/tests/test_ai_key_api.py`

**Interfaces:**
- Consumes: the `ai_keys.*` functions (Task 2)
- Produces:
  - `AIKeyIn { api_key: SecretStr }`
  - `AIKeyOut { has_key: bool, hint: str | None, status: Literal["ok","rejected"] | None, updated_at: datetime | None }`
  - `GET /api/v1/ai-key` → `AIKeyOut`
  - `PUT /api/v1/ai-key` → `AIKeyOut`
  - `DELETE /api/v1/ai-key` → 204
  - `routers.ai_key.attempts`, with `.allow(user_id) -> bool` and `.reset() -> None`.
    It's an in-memory sliding window allowing **10 PUTs per user per 3600 s**, which is
    enough because Render runs one uvicorn worker.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_key_api.py
import pytest
from src.core.config import settings
from src.services import ai_keys

API = "/api/v1/ai-key"
KEY = "sk-ant-api03-" + "s" * 36 + "WXYZ"

@pytest.fixture
def verifies(monkeypatch):
    monkeypatch.setattr(ai_keys, "_models_list", lambda api_key: None)

def test_starts_empty(auth_client):
    assert auth_client.get(API).json() == {"has_key": False, "hint": None, "status": None, "updated_at": None}

def test_save_returns_hint_never_key(auth_client, verifies):
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 200
    assert KEY not in response.text and response.json()["hint"] == "…WXYZ"
    got = auth_client.get(API)
    assert got.json()["has_key"] is True and KEY not in got.text

def test_bad_format_is_422_without_echo(auth_client):
    bad = "sk-ant-has space" + "q" * 30
    response = auth_client.put(API, json={"api_key": bad})
    assert response.status_code == 422 and "qqqq" not in response.text

def test_oversized_body_is_422_without_echo(auth_client):
    huge = "sk-ant-" + "z" * 5000
    response = auth_client.put(API, json={"api_key": huge})
    assert response.status_code == 422 and "zzzzzzzz" not in response.text

def test_claude_refuses_key(auth_client, monkeypatch):
    def refuse(api_key): raise ai_keys.KeyNotAccepted("Claude didn't accept this key.")
    monkeypatch.setattr(ai_keys, "verify", refuse)
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 422 and response.json()["detail"] == "Claude didn't accept this key."
    assert auth_client.get(API).json()["has_key"] is False

def test_claude_unreachable(auth_client, monkeypatch):
    def down(api_key): raise ai_keys.KeyCheckFailed("Couldn't check this key with Claude. Try again.")
    monkeypatch.setattr(ai_keys, "verify", down)
    assert auth_client.put(API, json={"api_key": KEY}).status_code == 502

def test_delete(auth_client, verifies):
    auth_client.put(API, json={"api_key": KEY})
    assert auth_client.delete(API).status_code == 204
    assert auth_client.get(API).json()["has_key"] is False

def test_rotated_secret_reads_as_no_key(auth_client, verifies, monkeypatch):
    auth_client.put(API, json={"api_key": KEY})
    monkeypatch.setattr(settings, "ai_key_secret", "rotated")
    assert auth_client.get(API).json() == {"has_key": False, "hint": None, "status": None, "updated_at": None}

def test_eleventh_attempt_in_an_hour_is_429(auth_client, verifies):
    for _ in range(10):
        assert auth_client.put(API, json={"api_key": KEY}).status_code == 200
    response = auth_client.put(API, json={"api_key": KEY})
    assert response.status_code == 429 and response.json()["detail"] == "Too many key attempts. Try again in an hour."

def test_keys_are_per_user(client, auth_client, verifies):
    auth_client.put(API, json={"api_key": KEY})
    other = client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "another-long-pass"}).json()
    response = client.get(API, headers={"Authorization": f"Bearer {other['access_token']}"})
    assert response.json()["has_key"] is False
```
If `client` and `auth_client` share one `TestClient` instance in conftest, give the
second user a fresh `TestClient(app)` instead.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest tests/test_ai_key_api.py -q`

Expected: FAIL with 404s.

- [ ] **Step 3: Implement**
  - **`AIKeyIn.api_key`:** a `SecretStr` with `max_length=300`, so pydantic never echoes
    it.
  - **PUT order:**
    1. Rate limit → 429.
    2. `normalize` → 422 with the bad-format copy.
    3. `verify` → 422 / 502.
    4. `save_key`, commit.
    5. Return the row as `AIKeyOut`.
  - **GET:** a row counts as present only when `read_key` returns a value. Otherwise
    return the empty shape.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `pytest -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "Add the /ai-key endpoints: write-only, verified, rate-limited"
```

---

### Task 4: Every AI call runs on the user's key

**Files:**
- Modify: `apps/api/src/services/ai.py`
  - Remove `enabled`, `client`, `AIQuotaExceeded`, `_month_start`, `calls_this_month`
    and `under_cap`, and the cap check in `reserve_call`.
  - Add the interfaces below.
- Modify: `apps/api/src/services/ai_errors.py`: the new status mapping
- Modify: `apps/api/src/core/config.py`: remove `anthropic_api_key` and
  `llm_monthly_call_cap`
- Modify the call sites:
  - `src/services/ai_text.py:132`
  - `src/services/cover_letters.py:75`
  - `src/services/autofill.py:83,267`
  - `src/services/ingestion/tiers/llm.py`: `extract` takes a client; delete `enabled`
    and `LLMUnavailable`
  - `src/services/ingestion/pipeline.py`: `run_pipeline(..., llm_client=None)` replaces
    `allow_llm`. `ingest_application` passes `ai.client_or_none(db, user_id)`.
  - `src/routers/ingest.py:146-161,218`: pass `llm_client=ai.client_or_none(db, user.id)`
- Modify: `apps/api/src/models/llm_call.py`: the docstring no longer mentions a cap
- Modify: `apps/api/tests/conftest.py`: rework the `fake_ai` fixture
- Modify:
  - `apps/api/tests/test_ai.py`: delete `test_the_monthly_cap_is_enforced`; update
    `saved_with_description` and the no-key test
  - `tests/test_packaging.py`: the Tier 4 ImportError test
  - Any test still using `allow_llm`, `ai.enabled` or `ai.client`
- Test: `apps/api/tests/test_ai_user_keys.py`

**Interfaces:**
- Consumes: `ai_keys.read_key`, `ai_keys.get_row`, `ai_keys.mark_rejected` (Task 2)
- Produces:
  - **Messages:** `ai.MISSING_KEY`, `ai.REJECTED_KEY`, `ai.OUT_OF_CREDIT`,
    `ai.RATE_LIMITED`, as `str` constants with the Global Constraints copy.
  - **Exceptions:** `ai.AIKeyMissing(AIUnavailable)` and `ai.AIKeyRejected(AIUnavailable)`.
  - **Key lookup:** `ai.user_key(db, user_id) -> str`.
    - No row, or a row that can't be opened → `AIKeyMissing(MISSING_KEY)`.
    - `status == "rejected"` → `AIKeyRejected(REJECTED_KEY)`.
  - **Client construction:**
    - `ai._build_client(api_key: str)` returns `anthropic.Anthropic(api_key=api_key)`.
      An `ImportError` becomes `AIUnavailable`. This is the seam tests patch.
    - `ai.UserClient(inner, db, user_id)` exposes `.messages.create(**kw)` and
      `.messages.parse(**kw)`, looking up `inner.messages` at call time. When
      `sdk_error_kind(exc) == "auth"` it calls `ai_keys.mark_rejected(db, user_id)` and
      raises `AIKeyRejected(REJECTED_KEY)` from the SDK error. Every other exception
      passes through.
    - `ai.client_for(db, user_id) -> UserClient`
    - `ai.client_or_none(db, user_id) -> UserClient | None` returns None on any
      `AIUnavailable`.
    - `ai.has_key(db, user_id) -> bool`
  - **SDK error classification:** `ai.sdk_error_kind(exc) -> Literal["auth","rate_limit","credit","other"] | None`.
    - `AuthenticationError` / `PermissionDeniedError` → `"auth"`
    - `RateLimitError` → `"rate_limit"`
    - `BadRequestError` with `"credit balance"` in `str(exc).lower()` → `"credit"`
    - any other `anthropic.APIError` → `"other"`
    - anything else → `None`
  - **Call accounting:** `ai.reserve_call(db, user_id, kind)` now only records (add +
    flush).
  - **Tier 4:** `llm.extract(text: str, *, url: str | None = None, client=None) -> ExtractedPosting | None`.
    It returns None when `client` is None. It catches `ai.AIUnavailable` and SDK errors
    and returns None.
  - **Pipeline:** `pipeline.run_pipeline(url, *, html=None, text=None, hints=None, llm_client=None) -> IngestOutcome`
  - **`ai_errors()`** maps, in this order:
    - `AIKeyMissing` → 428
    - `AIKeyRejected` → 424
    - other `AIUnavailable` → 503
    - `ResumeRejected` → its own code
    - `AIFailed` → 502
    - SDK `rate_limit` → 429 with `RATE_LIMITED`
    - SDK `credit` → 402 with `OUT_OF_CREDIT`
    - other SDK errors → the existing 502

- [ ] **Step 1: Rework the fixture**

`FakeAI` gains `self.keys: list[str] = []`. The new `fake_ai` fixture:

```python
@pytest.fixture
def fake_ai(monkeypatch) -> FakeAI:
    fake = FakeAI()
    monkeypatch.setattr("src.services.ai.user_key", lambda db, user_id: "sk-ant-test-0000")
    def build(api_key):
        fake.keys.append(api_key)
        return fake
    monkeypatch.setattr("src.services.ai._build_client", build)
    return fake
```
Add a fixture and a helper to `conftest.py` alongside it, so Task 5 can reuse them:

```python
def auth_error():
    import anthropic, httpx
    return anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=httpx.Request("POST", "https://x")), body=None)

@pytest.fixture
def real_keys(monkeypatch) -> FakeAI:
    """Real key storage, fake transport: records which key each client was built with."""
    from src.services import ai_keys
    fake = FakeAI()
    def build(api_key):
        fake.keys.append(api_key)
        return fake
    monkeypatch.setattr("src.services.ai._build_client", build)
    monkeypatch.setattr(ai_keys, "_models_list", lambda api_key: None)
    return fake
```

`saved_with_description(client, text=NOISY, fake=None)` queues `fake.parsed(None)` when
`fake` is given, replacing the `ai.enabled()` check. Update its callers to pass
`fake_ai`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_ai_user_keys.py
import uuid

import anthropic, httpx, pytest
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
    def refuse(**_): raise auth_error()
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

@pytest.mark.parametrize("kind,status,detail", [
    ("rate_limit", 429, ai.RATE_LIMITED),
    ("credit", 402, ai.OUT_OF_CREDIT),
])
def test_account_limits_are_reported_as_the_users(auth_client, fake_ai, monkeypatch, kind, status, detail):
    app = saved_with_description(auth_client, fake=fake_ai)
    req = httpx.Request("POST", "https://x")
    err = (anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)
           if kind == "rate_limit" else
           anthropic.BadRequestError("Your credit balance is too low", response=httpx.Response(400, request=req), body=None))
    def fail(**_): raise err
    monkeypatch.setattr(fake_ai.messages, "create", fail)
    response = auth_client.post(f"{API}/applications/{app['id']}/clean-description")
    assert response.status_code == status and response.json()["detail"] == detail

def test_no_ai_error_is_ever_401(auth_client, real_keys, monkeypatch):
    auth_client.put(f"{API}/ai-key", json={"api_key": ALICE_KEY})
    app = saved_with_description(auth_client, fake=real_keys)
    def refuse(**_): raise auth_error()
    monkeypatch.setattr(real_keys.messages, "create", refuse)
    assert auth_client.post(f"{API}/applications/{app['id']}/clean-description").status_code != 401
```
Also add one missing-key test for the cover letter
(`POST /applications/{id}/cover-letter` → 428) in `test_cover_letters.py`, and one for
the resume profile (`POST /autofill/profile` → 428) in `test_autofill.py`. Use the
request shapes those files already use.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `pytest tests/test_ai_user_keys.py -q`

Expected: FAIL. `ai.MISSING_KEY` doesn't exist, and the status is 503.

- [ ] **Step 4: Implement**

Do the interface list above, then:
- Replace each `client = ai.client()` with `client = ai.client_for(db, <user id>)`. In
  `tiers/llm.py`, use the `client` argument instead.
- Leave each `reserve_call` call where it is.
- Remove `AIQuotaExceeded` from every `except` tuple.
- Update `test_packaging`'s Tier 4 test: with `anthropic` imports refused,
  `ai.client_or_none(db_session, user.id)` is None given a stored key, and
  `llm.extract(text, url=..., client=None)` is None.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `pytest -q && ruff check src tests scripts && ruff format --check src tests scripts`

Expected: all pass.

Then run: `grep -rn "anthropic_api_key\|llm_monthly_call_cap\|ai\.enabled\|ai\.client()\|allow_llm\|AIQuotaExceeded" src tests ../worker`

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add apps/api apps/worker
git commit -m "Run every AI call on the user's own key; drop the global key and monthly cap"
```

---

### Task 5: Background paths and the extension tell users why AI didn't run

**Files:**
- Modify: `apps/api/src/services/ingestion/pipeline.py`
  - Add `IngestOutcome.llm_skipped: bool = False`. `run_pipeline` sets it at the two
    Tier 4 sites when the tier's other conditions hold but `llm_client is None`.
  - `apply_outcome` writes `extraction_meta["llm"] = "no_key"` when it's set.
  - At `pipeline.py:229`, enqueue clean-up only when `ai.has_key(db, application.user_id)`.
- Modify: `apps/api/src/routers/ingest.py:183,229`: the same `has_key` gate before
  `queue.enqueue_cleanup`
- Modify: `apps/api/src/services/ingestion/queue.py:76-85`: drop the `ai.enabled()`
  gate in `enqueue_cleanup`
- Modify: `apps/api/src/services/ai_text.py` `run_cleanup`: catch `ai.AIUnavailable`
  only
- Modify:
  - `apps/api/src/schemas/autofill.py`: add `AutofillPlan.ai_skipped_reason: str | None = None`
  - `src/services/autofill.py`: `_ask_model` reports why it didn't ask, which is
    `str(exc)` of the `AIUnavailable`, and the plan carries it
- Modify: `apps/extension/src/sidepanel.js` (fill handler, around line 213). When any
  frame's `/map` response has `ai_skipped_reason`, append it to the "Filled N
  fields…" status, after a space.
- Test: `apps/api/tests/test_ai_background.py`, plus an addition to `tests/test_autofill.py`

**Interfaces:**
- Consumes: `ai.client_or_none`, `ai.has_key`, `ai.AIKeyRejected`, and from
  `conftest.py` (Task 4) the `real_keys` / `fake_ai` fixtures and `auth_error()`.
- Produces: `IngestOutcome.llm_skipped`, `extraction_meta["llm"] == "no_key"`,
  `AutofillPlan.ai_skipped_reason`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_background.py
import uuid
from src.services.ingestion import pipeline
from src.services import ai, ai_keys
from src.models import Application

LONG_PAGE = "<html><body><main>" + "We are hiring someone great. " * 40 + "</main></body></html>"

def test_tier4_without_a_client_is_recorded_as_skipped():
    outcome = pipeline.run_pipeline("https://example.com/jobs/1", html=LONG_PAGE, llm_client=None)
    assert outcome.llm_skipped is True and "llm" not in outcome.tiers_attempted

def test_no_key_lands_in_extraction_meta(db_session, user):
    app = Application(user_id=user.id, source_url="https://example.com/jobs/1")  # fill required columns as the model demands
    db_session.add(app); db_session.flush()
    outcome = pipeline.run_pipeline(app.source_url, html=LONG_PAGE, llm_client=None)
    pipeline.apply_outcome(db_session, app, outcome)
    assert app.extraction_meta["llm"] == "no_key"

def test_no_cleanup_is_queued_without_a_key(auth_client, cleanups):
    auth_client.post("/api/v1/ingest/from-text", json={"text": "About the role " * 30, "company": "Ramp", "title": "Intern"})
    assert cleanups == []

def test_a_key_revoked_mid_ingest_still_finishes(db_session, user, real_keys, monkeypatch):
    ai_keys.save_key(db_session, user.id, "sk-ant-api03-" + "r" * 40); db_session.commit()
    from tests.conftest import auth_error
    def refuse(**_): raise auth_error()
    monkeypatch.setattr(real_keys.messages, "parse", refuse)
    client = ai.client_for(db_session, user.id)
    outcome = pipeline.run_pipeline("https://example.com/jobs/1", html=LONG_PAGE, llm_client=client)
    assert outcome.posting is not None  # generic tier still produced the card
    db_session.expire_all()
    assert ai_keys.get_row(db_session, user.id).status == "rejected"
```

```python
# tests/test_autofill.py — addition
def test_map_without_a_key_says_why(auth_client):
    # a profile plus one field no rule can place, as the file's existing map tests build them
    plan = auth_client.post("/api/v1/autofill/map", json=...).json()
    assert plan["used_ai"] is False
    assert plan["ai_skipped_reason"] == ai.MISSING_KEY
```
Fill in `json=...` with the request body the existing `/map` tests use, plus one free
text field that has no rule.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest tests/test_ai_background.py tests/test_autofill.py -q`

Expected: FAIL on the `llm_skipped` attribute, the `cleanups` list, and the missing
`ai_skipped_reason`.

- [ ] **Step 3: Implement**

Make the changes listed under Files.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `pytest -q && ruff check src tests scripts && ruff format --check src tests scripts`

Expected: all pass.

Then run: `cd ../extension && node test/run.mjs`

Expected: passes as before.

- [ ] **Step 5: Commit**

```bash
git add apps/api apps/extension
git commit -m "Say why AI didn't run in background ingest and extension autofill"
```

---

### Task 6: Web — the Claude API key dialog

**Files:**
- Modify: `apps/web/src/api/types.ts`: add `AiKeyState`
- Modify: `apps/web/src/api/hooks.ts`: add `queryKeys.aiKey`, `useAiKey`,
  `useSaveAiKey`, `useRemoveAiKey`
- Modify: `apps/web/src/lib/store.ts`: add `aiKeyDialogOpen`, `openAiKeyDialog`,
  `closeAiKeyDialog`
- Create: `apps/web/src/features/aikey/AiKeyDialog.tsx`. Render `<AiKeyDialog />` once
  in `App.tsx`, after the header.
- Modify: `apps/web/src/features/auth/AccountMenu.tsx`: add the "Claude API key" menu
  item
- Test: `apps/web/src/features/aikey/AiKeyDialog.test.tsx`

**Interfaces:**
- Consumes: `GET/PUT/DELETE /api/v1/ai-key` (Task 3)
- Produces:
  - **Types:**
    - `type AiKeyState = { has_key: boolean; hint: string | null; status: "ok" | "rejected" | null; updated_at: string | null }`
  - **Hooks:**
    - `useAiKey(): UseQueryResult<AiKeyState>`
    - `useSaveAiKey()` is a mutation taking `string`. It PUTs `{ api_key }` and on
      success does `setQueryData(queryKeys.aiKey, result)`.
    - `useRemoveAiKey()` is a mutation that DELETEs, then sets the empty state.
  - **Store:** `useUi` gains `aiKeyDialogOpen: boolean`, `openAiKeyDialog(): void` and
    `closeAiKeyDialog(): void`.
  - **Component:** `AiKeyDialog(): JSX.Element | null`

- [ ] **Step 1: Write the failing tests**

Use the `serve`/`json` fetch-stub pattern from `CoverLetter.test.tsx`. Render
`<AiKeyDialog />` in a `QueryClientProvider`, after `useUi.getState().openAiKeyDialog()`.

```tsx
const KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789WXYZ";

it("saves, clears the input, and shows only the hint", async () => {
  let state = { has_key: false, hint: null, status: null, updated_at: null };
  serve((url, init) => {
    if (init?.method === "PUT") {
      expect(JSON.parse(String(init.body))).toEqual({ api_key: KEY });
      state = { has_key: true, hint: "…WXYZ", status: "ok", updated_at: "2026-10-26T00:00:00Z" };
    }
    return json(state);
  });
  renderDialog();
  fireEvent.change(await screen.findByLabelText("Claude API key"), { target: { value: KEY } });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  expect(await screen.findByText(/…WXYZ/)).toBeInTheDocument();
  expect((screen.getByLabelText("Claude API key") as HTMLInputElement).value).toBe("");
  expect(document.body.textContent).not.toContain("abcdefghij");
  expect(JSON.stringify({ ...localStorage })).not.toContain("sk-ant");
});

it("shows the server's reason when Claude refuses the key", async () => {
  serve((_, init) => init?.method === "PUT"
    ? json({ detail: "Claude didn't accept this key." }, 422)
    : json({ has_key: false, hint: null, status: null, updated_at: null }));
  renderDialog();
  fireEvent.change(await screen.findByLabelText("Claude API key"), { target: { value: KEY } });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  expect(await screen.findByText("Claude didn't accept this key.")).toBeInTheDocument();
});

it("asks before removing, then sends DELETE", async () => {
  serve((_, init) => init?.method === "DELETE" ? new Response(null, { status: 204 })
    : json({ has_key: true, hint: "…WXYZ", status: "ok", updated_at: null }));
  renderDialog();
  fireEvent.click(await screen.findByRole("button", { name: "Remove key" }));
  fireEvent.click(screen.getByRole("button", { name: "Yes, remove it" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/ai-key"), expect.objectContaining({ method: "DELETE" })));
});

it("tells the user a rejected key needs replacing", async () => {
  serve(() => json({ has_key: true, hint: "…WXYZ", status: "rejected", updated_at: null }));
  renderDialog();
  expect(await screen.findByText(/rejected/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `npx vitest run src/features/aikey`

Expected: FAIL, because the module isn't found.

- [ ] **Step 3: Implement**
  - **Dialog structure:**
    - A `role="dialog"` `mc-panel`. Escape and the backdrop close it.
    - The input is labelled **Claude API key**, with `type="password"` and
      `autoComplete="off"`.
    - Buttons: **Save key**, **Remove key**, then **Yes, remove it** / **Cancel**.
  - **Dialog copy:**
    - "Powers link auto-fill, description clean-up, cover letters and extension
      autofill. Stored encrypted; never shown again."
    - A link to `https://console.anthropic.com/settings/keys` (opens in a new tab,
      `rel="noreferrer"`).
    - "Tip: make a separate key for this app with a monthly spend limit."
  - **State and errors:**
    - When a key exists, show the current `hint`. When `status === "rejected"`, show
      "Claude rejected this key — paste a new one."
    - The draft key lives in `useState` only. Set it to `""` on submit, before awaiting
      the mutation.
    - Show a mutation's `error.message` inline.
  - **Account menu item:** **Claude API key**, with a subtitle by state:
    - no key: "Turn on AI features"
    - `ok`: "Connected · {hint}"
    - `rejected`: "Rejected — replace it"

    Clicking it calls `openAiKeyDialog()` and closes the menu.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `npm run typecheck && npm test && npm run build`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "Add the Claude API key dialog to the account menu"
```

---

### Task 7: Web — AI surfaces without a key

**Files:**
- Create: `apps/web/src/features/aikey/AddKeyPrompt.tsx`
- Create: `apps/web/src/features/aikey/aiKeyErrors.ts`
- Modify: `apps/web/src/features/detail/CoverLetter.tsx` (`ResumeForm`, and
  `NotReady`'s "Clean up now")
- Modify: `apps/web/src/features/detail/DescriptionEditor.tsx` (the "Clean up" button,
  around line 84)
- Test: additions to `CoverLetter.test.tsx` and `DescriptionEditor.test.tsx`

**Interfaces:**
- Consumes: `useAiKey`, `openAiKeyDialog` (Task 6), `ApiError` (`api/client.ts`)
- Produces:
  - `AddKeyPrompt({ what }: { what: string })` renders "Add your Claude API key to use
    {what}." and a button **Add Claude key** that calls `openAiKeyDialog()`.
  - `isAiKeyError(error: unknown): boolean` is true for `ApiError` with status 428 or
    424.
  - `aiUsable(state: AiKeyState | undefined): boolean` is
    `state === undefined || (state.has_key && state.status !== "rejected")`. While
    loading, or on fetch failure, allow the attempt; the server's 428/424 is the
    fallback.

- [ ] **Step 1: Write the failing tests**

Route `/ai-key` in each file's existing `serve` stub.

```tsx
// CoverLetter.test.tsx
it("asks for a key instead of a resume when there is none", async () => {
  serve((url) => url.endsWith("/ai-key")
    ? json({ has_key: false, hint: null, status: null, updated_at: null })
    : json({ detail: "No cover letter yet" }, 404));
  renderTab({ description_clean: "About the role…" });
  expect(await screen.findByRole("button", { name: "Add Claude key" })).toBeInTheDocument();
  expect(screen.queryByLabelText(/resume/i)).not.toBeInTheDocument();
});

it("opens the key dialog when the server says the key is missing", async () => {
  // has_key true locally, but generation returns 428 → toast + dialog opens
  ...
  expect(useUi.getState().aiKeyDialogOpen).toBe(true);
});
```

```tsx
// DescriptionEditor.test.tsx
it("turns Clean up into Add Claude key without a key", async () => {
  // stub /ai-key → has_key false; render as the file's existing tests do
  fireEvent.click(await screen.findByRole("button", { name: "Add Claude key to clean up" }));
  expect(useUi.getState().aiKeyDialogOpen).toBe(true);
});
```
Fill in the elided setup with the render helper and fixture each file already has.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `npx vitest run src/features/detail`

Expected: FAIL on the new tests.

- [ ] **Step 3: Implement**
  - **Cover letter:** `ResumeForm` renders `<AddKeyPrompt what="cover letters" />` when
    `!aiUsable(aiKey.data)`.
  - **Clean-up buttons:** in `DescriptionEditor`'s clean-up button and in
    `CoverLetter`'s `NotReady` button, when `!aiUsable(...)`, the label becomes **Add
    Claude key to clean up** and `onClick` calls `openAiKeyDialog()`.
  - **Error fallback:** every AI mutation's `onError` keeps `notify(error.message,
    "error")`, and when `isAiKeyError(error)` also calls `openAiKeyDialog()`. The AI
    mutations are clean-up and cover-letter generation.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `npm run typecheck && npm test && npm run build`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "Point AI features at the key dialog when there's no usable key"
```

---

### Task 8: Config, deploy and docs; full verification

**Files:**
- `render.yaml`: remove the `ANTHROPIC_API_KEY` block (lines 46-47). Add
  `- key: AI_KEY_SECRET` with `generateValue: true` and a comment: "Seals users' Claude
  keys. Changing it makes every stored key unreadable — users must re-enter them."
- `docker-compose.yml:40,59`: replace `ANTHROPIC_API_KEY` with
  `AI_KEY_SECRET: ${AI_KEY_SECRET:-}`
- `apps/api/.env.example:14`: replace the line with `# AI_KEY_SECRET=` plus the same
  one-line warning
- `infra/main.tf`: add `AI_KEY_SECRET` wherever the API and worker get their other
  secrets
- Docs:
  - `docs/DEPLOYMENT.md`:
    - In the env table, replace the `ANTHROPIC_API_KEY` row with `AI_KEY_SECRET`
      (required outside local, `generateValue`, losing it locks every key).
    - Remove the Anthropic lines from the cost tables, and the cap mention around line
      56.
    - Rewrite the gotcha near line 105 about Tier 4 being quietly dead without the
      extra. `anthropic` is now a core dependency; the remaining reason Tier 4 is off
      is a user without a key.
  - `docs/GETTING_STARTED.md`: how to add your own key locally (👤 → Claude API key).
  - `docs/STATUS.md`: a short "Bring your own key" entry under Phase 5.
  - `README.md` §8.3: a one-line *revised* note saying cost is now per user, on the
    user's own key.

- [ ] **Step 1: Make the config and doc edits above**

- [ ] **Step 2: Confirm nothing still refers to the old key**

Run: `git grep -n "ANTHROPIC_API_KEY\|llm_monthly_call_cap\|\.\[llm\]"`

Expected: no output, apart from historical mentions that the docs explicitly frame as
past.

- [ ] **Step 3: Run the full verification**

Run, from `apps/api`: `pytest -q && ruff check src tests scripts && ruff format --check src tests scripts`

Run, from `apps/web`: `npm run typecheck && npm test && npm run build`

Run, from `apps/extension`: `node test/run.mjs`

Expected: everything passes.

- [ ] **Step 4: Run it by hand**

Start the API and web locally (`docs/GETTING_STARTED.md`) and sign in. Then check:
1. AI surfaces show **Add Claude key**.
2. Saving a real key shows `…xxxx`.
3. Generating a cover letter works.
4. The API log never shows the key.

- [ ] **Step 5: Commit**

```bash
git add render.yaml docker-compose.yml apps/api/.env.example infra docs README.md
git commit -m "Replace ANTHROPIC_API_KEY with AI_KEY_SECRET in config and docs"
```
