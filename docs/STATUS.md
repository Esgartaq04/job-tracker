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

## Phase 3 — Make it stick ✅

Full-text search (Postgres `tsvector` with prefix matching, LIKE on SQLite), tags,
staleness indicators, the Insights view, Table view, Timeline view, CSV import **and**
export, reminders, the browser extension, the mobile board, and the PWA share target.

**Reminders.** `src/services/reminders.py` is the single definition of "needs
attention" — overdue and due follow-ups first, then cards gone quiet; a card with an
explicit next action is never also nagged about silence. The worker sweeps daily and
pushes over SSE; the web app shows a needs-attention bar and can raise a desktop
notification. Email is the one piece still dark: it sits behind a `Sender` interface
whose default implementation logs. The digest renders and is tested, so switching it on
is a provider key plus one class.

**Extension.** `apps/extension` is a Manifest V3 extension using `activeTab` — no host
permissions, no content scripts, inert until you click it. It posts the rendered DOM to
the existing `/ingest/from-dom`, along with selector-read hints that only fill gaps the
tiers left. Verified end to end in Chromium against a LinkedIn-shaped fixture.

**Mobile.** Below 768px the board becomes a single column with a segmented status
switcher and a floating quick-add button; the PWA manifest registers a share target, so
the OS share sheet opens the app with the URL pre-filled.

Not built: column virtualization (`@tanstack/react-virtual`) — the board loads at most
200 cards per column today and nothing has been slow yet, so it stays on the list rather
than in the code.

## Deployment readiness ✅ (not yet deployed)

The four changes [`DEPLOYMENT.md`](./DEPLOYMENT.md) §3 asks for are done: a build-time
`VITE_API_ORIGIN` so the SPA can live on a different host than the API, `[llm]` in the API
image so Tier 4 isn't silently dead in the container, a runtime host permission for the
extension, and `POST /reminders/sweep` so a free scheduler can do the worker's daily job
where there's no Redis. `render.yaml`, `apps/web/vercel.json` and
`.github/workflows/reminders.yml` are committed.

Verified rather than assumed: the SPA built for one origin and served from another signs
in, loads the board and `/reminders`, and holds the SSE stream open with no CORS errors.

**Nothing is deployed.** That step needs accounts — Vercel, Render, Neon — and the
secrets that go with them.

## Phase 4 — The extension ✅ *(re-planned)*

