# Bring your own Claude key — design

**Date:** 2026-10-26 · **Status:** draft, awaiting approval

## Why

The deployed tracker has open registration and a public repo. Every AI call runs on the
owner's `ANTHROPIC_API_KEY`, so any stranger can sign up and spend up to
`llm_monthly_call_cap` (500) calls a month of the owner's money. The owner doesn't want
to pay for other people's AI use.

The change: every user, the owner included, pastes in their own Claude API key. The
server stores it encrypted and uses it for that user's AI calls only. Keys must not
leak: not to other users, not into logs, not back out through the API.

## Goals

- A signed-in user can add, replace and remove their own Anthropic API key from the web
  app.
- All five AI features use the key of the user they run for:
  Tier 4 extraction, description clean-up, cover letters, resume profile, and the
  extension's autofill. That includes the two that run in the background
  (Tier 4 inside ingestion, clean-up from the queue) and the extension.
- There is no server-wide key. `ANTHROPIC_API_KEY` / `settings.anthropic_api_key` goes
  away.
- A stored key is encrypted at rest, is never returned by any endpoint, is never written
  to a log, and is decrypted only in memory for the length of one call.
- A user with no key gets the whole non-AI app, and every AI feature tells them plainly
  how to add a key.
- A key that Claude rejects later (revoked, deleted) is reported as such, with a way to
  replace it.

## Non-goals

- Keys from other providers (OpenAI, Gemini, …). The AI code stays Claude-specific
  (`messages.parse` structured output, PDF document blocks).
- A shared or fallback key, free trial calls, or any AI paid for by the owner.
- Letting users pick a model. `settings.llm_model` still decides.
- A usage or cost dashboard.
- The ⓘ help guide and GitHub link. That's a separate design, next.

## Anti-goals

These would make it a failure even if it otherwise works:

- A key, or any recognisable part of one beyond the last four characters, appears in an
  API response, a log line, an error message, a queue payload, or browser storage.
- One user's AI call runs on another user's key.
- An AI feature silently does nothing because the key is missing, with no explanation.
- The non-AI app breaks or degrades for users without a key.

## Constraints

- **Background work only carries an `application_id`.** Ingestion (`queue.run_ingest_now`
  → `pipeline.ingest_application` → `tiers/llm.extract`) and clean-up
  (`queue.enqueue_cleanup` → `run_cleanup_now`) run on a thread pool, or in the arq
  worker when `REDIS_URL` is set. They have to load the key from the database by the
  application's `user_id`, which is why it lives on the server.
- **Deployment.** API on Render (one uvicorn worker, usually no Redis), Postgres on Neon,
  web on Vercel. Local dev and CI use SQLite. Everything must work on both databases.
- **Dependencies.** `anthropic` is an optional `[llm]` extra today. The API Dockerfile
  installs it, but `apps/worker/Dockerfile` installs `./apps/api` without it.
- **The extension shows `detail` as is.** `sidepanel.js` displays `body.detail` when it's
  a string. AI errors have to keep `detail` a readable sentence.

## Approaches considered

| | How it works | Trade-off |
|---|---|---|
| **A. Encrypted on the server (chosen)** | The user pastes the key once. The server verifies it, encrypts it with a secret that lives only in the host's environment, stores the ciphertext, and decrypts it per call. | Works for background jobs and the extension with no extra setup. Reading keys takes both the database and the server's environment. A stolen session can *spend* a user's key but not read it. |
| B. Browser only, sent per request | The key sits in browser storage and rides along on each AI request. The server never stores it. | Background Tier 4 extraction can't work, the extension needs its own copy, any injected script can read it, and it's lost on a new device. |
| C. Browser calls Claude directly | The web app and extension call the Anthropic API themselves. | B's problems, plus all five features rewritten from Python into the front ends. Dropped. |

The owner picked **A**.

## Decided in conversation

- Claude (Anthropic) keys only for now.
- Every user brings their own key. No shared key, no fallback, no free tries.
- Keys are stored encrypted on the server.

## Design

### Storage

A new table `user_ai_keys` (Alembic `0003`), one row per user:

| column | notes |
|---|---|
| `user_id` | PK, FK → `users.id`, `ON DELETE CASCADE` |
| `ciphertext` | text. The encrypted key in a versioned envelope (below) |
| `hint` | text. `…` plus the last 4 characters, for display only |
| `status` | `ok` \| `rejected` |
| `verified_at`, `created_at`, `updated_at` | timestamps |

