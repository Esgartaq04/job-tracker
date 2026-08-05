# Getting started

Two ways to run it. The first needs nothing but Python and Node.

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
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list |

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

### Sites that block scraping

LinkedIn, Indeed, Glassdoor and ZipRecruiter are not scraped server-side. Two paths
exist instead: `POST /api/v1/ingest/from-dom` (a browser extension POSTs the DOM the
user is already looking at — the extension itself is Phase 3 and not built yet) and
`POST /api/v1/ingest/from-text` (paste the description). Either way the card exists
from the moment you paste the URL.

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
