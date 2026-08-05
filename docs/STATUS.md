# Implementation status

Against the delivery phases in the design document (README §10). This file is the
honest inventory — what runs, what doesn't, and what was decided along the way.

## Phase 0 — Foundation ✅

Repo scaffold, Docker Compose (Postgres + Redis), FastAPI skeleton with health and
readiness checks, Alembic migration `0001`, JWT + argon2 auth, CI running lint and the
test suite on both SQLite and Postgres.

## Phase 1 — Manual MVP ✅

Full CRUD, the Kanban board with drag-and-drop and server-owned fractional ranking, the
detail drawer, and a `status_events` row written on every transition. Transition side
effects are enforced server-side: `→ applied` stamps `applied_at` once and never again,
`→ rejected`/`withdrawn` stamps `closed_at`, and re-opening clears it.

## Phase 2 — Ingestion ✅

Async ingestion (arq worker with Redis, in-process thread pool without), URL
canonicalisation and duplicate focusing, Tier 0 JSON-LD, Tier 1 adapters for Greenhouse,
Lever, Ashby, SmartRecruiters and Workday, Tier 2 generic HTML, Tier 4 LLM structuring,
Tier 5 manual fallback, SSE progress, and `ingest_jobs` telemetry.

Tier 3 (Playwright) is implemented but **off by default** — it needs the `browser` extra
and `INGEST_BROWSER_ENABLED=1`. It costs seconds and real memory per render, so it stays
opt-in until a posting actually needs it.

## Phase 3 — Make it stick 🟡 partial

Built: full-text search (Postgres `tsvector` with prefix matching, LIKE on SQLite),
tags, staleness indicators, the Insights view, Table view with CSV export, Timeline view,
and `next_action_at` on the drawer.

Not built: reminder delivery (email/browser notification — the worker has the sweep and
logs the count, but nothing sends), the browser extension (the `/ingest/from-dom`
endpoint it would POST to is done and tested), CSV *import*, and the PWA share target.

## Phase 4 / Phase 5 — not started

Skill-gap analysis and Gmail integration are deliberately untouched. The schema is ready
for both: `company_domain` is populated at ingest for v2's email matching, and
`status_events` carries `source`, `confidence`, and `evidence` columns so an
email-derived transition is distinguishable from one you made by hand.

---

## Decisions taken while building

**Adapters run before the page fetch.** The document orders JSON-LD as Tier 0 and the ATS
adapters as Tier 1. When the hostname is a known ATS, the adapter runs first: it hits a
JSON API that's cheaper and more reliable than the HTML, so fetching the page first would
spend a request to lose a race whose outcome we already know. The tier order is otherwise
as specified.

**`ingest_status: failed` still means a usable card.** Goal G3 says 100% of URLs produce a
usable record. `failed` means no tier learned anything, not that the record is broken —
the card keeps the URL, a company guessed from the hostname, and an amber
"couldn't read posting — add details" affordance that opens the manual fallback.

**Placeholders are marked, not guessed at.** A provisional card records
`extraction_meta.guessed = ["company", "title"]`. Extraction may overwrite anything on
that list; it may never overwrite a value you typed. Without this, the "Untitled"
placeholder would block the real title forever.

**Timestamps are UTC-aware on both engines.** SQLite has no timezone-aware type, so a
custom `UTCDateTime` re-tags values on read. Without it, "days since applied" quietly
drifts by a timezone offset in local development.

**Search does prefix matching.** `plainto_tsquery` won't match "snow" against
"Snowflake", which is exactly what a search box gets used for, so the query is built with
each term prefix-matched.

**Board ordering uses float fractional indices.** A move is a single-row UPDATE. When two
neighbours get within `1e-6` of each other the column is re-spaced on the spot, inside the
same request. LexoRank would avoid the precision issue entirely and remains the upgrade
path if re-spacing ever shows up in traces.

## Open questions from README §11

Unchanged and still open. Statuses are a fixed enum (§11 Q1's recommendation), the schema
is multi-tenant while the deployment is single-user (Q2), season grouping is a tag (Q3),
and referrals are a tag today — `contacts` exists in the schema but has no UI yet (Q4).