*My call:* a separate table rather than columns on `users`. `get_current_user` loads a
`User` on every request, and keeping the ciphertext off that object means no future
`UserOut`/`from_attributes` change can serialise it by accident.

### Encryption

- **Cipher:** AES-256-GCM via `cryptography` (already present through
  `python-jose[cryptography]`; declare it directly).
- **Master secret:** a new setting `ai_key_secret` (env `AI_KEY_SECRET`), separate from
  `JWT_SECRET` and `DATABASE_URL`. Derive the 32-byte AES key from it with HKDF-SHA256, so
  any long random string works, including Render's `generateValue`.
- **Bound to the user:** the user's UUID is the GCM associated data. A ciphertext copied
  onto another user's row fails to decrypt.
- **Envelope:** `v1:<b64 nonce‖ciphertext>`. A random 96-bit nonce per encryption. The
  version prefix leaves room to rotate the master secret later. Rotation itself is out of
  scope.
- **Unreadable is treated as missing.** A decrypt failure (wrong or rotated secret,
  tampering) is logged without the value and handled as "no key". The user re-enters
  it.
- **Startup:** outside `environment == "local"`, the API refuses to start without
  `AI_KEY_SECRET`. Locally it falls back to a fixed dev value and logs a warning.
- **Warning for the owner:** changing or losing `AI_KEY_SECRET` makes every stored key
  unreadable. Say so in DEPLOYMENT.md.

### API

All under `/api/v1/ai-key`, all scoped to the current user:

- **`GET`** returns `{has_key, hint, status, updated_at}`. Never the key.
- **`PUT`** takes `{api_key}`.
  - The schema field is a `pydantic.SecretStr`, so a validation error can't echo the key
    back in a 422 body.
  - Cheap format checks first: starts with `sk-ant-`, sane length, no whitespace.
  - Then it verifies the key with a call that costs no tokens (`client.models.list`).
    - Claude says 401/403 → 422 "Claude didn't accept this key."
    - Claude can't be reached → 502 "Couldn't check this key with Claude. Try again."
    - In both cases nothing is saved.
  - On success: encrypt, upsert with `status=ok`, return the same shape as `GET`.
  - Rate-limited per user (about 10 attempts an hour), so the server can't be used to
    test stolen keys in bulk. The mechanism is the builder's call.
- **`DELETE`** removes the row. 204.

### Making AI calls

`src/services/ai.py` stops owning a global client:

- **Factory.** `client()` → `client_for(db, user_id)`. It loads the row, decrypts, and
  builds `anthropic.Anthropic(api_key=…)` for that call. No module-level or cross-user
  caching of clients or keys.
- **Missing key.** No row, or an undecryptable row → `AIKeyMissing` (an `AIUnavailable`
  subclass): "Add your Claude API key (👤 → Claude API key) to use this." A row with
  `status=rejected` raises `AIKeyRejected` (below) without calling Claude.
- **Gate.** `enabled()` → `has_key(db, user_id)`, used by the call sites that gate
  rather than raise.
- **Key rejected mid-call.** An `anthropic.AuthenticationError` or
  `PermissionDeniedError` during a call flips the row to `status=rejected` and raises
  `AIKeyRejected`: "Claude rejected your saved key. Replace it under 👤 → Claude API key."
- **The user's own account limits.** Rate limits and out-of-credit errors are reported
  as being about the user's Claude account ("Your Claude account is out of credit"),
  not as a generic failure.
- **Statuses.** `ai_errors()` maps missing and rejected to statuses distinct from each
  other and from today's 503, keeping `detail` a readable string. The exact codes are
  the builder's call.
- **No more cap.** The monthly cap goes: `under_cap`, the cap check in `reserve_call`,
  `AIQuotaExceeded`, the 429 path, and `llm_monthly_call_cap`. *My call:* keep writing
  `LLMCall` rows, as a plain usage record.

Call sites to change:

- **Tier 4 extraction:** `tiers/llm.py`, `pipeline.py` and `queue.py`. The pipeline
  passes the application's user. No key → skip Tier 4 exactly as "no key" does today,
  and record `extraction_meta["llm"] = "no_key"` so the UI *can* hint later.
- **Description clean-up:** `ai_text.py`. `enqueue_cleanup` checks the application
  owner's key, not a global flag.
- **Cover letters:** `cover_letters.py`.
- **Resume profile and autofill map:** both in `autofill.py`.
- **The worker:** loads the key from the database itself. The key never goes into an
  arq payload.

