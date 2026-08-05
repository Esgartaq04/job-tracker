# Job & Internship Application Tracker — Design Document

> **Status:** Draft v0.1 · **Owner:** Esteven · **Last updated:** 2026-08-04

---

## 1. Overview

A personal web app for tracking job and internship applications end to end. The user pastes a posting URL, the system builds a structured **Application** record from it, and the user manages that record's lifecycle on a Jira-style **Kanban board**.

The product bet: *the cost of logging an application is the reason people stop logging applications.* Every design decision below optimizes for **time-to-log ≤ 5 seconds** and **zero manual data entry in the happy path**.

### 1.1 Goals

| # | Goal | Success signal |
|---|---|---|
| G1 | Create a tracked application from a URL alone | ≥80% of pastes auto-fill company, title, and description with no edits |
| G2 | Make pipeline state visible at a glance | User can answer "what's stalled?" in under 5 seconds |
| G3 | Never lose data to a failed scrape | 100% of URLs produce a usable record, even if degraded |
| G4 | Keep status current with minimal effort | v2: ≥60% of status changes originate from email signals |

### 1.2 Non-goals (explicitly out of scope)

- **Auto-applying to jobs.** Distinct product, distinct risk profile. Keep it separate.
- **Job discovery / search aggregation.** This tool tracks what the user found elsewhere.
- **Multi-user, teams, or recruiter-side features.** Single-tenant per user.
- **Mobile native apps.** Responsive web only.

---

## 2. Key Design Decision: `Saved` vs `Applied`

Your spec says the application date is recorded when the link is added. In practice, people paste URLs at two different moments:

1. **"This looks interesting"** — bookmarking, hasn't applied yet.
2. **"I just submitted"** — logging a completed application.

If those collapse into one timestamp, every "days since applied" metric is wrong and the funnel analytics are meaningless.

**Resolution:** the model carries two nullable timestamps.

- `saved_at` — set automatically on creation, always.
- `applied_at` — set when the card first enters `Applied` (or later), editable.

The board gets a **`Saved`** column to the left of `Applied`. A paste lands in `Saved` by default; dragging it to `Applied` stamps `applied_at = now()`. A "Paste & mark as applied" affordance sets both in one action for case 2.

Cards display *days since applied* when `applied_at` exists, and *days since saved* otherwise.

---

## 3. Technology Stack

Chosen to lean on what you already run in production and to keep the deployment surface small.

| Layer | Choice | Rationale |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite | Existing React experience; Vite for fast HMR |
| State/data | TanStack Query + Zustand | Server cache vs. UI state cleanly separated; optimistic updates for drag/drop |
| Drag & drop | `@dnd-kit/core` + `@dnd-kit/sortable` | Actively maintained, accessible, keyboard-navigable (`react-beautiful-dnd` is archived) |
| Styling | Tailwind CSS + shadcn/ui | Component primitives without a heavy design-system commitment |
| Backend | Python 3.12 + FastAPI + Pydantic v2 | Your strongest language; Pydantic doubles as the extraction schema for AI/JSON-LD |
| ORM | SQLAlchemy 2.0 + Alembic | Already familiar from prior RDS work |
| Database | PostgreSQL 16 | JSONB for raw extraction payloads, `tsvector` for full-text search, real transactions |
| Task queue | Celery + Redis *(or* `arq` *for a lighter footprint)* | URL scraping must be async — it can take 15s+ |
| Scraping | `httpx` → `selectolax`/`BeautifulSoup` → Playwright (fallback tier) | Cheap paths first, expensive browser last |
| Auth | Auth.js / Clerk, or FastAPI + JWT + `argon2` | v2 needs Google OAuth anyway — pick a provider that federates |
| Hosting | GCP: Cloud Run (API + worker), Cloud SQL, Memorystore | Matches your existing GCP footprint; Cloud Run scales to zero |
| Object storage | GCS | Resume/cover-letter versions |
| Observability | Structured JSON logs → Cloud Logging; Sentry | Ingestion failures need to be debuggable from the URL alone |

**Deliberate omissions:** no microservices, no Kafka, no GraphQL. A single FastAPI service plus one worker process handles this workload for a long time.

---

