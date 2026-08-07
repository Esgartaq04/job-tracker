# Deploying

Written against the repo at `main`, not against README §3. The design document specifies
Cloud Run + Cloud SQL + Memorystore, and `infra/main.tf` sketches it; that is a production
footprint this workload does not have. What follows deploys **the code that exists today**
for four people, at roughly zero, without foreclosing Phase 4 or Phase 5.

Nothing is deployed yet, so there is no migration to plan around — only a first choice.

**Status:** the four code changes in §3 are done, tested, and merged; §4 is the part that
needs accounts, and the accounts are yours to create. §3.1's cross-origin path has been
exercised in a browser rather than reasoned about — see the note in §4.3.

---

## 1. What the repo already decided for you

Four things in the code determine the deployment shape. They're worth stating before the
plan, because three of them contradict the obvious "just put it on Vercel" answer.

**The API needs a process that outlives a request.** `services/ingestion/queue.py` falls
back to a `ThreadPoolExecutor` when `REDIS_URL` is unset, and `POST /ingest` returns `202`
before the tiers run. `services/events.py` falls back to an in-process `EventHub`, and
`routers/events.py` holds an SSE connection open with a 20-second heartbeat. On serverless
functions the ingest thread is killed at response time and the SSE hub isn't shared
between invocations, so **the API cannot go on Vercel Functions** without rewriting both.

**The web app assumed the API was same-origin.** `apps/web/src/api/client.ts` hardcoded
`const API_BASE = "/api/v1"`; in dev the Vite proxy provides it, in Docker `nginx.conf`
provides it. Vercel provides neither. §3.1 replaced it with a build-time origin that
defaults to empty, so both existing setups are untouched.

**Auth makes cross-origin easy.** The token is a bearer JWT in `localStorage`, and
`/events` accepts `?access_token=` because `EventSource` can't set headers. No cookies
means no `SameSite` problem, no subdomain requirement — just `CORS_ORIGINS`.

**Redis is optional, and losing it costs exactly one thing.** Without it: ingestion runs
in-process, SSE runs in-memory, the fetch cache is per-process. All fine at one instance.
What you actually lose is the **daily reminder sweep**, which existed only as an arq cron
in `apps/worker/worker.py`. `GET /reminders` computes on demand, so the needs-attention bar
and the whole reminders feature still work — what goes missing is the unprompted daily
push. §3.4 adds that back over HTTP, on a free scheduler.

---

## 2. The plan

| Piece | Where | Cost |
|---|---|---|
| `apps/web` (Vite SPA) | Vercel Hobby | $0 |
| `apps/api` (FastAPI + in-process ingestion + SSE) | Render free web service → Fly when it annoys you | $0 → ~$2–4/mo |
| Postgres | Neon free plan | $0 |
| Redis | not deployed (`REDIS_URL` unset) | $0 |
| `apps/worker` | not deployed (no Redis to consume) | $0 |
| Tier 3 Playwright | not installed (`INGEST_BROWSER_ENABLED` stays `0`) | $0 |
| Tier 4 LLM | Anthropic API, capped at 500 calls/month in config | ~$0–2/mo |

**Verify every free tier before committing** — all three providers changed theirs in the
last eighteen months.

**Why Render free first:** 512 MB / 0.1 CPU, spins down after 15 minutes idle with a
30–60 second cold start, 750 instance-hours per month (one always-on service, nothing
else). The cold start is the whole cost. Ingestion in flight when it sleeps is lost, which
is recoverable — `POST /api/v1/applications/{id}/reingest` — and rare at four users.

**Why Fly next:** `shared-cpu-1x` at 512 MB is about $2–4/month always-on, no free
allowance for new orgs since 2024, and none of the above problems. Same image, same env
vars; moving is a `fly launch` and a DNS change.

**Do not use your app host's free Postgres.** Render's free database expires 30 days after
creation. Neon's free plan is permanent (0.5 GB storage, 100 CU-hours/month,
scale-to-zero). This app is the record of where you applied.

---

## 3. Code changes — done

All four are now in the repo, so this section is a record of what changed and why rather
than a to-do list. Nothing here alters local development or `docker compose up`: both
still run same-origin with no configuration.

### 3.1 The API origin is configurable

`apps/web/src/api/client.ts` builds its base from an environment variable that defaults
to empty, which is the same-origin path:

```ts
const API_ORIGIN = (import.meta.env.VITE_API_ORIGIN ?? "").replace(/\/$/, "");
const API_BASE = `${API_ORIGIN}/api/v1`;
```