### Keeping keys out of logs

- **Scrubbing filter.** A logging filter on the root logger replaces anything matching
  `sk-ant-[A-Za-z0-9_\-]+` in a log record's message and args with `sk-ant-…redacted`.
  This is defence in depth on top of never logging the key in the first place.
- **No SDK debug logging.** The Anthropic SDK's debug logging stays off in all
  environments.

### Web app

- **Account menu entry.** A new **Claude API key** item in `AccountMenu`, with a subtitle
  that reflects state: "Turn on AI features", "Connected · …a1b2", or "Rejected —
  replace it".
- **The dialog.** It opens from that item and contains:
  - One sentence on what the key powers, and that it's stored encrypted and never shown
    again.
  - A link to `https://console.anthropic.com/settings/keys`.
  - A tip to create a separate key for this app with a monthly spend limit.
  - A password-type input (`autocomplete="off"`) with Save, plus Remove (with a confirm
    step) when a key exists.
- **The key stays in memory.** It lives only in the input's component state and is
  cleared after submit. It never goes into `prefs`, the `useUi` store, localStorage, or
  a query cache.
- **AI surfaces with no key.** The cover letter and the description clean-up button
  check `has_key` and show an "Add your Claude key" action that opens the dialog,
  instead of calling the API and failing. The new error statuses are handled as a
  fallback.

### Extension

No new UI. Autofill already shows `detail`, and the new messages tell the user where to
add the key. The extension never sees the key.

### Config, deploy and docs

- **`render.yaml`:** drop `ANTHROPIC_API_KEY`, add `AI_KEY_SECRET` with
  `generateValue: true`.
- **Other config:** `docker-compose.yml` and `.env.example` change the same way.
  `infra/main.tf` gets the secret too.
- **Dependencies:** `anthropic` becomes a core dependency in `pyproject.toml`, so the
  worker image gets it too.
- **Docs:** `DEPLOYMENT.md` gets the new secret, the "losing it locks every key" warning,
  and a cost table that no longer shows an Anthropic line. `GETTING_STARTED.md` explains
  how to add your own key locally. `STATUS.md` records the change.

### Rollout

After deploy no one has a key, the owner included, so AI is off for everyone until they
add one. Existing `llm_calls` rows stay.

## Threat model

| Threat | What protects the key |
|---|---|
| Database leak (backup, Neon breach) | Only ciphertext is stored; the secret isn't in the database |
| Logs | Never logged; `SecretStr`; scrubbing filter |
| API responses | Write-only endpoint; only the 4-character hint comes back |
| Another user | Rows scoped by `user_id`; GCM associated data; a client built per call |
| XSS in the web app | The key is in the page only while it's being typed |
| Stolen session token (14-day JWT) | Can spend the key, can't read it. **Residual risk**, capped by the spend limit the dialog recommends |
| Full server compromise, or the operator | Can decrypt; true of any server-side secret. Capped by the spend limit |

## Testing

- **Crypto:**
  - Round trip works.
  - The wrong user id as associated data fails.
  - The wrong master secret fails and the row reads as "no key".
- **API:**
  - `GET` never contains the key.
  - A bad `PUT` returns 422 and the key string does not appear in `response.text`.
  - A good `PUT` (fake verifier) stores ciphertext that doesn't contain the plaintext.
  - `DELETE` works.
  - One user can't see or affect another's key.
- **Each AI feature:**
  - No key → the missing-key error.
  - With a key → the fake client was built with *that user's* key.
  - A call-time `AuthenticationError` → the row flips to `rejected`.
- **Background:**
  - Tier 4 and clean-up with no key are skipped, and the meta is recorded.
  - With a key they run on the owner's key, loaded inside the job.
- **Logging:** a record containing a fake `sk-ant-…` comes out redacted.
- **Fixtures:** `conftest.fake_ai` patches `settings.anthropic_api_key` and `ai.client`
  today. Rework it around `client_for` and a seeded key row.
- **Web:**
  - The dialog never renders a saved key.
  - The input is cleared after save.
  - The no-key state shows the "Add your Claude key" action.

## Left to the builder

- Exact HTTP statuses for missing and rejected keys (distinct, `detail` stays a string).
- The rate-limit mechanism on `PUT /ai-key`.
- Dialog layout and copy, in the existing `mc-panel` / `mc-button` style.
- Whether to add a "add a key to auto-fill pages like this" hint on Tier 5 cards now or
  later.