## 4. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser — React SPA                                         │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────────┐     │
│  │ Kanban     │  │ Detail       │  │ Quick-Add         │     │
│  │ Board      │  │ Drawer       │  │ (URL paste)       │     │
│  └────────────┘  └──────────────┘  └───────────────────┘     │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTPS / REST + SSE
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI (Cloud Run)                                         │
│   /auth  /applications  /ingest  /events  /search  /stats    │
│   ├─ AuthN/AuthZ middleware (per-user row scoping)           │
│   └─ Enqueue → Redis                                         │
└──────┬───────────────────────────────────┬───────────────────┘
       │                                   │
┌──────▼────────────┐            ┌─────────▼──────────────────┐
│  PostgreSQL       │            │  Worker (Celery/arq)       │
│  applications     │◄───────────┤   ┌──────────────────────┐ │
│  status_events    │            │   │ Ingestion Pipeline   │ │
│  ingest_jobs      │            │   │  T0 JSON-LD          │ │
│  documents        │            │   │  T1 ATS adapters     │ │
│  email_links (v2) │            │   │  T2 generic HTML     │ │
└───────────────────┘            │   │  T3 Playwright       │ │
                                 │   │  T4 LLM structuring  │ │
┌───────────────────┐            │   └──────────────────────┘ │
│  GCS (documents)  │◄───────────┤   Reminder / stale sweeps  │
└───────────────────┘            │   Gmail sync (v2)          │
                                 └────────────────────────────┘
```

### 4.1 Ingestion Pipeline (the hard part)

`POST /ingest` returns **immediately** with a provisional application record (status `Saved`, `title = "Untitled"`, `ingest_status = pending`). The card appears on the board instantly and fills in as the worker resolves it. Progress streams to the client over SSE on `/events`.

Tiers are attempted in order; the first success wins.

**Tier 0 — Structured markup.** Parse `<script type="application/ld+json">` for a schema.org `JobPosting` object. Gives title, hiringOrganization, datePosted, employmentType, baseSalary, jobLocation, and a full HTML description. Free, fast, and surprisingly common because it drives Google Jobs indexing.

**Tier 1 — Known-host adapters.** Detect the ATS from the hostname and hit its public JSON API instead of parsing HTML:

| ATS | URL pattern | Endpoint |
|---|---|---|
| Greenhouse | `boards.greenhouse.io/{co}/jobs/{id}` | `boards-api.greenhouse.io/v1/boards/{co}/jobs/{id}` |
| Lever | `jobs.lever.co/{co}/{uuid}` | `api.lever.co/v0/postings/{co}/{uuid}` |
| Ashby | `jobs.ashbyhq.com/{co}/{uuid}` | Public posting API |
| SmartRecruiters | `jobs.smartrecruiters.com/...` | `api.smartrecruiters.com/v1/companies/{co}/postings/{id}` |
| Workday | `{co}.wd*.myworkdayjobs.com/...` | JSON endpoint derived from the path |

These four or five adapters cover a large share of real early-career postings. Each adapter is a small class implementing `matches(url) -> bool` and `fetch(url) -> RawPosting`, registered in a list — adding an ATS is a ~40-line file.

**Tier 2 — Generic HTML.** Fetch with a realistic UA, run readability-style main-content extraction, pull `og:title` / `og:site_name` / `<title>` for metadata.

**Tier 3 — Headless browser.** Playwright with a shared browser pool for JS-rendered SPA postings. Expensive (~3–8s, meaningful memory); rate-limit it and cache aggressively.

**Tier 4 — LLM structuring.** Feed the cleaned text to a model with a Pydantic schema and get typed fields back. See §8 — this is the AI use case that actually pays for itself.

**Tier 5 — Manual fallback.** Always reachable. The drawer shows a "Paste the description yourself" textarea. The record is never blocked on ingestion.

#### Sites that will fight you

LinkedIn, Indeed, Glassdoor, and ZipRecruiter run aggressive bot detection, and their Terms of Service prohibit automated scraping. Do not build the product's core loop on top of them.

Mitigations, in order of preference:
1. **Browser extension** (Phase 3): the user is already authenticated and viewing the page; the extension reads the rendered DOM and POSTs it to `/ingest/from-dom`. This sidesteps scraping entirely, since the user's own browser is doing the reading.
2. **Share-target / paste-the-text** flow: user copies the description, app parses the text blob.
3. **Degrade gracefully:** save the URL, extract the company from the hostname if possible, and prompt for manual entry.

Also: postings are frequently taken down. Store `description_raw` on first fetch and never re-fetch destructively — the archived copy is often the only remaining record by interview time.

### 4.2 Caching & idempotency

- Normalize URLs (strip `utm_*`, `gh_src`, `refId`, fragments) into `canonical_url`.
- Unique index on `(user_id, canonical_url)` — re-pasting a known URL focuses the existing card instead of creating a duplicate.
- Cache raw fetch results in Redis keyed by `canonical_url` for 24h so retries and multi-user pastes don't re-hit the origin.

---

## 5. Data Model

```sql
-- ─── core ────────────────────────────────────────────────────────────
CREATE TYPE app_status AS ENUM (
  'saved', 'applied', 'oa', 'phone_screen',
  'interview', 'final', 'offer', 'rejected', 'withdrawn', 'ghosted'
);

