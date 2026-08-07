# Getting started

Two ways to run it. The first needs nothing but Python and Node. For putting it on the
internet, see [`DEPLOYMENT.md`](./DEPLOYMENT.md).

## 1. Local, no Docker

The API defaults to a SQLite file and runs ingestion in-process, so Postgres and Redis
are optional until you want the real deployment shape.

```bash
# API — http://localhost:8000  (docs at /docs)
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python scripts/seed_demo.py --email you@example.com   # optional demo board
uvicorn src.main:app --reload

# Web — http://localhost:5173
cd apps/web
npm install
npm run dev
```

Sign in with the email you seeded (password `demo-password-123`), or register a new
account from the sign-in screen.

## 2. Docker Compose (Postgres + Redis + worker)

```bash
docker compose up --build
open http://localhost:5173
```

This is the shape the app deploys in: Postgres for real transactions and full-text
search, Redis for the ingestion queue and the SSE fan-out, and the worker as its own
process so a slow origin can't tie up an API instance.

## Configuration

Everything is an environment variable; defaults are in `apps/api/src/core/config.py`.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite+pysqlite:///./job_tracker.db` | Use `postgresql+psycopg://…` in any deployed environment |
| `REDIS_URL` | *(unset)* | When unset, ingestion runs in-process and SSE uses an in-memory hub |
| `JWT_SECRET` | `dev-secret-change-me` | **Change this before deploying** |
| `ANTHROPIC_API_KEY` | *(unset)* | Enables Tier 4 (LLM structuring). Without it the pipeline stops at Tier 3 |
| `LLM_MODEL` | `claude-opus-5` | Model used for the extraction fallback |
| `INGEST_BROWSER_ENABLED` | `0` | Enables Tier 3 (Playwright). Install the `browser` extra first |
| `STALE_WARN_DAYS` / `STALE_DIM_DAYS` | `14` / `30` | When a card goes amber, then grey |
| `REMINDER_EMAIL_ENABLED` | `false` | Email digests. Needs a provider — see below |
| `REMINDER_SWEEP_HOUR_UTC` | `13` | When the worker's daily reminder sweep runs |
| `SWEEP_SECRET` | *(unset)* | Enables `POST /reminders/sweep` for an external scheduler. Unset means that route 404s |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list |

The web app has one of its own, in `apps/web/.env.example`:

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_ORIGIN` | *(empty)* | Origin of the API, no trailing slash. Leave it unset for local dev and Docker — both serve the API same-origin. Set it only when the SPA and the API are on different hosts. Vite inlines it at **build** time |

## Tests

```bash
cd apps/api
pytest                       # SQLite — fast, no services needed
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/job_tracker pytest
```

The Postgres run executes the Alembic migration instead of `create_all`, so the
generated `search_vector` column, the `app_status` enum, and the partial indexes are
exercised too. CI runs both.

```bash
cd apps/web
npm run typecheck && npm run build
```

## What the ingestion pipeline does with a URL

1. **Tier 1 — ATS adapter.** If the hostname is Greenhouse, Lever, Ashby,
   SmartRecruiters, or Workday, hit that vendor's JSON API. Cheapest and most reliable,
   so it runs before any page fetch.
2. **Tier 0 — JSON-LD.** Fetch the page and look for a schema.org `JobPosting`.
3. **Tier 2 — Generic HTML.** Readability-style main-content extraction plus `og:` tags.
4. **Tier 3 — Headless browser.** Off by default; opt in for JS-rendered postings.
5. **Tier 4 — LLM structuring.** Only when a key is configured and the cheap tiers left
   holes. Schema-constrained, input truncated, confidence recorded.
6. **Tier 5 — Manual.** Always reachable: `POST /ingest/from-text`, or the drawer's
   "Paste the description yourself".

Every attempt writes an `ingest_jobs` row (tiers attempted, tier that won, duration,
error), which is what makes a bad paste debuggable from the URL alone.

## Bringing an existing spreadsheet

Table view → **Import CSV**. Headers are matched loosely (`employer`/`company`,
`role`/`position`, `link`/`url`, `stage`/`status`, `date applied`) and free-text statuses
like "Online Assessment" or "No response" map onto the board's columns. Re-importing the
same file is a no-op — rows are matched by canonical URL, or by company + title when
there's no link.

Rows it can't identify are skipped and reported by line number rather than guessed at,
and any column it didn't recognise is named back to you. **Export CSV** writes a file the
importer accepts, so export is a real backup rather than a dead end.

## Reminders

`next_action_at` on a card is a follow-up date. What's overdue, due today, or has simply
gone quiet appears in the bar above the board, and the account menu can turn on desktop
notifications.

The worker runs a sweep each day at `REMINDER_SWEEP_HOUR_UTC` and pushes to any
connected browser over SSE. Where there's no Redis — and so no worker — set
`SWEEP_SECRET` and have a scheduler `POST /api/v1/reminders/sweep` with an
`x-sweep-secret` header instead; `.github/workflows/reminders.yml` does exactly that.
Both run the same function.

**Email is not wired to a provider**: it sits behind the `Sender` interface in
`src/services/notify.py` with an implementation that logs what it would have sent. To
turn it on, implement `Sender` against your provider, return it from `get_sender()`, and
set `REMINDER_EMAIL_ENABLED=true`.

### Sites that block scraping

LinkedIn, Indeed, Glassdoor and ZipRecruiter are not scraped server-side. Two paths
exist instead:

1. **The browser extension** in `apps/extension` — load it unpacked, connect it with the
   token from the account menu, and click it on any posting. It reads the DOM your
   browser already rendered and posts it to `/api/v1/ingest/from-dom`. See
   [`apps/extension/README.md`](../apps/extension/README.md).
2. **Paste the text** — `POST /api/v1/ingest/from-text`, or the drawer's "Paste the
   description yourself".

Either way the card exists from the moment you paste the URL.

## On a phone

The board becomes a single column with a status switcher and a floating add button.
Install it from the browser's "Add to home screen" and it registers as a **share
target**: share a posting from the LinkedIn app (or anywhere) and the tracker opens with
the URL already filled in.

## Adding an ATS adapter

One file and one registry entry:

```python
# src/services/ingestion/adapters/workable.py
class WorkableAdapter(ATSAdapter):
    vendor = "workable"

    def matches(self, url: str) -> bool: ...
    def fetch(self, url: str) -> ExtractedPosting: ...
```

Add it to `ADAPTERS` in `adapters/__init__.py` and add a routing case to
`tests/test_tiers.py::test_adapter_routing`.