**The duplicate-save bug.** Saving two jobs from one page could save the first one twice.
The extractor sent `link[rel=canonical]` whenever a page had one, and on single-page
boards that link can be stale — still naming the job the page first loaded — or drop the
query parameter that identifies this job (Google's apply form is `/apply?jobId=…`). Two
jobs then posted one URL, the server's dedup returned the first card, and the popup said
"Saved". The canonical link is now trusted only when it has the same path and keeps
every identifying parameter; otherwise the address bar wins and the stale head metadata
is stripped before the HTML is sent. LinkedIn `currentJobId` and Indeed `vjk` panes
resolve to the job's own page. The popup says "Already on your board" for a duplicate,
and a card that was already read in full is no longer patched from the posted page.

Honest note: on the public Google Careers pages, clicking between jobs *did* update the
canonical link when this was tested (Playwright, 2026-10-01), so that path wasn't the
culprit. The apply flow, which needs a signed-in Google account, couldn't be inspected; it
puts the job's identity only in the query string, which is exactly the shape the old code
collapsed. `test/spa.mjs` covers both shapes offline.

**Autofill — fill, never submit.** The popup's *Autofill application…* opens a side panel
(a popup closes the moment a file dialog takes focus). The user picks a resume, the API
reads it into a profile, and *Fill this page* fills the form. Standard fields (name,
email, phone, links, location, school) are matched by `autocomplete` or label with no
model; only the leftovers go to the model, and its answers must name a real field and a
real option. The extension sets values the way typing does (prototype setter plus
`input`/`change`), so React-controlled forms register them, attaches the resume to the
file input, and outlines what it filled in green and what it left in amber.

Not handled: custom combobox widgets (Workday's and react-select's dropdowns aren't
`<select>`s), CAPTCHAs, and essay questions all land in "needs you". A multi-page form
needs one *Fill again* per page.

## Phase 5 — AI in the tracker ✅ *(re-planned)*

**Description clean-up.** After a job is saved, a background job sends the raw
description to the model with the instruction "I have the following job description
please clean it up. DONT reword or re write it:". The reply lands in `description_clean`
only if it passes `ai_text.faithful()`; otherwise the raw text stays and
`extraction_meta.cleanup` records why. The drawer shows the cleaned text with a
*Show original* toggle and a *Clean up* button for older cards.

**Cover letters.** A *Cover letter* tab in the drawer: once the description is clean,
upload a resume (PDF or .docx) and optional notes, and the model writes a 250–400 word
letter from the cleaned description and that resume only. The letter can be edited,
copied, regenerated, and downloaded as .docx.

**Shared plumbing.** `services/ai.py` owns the client, resume intake, and the per-user
monthly cap, which existed in config but was never enforced; it is now, through an
`llm_calls` table that Tier 4 also counts against. The original Phase 4 (gated skill-gap
analysis) and Phase 5 (Gmail sync) are dropped; the email-matching hooks in the schema
stay.

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

**A job board is never the employer.** The generic tier used to read `og:site_name` and
happily record "LinkedIn" as the company. It now rejects a candidate that matches the
page's own hostname, which covers the boards nobody has added to a list yet, and parses
LinkedIn's "<Company> hiring <Title> in <Location>" title format directly.

**Extension hints are hints.** They are absorbed last, below every real tier, and marked
low-confidence. A selector that rots therefore degrades to "no hint" rather than to a
wrong record — the same principle as `guessed` placeholders.

**Drag-and-drop is not the mobile interaction.** A long-press drag inside a scrolling
list fights the scroll on touch, so each mobile card carries a status control instead.
That doubles as the menu equivalent §7.6 requires.

**CSV import guesses about columns, never about identity.** Header matching is loose
(`employer`/`company`, `role`/`position`, `link`/`url`) because no two spreadsheet
templates agree, and free-text statuses like "Online Assessment" or "No response" map
onto the enum. But a row with neither a company nor a title is skipped and reported by
line number — inventing an identity would put a card on the board that means nothing.

**The extension asks for its host when you connect, not when you install.** The design
document's fix was `host_permissions` in the manifest, but each person may point at a
different API and the manifest is a committed file. `optional_host_permissions` plus a
request from the Connect button grants exactly the origin the user typed, from the gesture
Chrome requires, with no per-deployment edit. Installing the extension still grants
nothing at all — `test/run.mjs` asserts that, because it's the kind of property that
erodes quietly.

**A missing optional dependency is tested for, not just fixed.** Tier 4 was dead in the
container because `anthropic` sits behind an extra the image didn't install, and
`tiers/llm.py` degrades on `ImportError` rather than raising — so nothing failed, the
pipeline just quietly stopped one tier early. `tests/test_packaging.py` now reads the
Dockerfile and asserts the extras it installs actually exist and include `llm`. A silent
failure needs a test more than a loud one does.

**The sweep has one definition and two callers.** The doc suggested copying the worker's
sweep body into the endpoint. It lives in `services/reminders.py::sweep` instead, called
by both the arq cron and the HTTP route, because two copies of "who gets nagged" would
diverge the first time either changed. Both failure modes of the endpoint return 404 —
an unconfigured deployment shouldn't advertise the route, and a prober shouldn't learn
that the secret is worth guessing.

**Board ordering uses float fractional indices.** A move is a single-row UPDATE. When two
neighbours get within `1e-6` of each other the column is re-spaced on the spot, inside the
same request. LexoRank would avoid the precision issue entirely and remains the upgrade
path if re-spacing ever shows up in traces.

**"Don't reword" is checked, not trusted.** A prompt can ask a model not to rewrite
text, but it can't promise it. The clean-up is accepted only when ≥97% of its 5-word runs
appear verbatim in the original (with a small allowance so a short posting survives a
repeated heading) and it kept a real share of the text. A clean-up that fails is thrown
away. A noisy description is a nuisance; one that has been quietly reworded misstates
the job.

**Resumes are never stored.** Uploaded for one call — reading a profile, writing a
letter — and discarded; a PDF goes to the model as a document block, so there isn't even
a parsed copy. The extension keeps the file in the side panel's memory and nothing else.
The cost is re-uploading for each letter, which was the explicit choice.

**Some questions are never answered for you.** Work authorization, sponsorship,
demographics, salary, criminal history, and any consent or attestation are matched by
rule *before* the model sees the form and always come back as "needs you". The model is
also told to skip them, and any answer it gives is re-checked. A wrong answer to any of
these can't be taken back once submitted.

**The autofill asks for each form's site when you use it.** Same pattern as Connect:
`optional_host_permissions` plus a request from the *Fill this page* click, for exactly
that origin. Without the `tabs` permission (which Chrome describes as "read your browsing
history") the panel can only see the tab's URL while the toolbar click's grant lasts or
once the origin is allowed, so on a brand-new site the user may need to click the toolbar
button once first. The panel says so.

**A cover letter waits for the clean-up.** Writing one against the raw scrape would let
cookie banners and "similar jobs" into the prompt. The API answers 409 until the
clean-up has run, and uses the raw text only once the clean-up has run and declined.

## Open questions from README §11

Unchanged and still open. Statuses are a fixed enum (§11 Q1's recommendation), the schema
is multi-tenant while the deployment is single-user (Q2), season grouping is a tag (Q3),
and referrals are a tag today — `contacts` exists in the schema but has no UI yet (Q4).