CREATE TABLE applications (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- source
    source_url        TEXT NOT NULL,
    canonical_url     TEXT NOT NULL,
    source_host       TEXT,              -- 'boards.greenhouse.io'
    ats_vendor        TEXT,              -- 'greenhouse' | 'lever' | ...

    -- identity
    company           TEXT,
    company_domain    TEXT,              -- v2 email matching key
    title             TEXT,
    location          TEXT,
    is_remote         BOOLEAN,
    employment_type   TEXT,              -- 'internship' | 'full_time' | 'coop'
    req_id            TEXT,              -- ATS requisition number

    -- compensation (nullable; rarely present)
    salary_min        NUMERIC,
    salary_max        NUMERIC,
    salary_currency   CHAR(3),
    salary_period     TEXT,              -- 'hourly' | 'yearly'

    -- description: raw is immutable, edited is user-owned
    description_raw   TEXT,
    description_html  TEXT,
    description_user  TEXT,              -- user edits live here
    extraction_meta   JSONB DEFAULT '{}',-- tier used, confidence, timings

    -- lifecycle
    status            app_status NOT NULL DEFAULT 'saved',
    board_position    NUMERIC NOT NULL,  -- fractional ranking, see below
    saved_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at        TIMESTAMPTZ,
    posted_at         TIMESTAMPTZ,
    closed_at         TIMESTAMPTZ,
    next_action_at    TIMESTAMPTZ,       -- reminder
    priority          SMALLINT DEFAULT 0,

    ingest_status     TEXT NOT NULL DEFAULT 'pending',  -- pending|ok|partial|failed
    notes             TEXT,
    archived_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    search_vector     TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english',
          coalesce(company,'') || ' ' || coalesce(title,'') || ' ' ||
          coalesce(location,'') || ' ' || coalesce(description_user, description_raw,''))
    ) STORED
);

CREATE UNIQUE INDEX ux_app_user_url ON applications(user_id, canonical_url)
  WHERE archived_at IS NULL;
CREATE INDEX ix_app_board ON applications(user_id, status, board_position)
  WHERE archived_at IS NULL;
CREATE INDEX ix_app_search ON applications USING GIN(search_vector);

-- ─── audit trail: powers analytics and the timeline UI ───────────────
CREATE TABLE status_events (
    id              BIGSERIAL PRIMARY KEY,
    application_id  UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status     app_status,
    to_status       app_status NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT NOT NULL DEFAULT 'manual', -- manual|email|system|ai
    confidence      REAL,
    note            TEXT,
    evidence        JSONB           -- v2: {message_id, snippet, matched_rule}
);

-- ─── supporting ──────────────────────────────────────────────────────
CREATE TABLE tags (
    id UUID PRIMARY KEY, user_id UUID NOT NULL, name TEXT NOT NULL, color TEXT,
    UNIQUE(user_id, name)
);
CREATE TABLE application_tags (
    application_id UUID REFERENCES applications(id) ON DELETE CASCADE,
    tag_id         UUID REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (application_id, tag_id)
);