`hooks.ts` no longer builds its own URL for the CSV upload — it imports `API_BASE` like
everything else, so there is one place that knows where the API lives. `public/sw.js`
also skips any cross-origin request rather than only `/api/` paths, which keeps the
service worker out of the way of both the API and the SSE stream once they move hosts.

`apps/web/.env.example` documents the variable. Leave it unset locally and in Docker.

Vite inlines `import.meta.env` **at build time** — changing it in the Vercel dashboard
without redeploying changes nothing.

### 3.2 The image installs the `llm` extra

`apps/api/Dockerfile` now runs `pip install ".[llm]"`. Without it, Tier 4 was dead in the
container even with `ANTHROPIC_API_KEY` set — and dead *quietly*: `tiers/llm.py` catches
the `ImportError`, logs one INFO line, and returns `None`, so the pipeline just stopped
at Tier 2 and every posting looked a little worse than it should have.

That silence is why `tests/test_packaging.py` now parses the Dockerfile and asserts the
extras it installs exist in `pyproject.toml`, that `llm` is among them, and that
`browser` is not — Playwright's download will not fit a 512 MB instance.

### 3.3 The extension asks for one host, at runtime

The problem is real: the extension's `fetch` to the API is an ordinary cross-origin
request from `chrome-extension://<id>`, and an unpacked install gets a different id on
every machine, so those ids can't be listed in `CORS_ORIGINS`.

Hardcoding `host_permissions` in the manifest would mean editing a committed file per
deployment, and each person here may point at a different host. Instead the manifest
declares `optional_host_permissions`, and the popup requests the one origin the user
typed when they press **Connect** — the user gesture Chrome requires:

```json
"optional_host_permissions": ["https://*/*", "http://*/*"]
```

Same exemption, granted for one host, no per-deployment manifest edit. The service worker
can't request permission (no gesture), so `savePosting` checks first and says "open
Settings and press Connect" instead of failing as an opaque CORS error. `test/run.mjs`
asserts that installing the extension grants **nothing** — neither the API host nor any
job site.

### 3.4 A sweep endpoint for an external scheduler

`POST /api/v1/reminders/sweep`, guarded by the `x-sweep-secret` header against
`SWEEP_SECRET`. Both "no secret configured" and "wrong secret" return **404**, so an
unconfigured deployment doesn't advertise the route and a prober learns nothing; the
comparison is constant-time. It's `include_in_schema=False`, so it stays out of `/docs`.

The sweep itself moved into `src/services/reminders.py::sweep`, which the arq cron in
`apps/worker/worker.py` now calls too — one definition, so the Redis and no-Redis
deployments can't drift.

`.github/workflows/reminders.yml` calls it daily at 13:00 UTC and on demand
(`workflow_dispatch`). It needs two repository secrets, `API_URL` and `SWEEP_SECRET`; with
either missing the job exits successfully and says so, rather than failing every morning.
It pings `/healthz` first so a cold start doesn't read as a failed sweep.

Remember this only restores the **unprompted** daily push. `GET /reminders` computes on
demand, so the needs-attention bar works with none of this configured.

---

## 4. Deploy

### 4.1 Neon

Create one project, one branch. Copy the **pooled** connection string and rewrite the
scheme for SQLAlchemy: `postgresql+psycopg://…?sslmode=require`. `psycopg[binary]` is
already a hard dependency, so nothing to install.

`core/db.py` sets `pool_pre_ping=True` for non-SQLite engines, which is exactly what you
need against a database that scales to zero — the first query after idle pays ~0.5 s and
a stale pooled connection gets recycled instead of erroring.

### 4.2 The API

`apps/api/Dockerfile` is already deployable: it reads `$PORT`, runs
`alembic upgrade head && uvicorn src.main:app` on boot, and starts **one** uvicorn worker.
Leave it at one — with no Redis, the SSE hub and the thread pool live in process memory, so
a second worker would mean a browser connected to worker A never sees an ingest running on
worker B.

The blueprint is committed at **`render.yaml`** in the repo root: point Render at the
repo and it reads that file. Every secret is `sync: false`, so Render prompts for it
rather than the repo carrying it; `JWT_SECRET` is `generateValue: true`, so the
`dev-secret-change-me` default can't reach production by inattention. Edit
`CORS_ORIGINS` to your real Vercel URL before the first deploy.

Blueprint field names have drifted across Render versions — if it refuses the file, check
the current spec rather than assuming the file is wrong.

Every setting, with the real defaults from `core/config.py`:

| Variable | Set it to | Note |
|---|---|---|
| `DATABASE_URL` | Neon pooled URL | Default is a SQLite file — on a container with no disk, that's a database that vanishes on every deploy |
| `REDIS_URL` | **unset** | Setting it without running a worker means jobs enqueue and nothing consumes them |
| `JWT_SECRET` | 48 random bytes | Default `dev-secret-change-me` signs every session |
| `CORS_ORIGINS` | `["https://<your-app>.vercel.app"]` | Parsed as a **JSON list** by pydantic-settings. Add the custom domain when you add one |
| `ANTHROPIC_API_KEY` | optional | Tier 4 only. `llm_monthly_call_cap` already caps it at 500 calls/month |
| `INGEST_BROWSER_ENABLED` | leave unset | Read directly by `tiers/browser.py`; anything but `1`/`true`/`yes` is off |
| `REMINDER_EMAIL_ENABLED` | `false` | `notify.py` has no provider — a `true` here changes nothing but the log |
| `REMINDER_SWEEP_HOUR_UTC` | `13` | 8am Chicago in summer, 7am in winter. Read by the **worker's** arq cron only; the GitHub Actions schedule has its own time |
| `SWEEP_SECRET` | 32 random bytes, or unset | Must match the `SWEEP_SECRET` repository secret. Unset means `POST /reminders/sweep` 404s — the safe default |
| `ENVIRONMENT` | `production` | Surfaced by `/healthz` |

Turn off preview environments. Each one is another process against the same database, and
on the free plan they eat the 750 hours.

### 4.3 The web app on Vercel

Set the project's root directory to `apps/web`; the rest is in the committed
**`apps/web/vercel.json`** — Vite preset, `npm run build`, `dist`, an SPA rewrite, and
cache headers that keep `sw.js` and the web manifest revalidating while content-hashed
assets stay immutable. A stale service worker pins the old shell indefinitely, which is
the kind of bug you debug for an hour and fix in one header.

Three things about that file, since it carries no comments of its own — Vercel validates
it with `additionalProperties: false` at every level, so a `"//"` key is a hard error
("should NOT have additional property") rather than an ignored annotation:

- **The SPA rewrite is a bare catch-all** (`/(.*)` → `/index.html`), which is Vercel's
  own documented pattern. It doesn't shadow `/sw.js`, `/manifest.webmanifest` or the
  hashed assets, because static files are matched *before* rewrites; it only catches
  paths with no file behind them.
- **There is deliberately no rewrite to the API.** Proxying `/api` through Vercel is the
  tempting no-code-change option, but `/api/v1/events` is a long-lived SSE stream and a
  proxy in the path is exactly what breaks those. Going cross-origin via
  `VITE_API_ORIGIN` puts nothing between the browser and the stream.
- **`sw.js` must not be cached.** A stale service worker keeps serving the old shell
  forever, so it's `no-cache, must-revalidate` while `/assets/*` is `immutable`.

One environment variable: `VITE_API_ORIGIN=https://<your-api-host>` (no trailing slash).
Then add that Vercel URL to `CORS_ORIGINS` on the API and restart it — do both in the same
sitting, because a CORS mismatch looks exactly like a dead API from the browser console.

This path is verified, not assumed: with the SPA built for one origin and served from
another, sign-in, the board, `/reminders`, and the SSE stream all connect with no CORS
errors in the console.

**Web Analytics** is wired up — `<Analytics />` from `@vercel/analytics/react` is mounted
in `src/main.tsx`. Note `/react`, not `/next`: this is a Vite SPA, and the `/next` entry
point imports `next/navigation`, which would fail the build. It still needs turning on
once in the dashboard (Project → **Analytics** → Enable); until then the script 404s
harmlessly and the app is unaffected. `public/sw.js` skips `/_vercel/` so the service
worker can't pin a stale copy of the script.

**Don't route the API through a Vercel rewrite.** It's the tempting no-code-change option,
but `/api/v1/events` is a long-lived SSE stream and a proxy in the path is precisely what
breaks those — the API already sets `X-Accel-Buffering: no` for this reason, and that
header is a request to nginx that Vercel's edge is under no obligation to honour. Going
cross-origin puts no proxy between the browser and the stream at all.

`apps/web/Dockerfile` and `nginx.conf` stay in the repo unused by this deployment. They're
what makes `docker compose up` work, and what you'd go back to on a single box.

### 4.4 Accounts, and the extension

`POST /api/v1/auth/register` is open and there's no invite flow. The schema is multi-tenant
(README §11 Q2) and uniqueness is `(user_id, canonical_url)`, so four accounts is four
independent boards — nothing to configure. If you'd rather not leave registration open to
the internet, the smallest gate is a signup-code check in `routers/auth.py::register`;
four users is not worth an OAuth provider.