CREATE TABLE documents (           -- which resume version went to which company
    id UUID PRIMARY KEY, user_id UUID NOT NULL,
    application_id UUID REFERENCES applications(id) ON DELETE SET NULL,
    kind TEXT,                     -- 'resume' | 'cover_letter' | 'portfolio'
    label TEXT, gcs_path TEXT, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE contacts (            -- recruiters, referrals
    id UUID PRIMARY KEY, user_id UUID NOT NULL,
    application_id UUID REFERENCES applications(id) ON DELETE CASCADE,
    name TEXT, email TEXT, role TEXT, linkedin_url TEXT, notes TEXT
);

CREATE TABLE ingest_jobs (         -- observability for the pipeline
    id UUID PRIMARY KEY, application_id UUID REFERENCES applications(id),
    url TEXT, tier_attempted TEXT[], tier_succeeded TEXT,
    attempts INT DEFAULT 0, error TEXT, duration_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 5.1 Board ordering

`board_position` is a **fractional index**, not a dense integer. Dropping a card between neighbors `a` and `b` sets `position = (a + b) / 2`, which makes reordering a **single-row UPDATE** instead of renumbering the column. A background job re-spaces a column when float precision degrades (after ~50 subdivisions between the same pair). If you prefer strings, LexoRank gives the same property without precision loss.

### 5.2 Why a separate `status_events` table

The current status lives on `applications` for fast board reads, but every transition is also appended to `status_events`. That gives you, for free:

- The timeline view in the detail drawer.
- Funnel conversion rates (`applied → interview` %, per company or per season).
- Time-in-stage metrics that drive stale detection.
- An audit trail for v2, where AI proposes transitions and you need to see *why*.

---

## 6. API Surface

REST, JSON, all routes scoped to the authenticated user.

```
POST   /api/v1/ingest                  { url, mark_as_applied?: bool }
                                       → 202 { application_id, ingest_status }
POST   /api/v1/ingest/from-dom         { url, html }        # browser extension
POST   /api/v1/ingest/from-text        { text, url? }       # manual fallback
POST   /api/v1/applications/{id}/reingest

GET    /api/v1/applications            ?status=&q=&tag=&sort=&cursor=
GET    /api/v1/applications/board      → { columns: [{status, count, items[]}] }
POST   /api/v1/applications            # fully manual create
GET    /api/v1/applications/{id}
PATCH  /api/v1/applications/{id}       # partial; description_user, company, ...
DELETE /api/v1/applications/{id}       # soft delete → archived_at

PATCH  /api/v1/applications/{id}/move  { to_status, before_id?, after_id? }
                                       → recomputes board_position server-side

GET    /api/v1/applications/{id}/events
POST   /api/v1/applications/{id}/notes
POST   /api/v1/applications/{id}/documents

GET    /api/v1/stats/funnel            ?from=&to=
GET    /api/v1/stats/velocity          # apps/week, time-in-stage
GET    /api/v1/search                  ?q=            # full-text

GET    /api/v1/events                  # SSE: ingest progress, email-derived updates
```

**On `/move`:** the client sends *neighbor IDs*, not a computed position. The server owns ranking. This prevents two tabs from computing conflicting positions and keeps the fractional-index logic in one place.

**Optimistic UI contract:** the client applies the move locally, fires the PATCH, and reverts on non-2xx. Column counts update immediately. TanStack Query's `onMutate`/`onError` rollback handles this cleanly.

---

## 7. UI Layout

### 7.1 Board view (default)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ⬢ Tracker    [ 🔗 Paste a job URL…              ] [+]   🔍  ⚙  👤          │
├────────────────────────────────────────────────────────────────────────────┤
│  Board │ Table │ Timeline │ Insights        Filters: [Internship ×] [2026 ×]│
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  SAVED (12)     APPLIED (34)    OA (6)        INTERVIEW (3)   OFFER (1)     │
│  ┌───────────┐  ┌───────────┐   ┌──────────┐  ┌───────────┐   ┌──────────┐  │
│  │▨ Stripe   │  │▨ Datadog  │   │▨ Nvidia  │  │▨ Google   │   │▨ Cisco   │  │
│  │ SWE Intern│  │ Backend In│   │ ML Intern│  │ STEP      │   │ SWE Int  │  │
│  │ ⚲ NYC     │  │ ⚲ Remote  │   │ ⚲ Santa C│  │ ⚲ Chicago │   │ ⚲ Chicago│  │
│  │ ⏱ saved 2d│  │ ⏱ 14d ⚠   │   │ ⏱ due 3d │  │ ⏱ Aug 12  │   │ ⏱ 2d     │  │
│  │ #referral │  │           │   │ 🔴 HackerR│  │ 📧 2      │   │ 💰 $52/h │  │
│  └───────────┘  └───────────┘   └──────────┘  └───────────┘   └──────────┘  │
│  ┌───────────┐  ┌───────────┐   ┌──────────┐                               │
│  │ ⟳ loading…│  │▨ Snowflake│   │▨ Citadel │       …  REJECTED (19) ▸      │
│  └───────────┘  └───────────┘   └──────────┘          (collapsed)          │
└────────────────────────────────────────────────────────────────────────────┘
```

**Columns.** Horizontally scrollable, each independently virtualized (`@tanstack/react-virtual`) so a 200-card `Rejected` column doesn't stall the board. Terminal columns (`Rejected`, `Withdrawn`, `Ghosted`) are collapsible to a vertical rail and collapsed by default — they're the largest and least useful columns, and letting them dominate the board is demoralizing.

**Card anatomy.** Company favicon (via `https://www.google.com/s2/favicons?domain=` or a self-hosted logo proxy), role title (2-line clamp), company name, location chip, an age/deadline indicator, and up to two tag pills. Nothing else — card density is the whole point of a board.

**Staleness.** A card shows ⚠ amber at 14 days in `Applied` with no movement, and dims to grey at 30. Configurable per column. This is the single highest-value passive feature: it surfaces the applications that need a nudge without any user input.

**Drag & drop.** `@dnd-kit` with a 5px activation constraint (so clicks still open the drawer), a drop-shadow ghost, and keyboard support (`Space` to lift, arrows to move, `Space` to drop) with `aria-live` announcements. Cross-column drops trigger transition side effects:

| Transition | Side effect |
|---|---|
| `→ applied` | Stamp `applied_at` if null |
| `→ oa` | Prompt for a deadline, set `next_action_at` |
| `→ interview` | Prompt for date/time; offer .ics download |
| `→ offer` | Prompt for comp details; confetti (earned) |
| `→ rejected` | Stamp `closed_at`, optional one-tap reason |

### 7.2 Quick-add

The URL field is a persistent element in the top bar, focused by a global `/` or `⌘K` shortcut. On paste:

1. Optimistic skeleton card animates into `Saved` immediately.
2. SSE fills in company → title → location → description as tiers resolve.
3. On failure the card turns amber with "Couldn't read this posting — add details" and opens the drawer on click.

Supports multi-line paste: several URLs at once queue as a batch.

### 7.3 Detail drawer

Right-hand slide-over at ~640px (full-screen on mobile), opened by clicking a card. Never a route change — the board stays mounted behind it.

```
┌────────────────────────────────────────────────┐
│ ▨ Datadog · Backend Engineering Intern      ✕  │
│ ⚲ Remote (US) · Internship · Applied Jul 21    │
│ [ Status: Applied ▾ ]  [ Open posting ↗ ]      │
├────────────────────────────────────────────────┤
│ Overview │ Description │ Timeline │ Files │📧  │
├────────────────────────────────────────────────┤
│                                                │
│  Description                  [Edit] [Restore] │
│  ┌──────────────────────────────────────────┐  │
│  │ ## About the role                        │  │
│  │ You'll work on the data ingestion…       │  │
│  └──────────────────────────────────────────┘  │
│  Extracted via greenhouse-api · Jul 21         │
│                                                │
│  Notes ─────────────────────────────────────   │
│  Referred by Andres — mentioned team is on Go  │
│                                                │
│  Next action ───────────────────────────────   │
│  ☐ Follow up with recruiter    Aug 8  [set]    │
└────────────────────────────────────────────────┘
```

**Description editing.** Markdown editor. `description_user` shadows `description_raw`; "Restore original" always works because the raw copy is immutable. A subtle line records which extraction tier produced the text — useful when a field looks wrong.

### 7.4 Secondary views

- **Table** — dense sortable grid, bulk edit, CSV export. Better than a board for "show me every application from March."
- **Timeline** — Gantt-ish horizontal lanes showing each application's stage durations. Makes ghosting patterns obvious.
- **Insights** — funnel conversion, applications per week, response rate by source/ATS, median time-to-first-response, outcome by resume version.

### 7.5 Responsive behavior

Below 768px the board becomes a single column with a segmented status switcher at the top; long-press initiates drag, or the status dropdown in the card menu moves it. Quick-add moves to a floating action button, and the app registers as a **PWA share target** so the mobile share sheet can send a URL straight into the tracker — the single biggest mobile-capture win.

### 7.6 Accessibility

Every drag interaction has a keyboard and menu equivalent. Status is never communicated by color alone (column position + text label carry it). Focus returns to the originating card when the drawer closes. Target WCAG 2.1 AA.

---

## 8. AI Integration — Framing the Undecided Piece

The useful question isn't "should this app have AI" but **"which parts of it are unreliable enough that a probabilistic system is an upgrade?"** Two of the candidates below clear that bar; the rest are features looking for a justification.

| Candidate | Value | Cost/risk | Verdict |
|---|---|---|---|
| **A. Structured extraction fallback** | High — directly serves G1/G3 | Low; runs only when Tiers 0–3 fail; schema-constrained output | **Build (Phase 2)** |
| **B. Email → status classification** | High — the entire premise of v2 | Medium; wrong transitions erode trust | **Build (v2), with confirmation UX** |
| **C. Resume ↔ JD gap analysis** | Medium — genuinely useful, but a separate mental mode from tracking | Medium; needs resume parsing, invites over-tailoring | **Defer to Phase 4, gate on demand** |
| **D. Cover letter generation** | Low — commoditized, adjacent to the auto-apply product you scoped out | Low | **Skip** |
| **E. Interview prep from JD** | Medium-low — nice, not core | Low | **Backlog** |
| **F. "Chat with your applications"** | Low — a search box answers 95% of it | Medium | **Skip** |

### 8.1 Candidate A — extraction fallback (recommended)

The pattern is *AI as plumbing, not as a feature*. The user never sees a model; they see a card that filled itself in.

```python
class ExtractedPosting(BaseModel):
    company: str | None
    title: str | None
    location: str | None
    is_remote: bool | None
    employment_type: Literal["internship","full_time","co_op","contract"] | None
    posted_at: date | None
    salary_min: float | None
    salary_max: float | None
    salary_period: Literal["hourly","monthly","yearly"] | None
    required_skills: list[str] = []
    description_markdown: str
    confidence: float                    # model's own 0–1 estimate
```

Guardrails that make this safe:
- Constrained decoding against the schema — no free-form parsing of model prose.
- Truncate input to ~8k tokens of *cleaned* text (strip nav, footers, cookie banners) to control cost.
- Cache by `canonical_url` — one extraction per posting, ever.
- Any field with `confidence < 0.6` renders with a dotted underline and a "verify" affordance rather than silently populating.
- Record the tier in `extraction_meta` so you can measure how often the LLM path is even reached. If it's under 15%, the adapters are doing their job.

### 8.2 Candidate C — skill matching (deferred, with a caveat)

The naive version — cosine similarity between a JD embedding and a resume embedding — produces a percentage that looks authoritative and means nothing. If you build this, build the version that's actually actionable:

> **Not covered by your resume:** Kubernetes, gRPC, "distributed tracing"
> **Covered but not prominent:** Go (appears once, in a project bullet)

That's a diff, not a score. It tells the user what to *do*. Extract required skills into a normalized taxonomy at ingest time (cheap, already happening in Candidate A), then set-difference against a parsed resume. Consider a rules-first implementation with an LLM assist for synonym collapsing (`"K8s" ≈ "Kubernetes"`), rather than an end-to-end model call.

**Decision checkpoint:** revisit after Phase 3, once there are ≥100 real applications in the system. Skill matching on an empty database can't be evaluated.

### 8.3 Cost model

At roughly 30 applications/week with a 15% LLM-fallback rate, that's ~5 extraction calls/week — pennies. This stays negligible until multi-user. Track spend per user from day one anyway; add a monthly cap and degrade to Tier 5 (manual) when it's hit.

---

## 9. v2 — Email Integration

The most valuable and most expensive feature in the doc. It's specified here so Phase 1–3 decisions don't foreclose it, but it should not be started before the core loop is solid.

### 9.1 Access model

Gmail API via OAuth 2.0. Scope selection determines your compliance burden and is the key decision:

| Scope | Grants | Verification burden |
|---|---|---|
| `gmail.metadata` | Headers only — From, To, Subject, Date. No bodies. | **Restricted** scope |
| `gmail.readonly` | Full message content | **Restricted** scope + likely CASA Tier 2 assessment |

Both are *restricted* scopes, meaning Google requires an app verification review — and for restricted scopes an annual third-party security assessment (CASA) with real cost and multi-week turnaround. **Verify current requirements and pricing at the Google API Services User Data Policy before committing.** Budget calendar time, not just engineering time.

**Recommended path:** ship with `gmail.metadata` first. Subject lines and sender domains alone resolve a surprising fraction of status transitions ("Your application to Datadog", "Interview invitation — Nvidia"). Escalate to `readonly` only if metadata-only accuracy proves insufficient, and note that unverified apps can still be used by up to 100 test users — enough to validate the idea before paying for review.

### 9.2 Sync mechanism

Polling is wasteful and laggy. Use push:

1. `users.watch` registers a Cloud Pub/Sub topic and returns a `historyId`.
2. Gmail publishes a notification on mailbox change.
3. A Cloud Run push endpoint receives it and calls `users.history.list(startHistoryId=…)` for the delta.
4. Re-register the watch every ~7 days (registrations expire).
5. Persist `last_history_id` per user; fall back to a full scan if the stored ID has expired.

### 9.3 Matching emails to applications

A cascade, highest-precision first:

1. **ATS message-ID / sender domain + req ID.** Greenhouse, Lever, Workday, and Ashby send from predictable domains and often embed the requisition ID. Near-certain match.
2. **Company domain match.** `applications.company_domain` vs. the sender's domain, resolved through a `no-reply@` → root-domain normalization step.
3. **Thread continuity.** Once a thread is linked, all future messages in that `threadId` inherit the link.
4. **Fuzzy company + title in subject.** Trigram similarity against `company` and `title`, thresholded.
5. **LLM disambiguation** — only when 2+ candidates survive step 4, and only with the candidates' metadata in context (not the whole database).

Store links in a dedicated table; keep message IDs and derived fields, **not full bodies**:

```sql
CREATE TABLE email_links (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL,
    application_id  UUID REFERENCES applications(id) ON DELETE CASCADE,
    gmail_message_id TEXT NOT NULL,
    gmail_thread_id  TEXT NOT NULL,
    sender          TEXT,
    subject         TEXT,
    received_at     TIMESTAMPTZ,
    match_rule      TEXT,        -- 'ats_domain' | 'company_domain' | 'llm' | 'manual'
    match_confidence REAL,
    inferred_status app_status,
    applied         BOOLEAN DEFAULT false,   -- did the user accept the suggestion?
    UNIQUE(user_id, gmail_message_id)
);
```

### 9.4 Suggestion, not automation

**Never auto-move a card on an email signal below high confidence.** A false "Rejected" is a genuinely upsetting bug. The interaction model:

- Confidence ≥ 0.9 **and** rule ∈ {ats_domain, thread_continuity} → apply automatically, show an undo toast for 10s, log `source='email'` in `status_events`.
- Otherwise → the card shows a 📧 badge and the drawer offers *"Looks like Datadog moved you to Interview — apply this?"* with Accept / Dismiss.
- Every accept/dismiss is training signal for threshold tuning. Track precision per `match_rule`.

### 9.5 Privacy posture

Even as a single-user app, build this correctly from the start:

- OAuth refresh tokens encrypted at rest (Cloud KMS envelope encryption), never logged.
- Store subject/sender/snippet only; discard bodies after classification.
- A visible "Connected accounts" screen with one-click disconnect that purges tokens and `email_links`.
- Full data export and account deletion endpoints.
- If it ever goes multi-user, a privacy policy is mandatory — Google's verification requires one, and it must specifically describe the Gmail data use.

---

## 10. Delivery Phases

Each phase ends in something usable. Estimates assume part-time work alongside coursework and an internship.

### Phase 0 — Foundation *(~1 week)*
Repo scaffold, Docker Compose (Postgres + Redis), FastAPI skeleton with health check, Alembic migration 001, auth, CI running lint + tests, Cloud Run deploy from `main`.
**Exit:** a deployed, authenticated "hello world" with a migrated database.

### Phase 1 — Manual MVP *(~2 weeks)*
Full CRUD on applications, the Kanban board with working drag-and-drop and persisted ordering, the detail drawer, `status_events` written on every transition.
**Exit:** you can track your real applications by typing them in. **Start using it yourself here** — every subsequent priority should come from that experience, not from this document.

### Phase 2 — Ingestion *(~2–3 weeks)*
Async worker, URL normalization, Tier 0 (JSON-LD), Tier 1 adapters for Greenhouse + Lever + Workday, Tier 2 generic HTML, Tier 4 LLM fallback, SSE progress, manual fallback UI, `ingest_jobs` telemetry.
**Exit:** paste-to-card in under 10 seconds for ≥80% of postings.

### Phase 3 — Make it stick *(~2 weeks)*
Full-text search, filters, tags, staleness indicators, reminders (`next_action_at` + email/browser notification), the Insights view, CSV import/export, browser extension for LinkedIn/Indeed capture, PWA share target.
**Exit:** the app tells you something you didn't already know about your own pipeline.

### Phase 4 — AI, conditionally *(~2 weeks, gated)*
Only if Phase 3 usage shows demand. Skill gap analysis, resume version tracking against outcomes, interview prep generation.
**Gate:** ≥100 applications logged and a specific articulated need. If neither, skip to v2.

### Phase 5 — v2 Email *(~4+ weeks, plus verification lead time)*
Google OAuth, Pub/Sub watch, matching cascade, suggestion UI, privacy screens, verification submission.
**Exit:** status changes start arriving without you touching the board.

---

## 11. Risks & Open Questions

| Risk | Impact | Mitigation |
|---|---|---|
| LinkedIn/Indeed blocking or ToS conflict | Core flow fails on the most-used sites | Browser extension path; never depend on scraping them server-side |
| Gmail restricted-scope verification cost/delay | v2 blocked for weeks | Start with `gmail.metadata`; test-user mode (≤100 users) validates before paying |
| Playwright memory/cost on Cloud Run | Ingestion becomes expensive | Separate low-concurrency service; strict rate limit; cache hard |
| ATS adapters rot silently | Extraction quality degrades unnoticed | Golden-URL contract tests in CI; alert when Tier-4 fallback rate crosses 25% |
| False email-driven status changes | Trust destroyed instantly | Confidence gating + confirm-first UX + undo |
| Scope creep into auto-apply | Never ships | The non-goals in §1.2 are load-bearing |

**Open questions to resolve before Phase 2:**

1. Should status columns be user-configurable, or is the fixed enum sufficient? *(Recommendation: fixed for v1 — configurable columns complicate analytics, migrations, and the email classifier's target space. Revisit only if the enum genuinely doesn't fit.)*
2. Multi-user from day one, or single-tenant? *(The schema above is multi-user-ready via `user_id`; the auth and privacy work is what differs. Recommendation: build the schema multi-tenant, deploy single-user.)*
3. Do you want cycle/season grouping (Fall 2026 recruiting vs. Summer 2027) as a first-class concept, or is a tag enough? *(Tag is probably enough until it isn't.)*
4. Where do referrals live — a `contacts` row, a tag, or a first-class field? Referral status meaningfully changes follow-up behavior.

---

## 12. Appendix — Repository Layout

```
job-tracker/
├── apps/
│   ├── api/
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── routers/          # applications, ingest, stats, auth, events
│   │   │   ├── models/           # SQLAlchemy
│   │   │   ├── schemas/          # Pydantic (shared with extraction)
│   │   │   ├── services/
│   │   │   │   ├── ingestion/
│   │   │   │   │   ├── pipeline.py
│   │   │   │   │   ├── normalize.py
│   │   │   │   │   ├── adapters/  # greenhouse.py, lever.py, workday.py, …
│   │   │   │   │   └── tiers/     # jsonld.py, generic.py, browser.py, llm.py
│   │   │   │   ├── ranking.py     # fractional index math
│   │   │   │   └── email/         # v2
│   │   │   └── core/              # config, db, security, deps
│   │   ├── alembic/
│   │   └── tests/
│   ├── worker/
│   ├── web/
│   │   └── src/
│   │       ├── features/
│   │       │   ├── board/         # Board, Column, Card, DragContext
│   │       │   ├── detail/        # Drawer, DescriptionEditor, Timeline
│   │       │   ├── quickadd/
│   │       │   └── insights/
│   │       ├── api/               # generated client + TanStack hooks
│   │       └── lib/
│   └── extension/                 # Phase 3 — MV3
├── infra/                         # Terraform: Cloud Run, Cloud SQL, Pub/Sub
├── docker-compose.yml
└── README.md
```

---

*This document should be revised at the end of every phase. If Phase 1 usage contradicts something here, the document is wrong, not the usage.*