Each person loads `apps/extension` unpacked, pastes their token from the account menu, and
sets the tracker URL to the **API** host, not the Vercel one — `background.js` posts
directly to `{apiBase}/api/v1/ingest/from-dom`. Pressing **Connect** raises a Chrome
permission prompt for that one host (§3.3); accepting it is what makes saving work, and
the popup refuses to store a connection without it.

### 4.5 Keepalive, if you're on the free tier

A free uptime monitor pinging `/healthz` every 10 minutes keeps the instance warm, and 24/7
at that interval still fits inside 750 hours/month.

Ping `/healthz`, not `/readyz`. `/readyz` opens a database connection, so pinging it every
ten minutes keeps Neon's compute awake around the clock and burns the 100 CU-hours you're
trying to conserve. `/healthz` touches nothing.

---

## 5. What it costs, and what makes it stop being free

| | Monthly |
|---|---|
| Vercel Hobby + Render free + Neon free | $0 |
| Anthropic API (Tier 4 only) | ~$0–2 |
| Same with Fly instead of Render free | ~$2–6 |

The one line item that can surprise you is Tier 4, which fires whenever the cheap tiers
leave holes — a bad week of LinkedIn pastes is a lot of fallbacks. `ingest_jobs` records
`tier_succeeded` per attempt, so the answer is one query away, and README §11's alert
threshold (Tier-4 rate over 25%) is a cost signal as much as a quality one.

Migration triggers, in the order you'll hit them:

| Signal | Move |
|---|---|
| Cold starts are annoying anyone | Render free → Fly `shared-cpu-1x` (~$2–4/mo) |
| Approaching 0.5 GB in Neon | `description_raw` + `description_html` per card is the driver. Neon Launch is usage-based with no monthly minimum |
| Four people pasting batches at once | Upstash Redis (free tier) + deploy `apps/worker` — both already exist in the code, it's two env vars and a second service |
| A posting genuinely needs Tier 3 | Playwright needs ≥1 GB. Its own low-concurrency service, per README §11 — never in the API instance |

---

## 6. Phase 4 and Phase 5 from here

You asked to not paint yourself into a corner. You aren't, and the reason is that every
backend seam in this repo is already an environment variable.

**Phase 4 (skill-gap, resume-versus-outcome, interview prep)** is more LLM calls against
the same database. No infrastructure change. Watch `llm_monthly_call_cap` — 500/month is
sized for extraction fallback, not for a feature users invoke on purpose.

**Phase 5 (Gmail)** is where this deployment needs three specific things:

- **A stable HTTPS origin for the OAuth redirect URI.** Buy the domain before you register
  the Google client, or you'll re-verify against a new one. Point it at the API host, and
  put the SPA on `app.` or the apex.
- **An always-on endpoint for the Pub/Sub push.** Pub/Sub retries, so a sleeping free
  instance is survivable rather than fatal — but this is the honest moment to be paying
  for the always-on machine.
- **Encryption at rest for refresh tokens.** README §9.5 specifies Cloud KMS envelope
  encryption, which assumes GCP. Off GCP, a key in the environment plus `cryptography`
  meets the same requirement at this scale; what matters is that tokens are never logged
  and that disconnect purges them.
- Renewing the Gmail watch is a daily job, which is when §3.4's cron endpoint stops being
  optional — or when you deploy `apps/worker` and let arq own both schedules.

`infra/main.tf` remains the path if Phase 5 makes GCP worth it: Cloud Run for the API and
worker, Cloud SQL, Memorystore, with the Pub/Sub topic deliberately absent until then. It
has never been applied. Treat it as a design artifact, not a deploy button.

The whole migration story here is: change `DATABASE_URL`, set `REDIS_URL`, run the worker
image that's already in the repo. That's why starting free costs you nothing later.

---

## 7. The alternative: one box

`docker-compose.yml` already describes the full system — Postgres, Redis, API, worker, and
the nginx-served SPA on one origin. A single small VM (Hetzner's cheapest tier, or an
Oracle Cloud Always Free ARM instance at $0) runs `docker compose up -d` and gives you the
real architecture, arq cron and Redis fan-out included, with **none of the four code
changes in section 3** — because on one origin, the hardcoded `/api/v1` is correct.

The trade is TLS renewal, OS patching, backups, and the 3 a.m. reboot. It's genuinely
cheaper and genuinely more work. Mentioned second because at four users the split
deployment's zero operational surface is worth more than the architectural fidelity — not
because it's wrong.