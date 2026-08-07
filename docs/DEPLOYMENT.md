# Deploying

Written against the repo at `main`, not against README §3. The design document specifies
Cloud Run + Cloud SQL + Memorystore, and `infra/main.tf` sketches it; that is a production
footprint this workload does not have. What follows deploys **the code that exists today**
for four people, at roughly zero, without foreclosing Phase 4 or Phase 5.

Nothing is deployed yet, so there is no migration to plan around — only a first choice.

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

**The web app assumes the API is same-origin.** `apps/web/src/api/client.ts` hardcodes
`const API_BASE = "/api/v1"`; in dev the Vite proxy provides it, in Docker `nginx.conf`
provides it. Vercel provides neither. Section 3 has the three-line fix.

**Auth makes cross-origin easy.** The token is a bearer JWT in `localStorage`, and
`/events` accepts `?access_token=` because `EventSource` can't set headers. No cookies
means no `SameSite` problem, no subdomain requirement — just `CORS_ORIGINS`.

**Redis is optional, and losing it costs exactly one thing.** Without it: ingestion runs
in-process, SSE runs in-memory, the fetch cache is per-process. All fine at one instance.
What you actually lose is the **daily reminder sweep**, which only exists as an arq cron in
`apps/worker/worker.py`. `GET /reminders` computes on demand, so the needs-attention bar
and the whole reminders feature still work — you just don't get an unprompted daily push.
Section 3.4 adds that back for free if you want it.

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

## 3. Changes to make before deploying

Four diffs. The first two are required; the third is required if anyone uses the
extension; the fourth is optional.

### 3.1 Make the API origin configurable (required)

Two files hardcode the path. `client.ts`:

```diff
-const API_BASE = "/api/v1";
+// Same-origin in dev (Vite proxy) and in Docker (nginx). Set VITE_API_ORIGIN when the
+// SPA is served from a different host than the API — e.g. Vercel in front of Render.
+const API_ORIGIN = import.meta.env.VITE_API_ORIGIN ?? "";
+const API_BASE = `${API_ORIGIN}/api/v1`;
```

and `hooks.ts:113`, where CSV import builds its own multipart request outside `client.ts`:

```diff
-      const response = await fetch("/api/v1/applications/import", {
+      const response = await fetch(`${API_BASE}/applications/import`, {
```

`API_BASE` is already exported from `client.ts`; import it there. Leave `VITE_API_ORIGIN`
unset locally and in `docker compose`, and both keep working unchanged.

Vite inlines `import.meta.env` **at build time**. Changing it in the Vercel dashboard
without redeploying changes nothing.

### 3.2 Install the `llm` extra in the API image (required if you want Tier 4)

`apps/api/pyproject.toml` puts `anthropic` behind an optional extra, and
`apps/api/Dockerfile` runs `pip install .`. So `tiers/llm.py` raises on
`import anthropic` and Tier 4 is dead in the container **even with a key set** — the
pipeline silently stops at Tier 2.

```diff
-RUN pip install --upgrade pip && pip install .
+RUN pip install --upgrade pip && pip install ".[llm]"
```

Do **not** add `[browser]`. Playwright's download is hundreds of megabytes and will not
fit a 512 MB instance.

### 3.3 Give the extension permission to reach the API (required for the extension)

`apps/extension/manifest.json` has no `host_permissions`, so its `fetch` to
`/api/v1/ingest/from-dom` is an ordinary cross-origin request subject to CORS from
`chrome-extension://<id>` — and an unpacked install gets a **different id on every
machine**, so you can't just list them in `CORS_ORIGINS`.

Cheapest fix, one line, and it doesn't widen access to any job site:

```diff
   "permissions": ["activeTab", "scripting", "storage"],
+  "host_permissions": ["https://<your-api-host>/*"],
```

A granted host permission exempts the extension's own requests from CORS. The README's
permissions table should gain a row saying the host is the tracker's API and nothing else.

### 3.4 Optional: a sweep endpoint so an external cron can do the worker's job

Without Redis, `sweep_reminders` never runs. If you want the daily push and the (currently
logging-only) digest, add a route that runs the same function behind a shared secret:

```python
# routers/reminders.py
@router.post("/sweep", include_in_schema=False)
def sweep(request: Request, db: DbSession) -> dict:
    if request.headers.get("x-sweep-secret") != os.environ["SWEEP_SECRET"]:
        raise HTTPException(status_code=404)
    # the body of worker.py::_sweep, unchanged
```

Then point a free scheduler at it once a day — GitHub Actions on a `schedule:` trigger is
free on a public repo and leaves a log of whether it ran. When Redis arrives later, the arq
cron takes over and this route becomes redundant rather than wrong.

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

A Render blueprint, roughly (field names have drifted across Render versions — check the
current blueprint spec):

```yaml
# render.yaml
services:
  - type: web
    name: job-tracker-api
    runtime: docker
    plan: free
    rootDir: apps/api
    dockerfilePath: ./Dockerfile
    healthCheckPath: /healthz
    envVars:
      - key: DATABASE_URL      # Neon pooled URL
        sync: false
      - key: JWT_SECRET
        generateValue: true
      - key: CORS_ORIGINS
        value: '["https://<your-app>.vercel.app"]'
      - key: ENVIRONMENT
        value: production
      - key: ANTHROPIC_API_KEY
        sync: false
```

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
| `REMINDER_SWEEP_HOUR_UTC` | `13` | 8am Chicago in summer, 7am in winter. Only matters once §3.4 or a worker exists |
| `ENVIRONMENT` | `production` | Surfaced by `/healthz` |

Turn off preview environments. Each one is another process against the same database, and
on the free plan they eat the 750 hours.

### 4.3 The web app on Vercel

Root directory `apps/web`, framework preset Vite, build `npm run build`, output `dist`.
One environment variable: `VITE_API_ORIGIN=https://<your-api-host>` (no trailing slash).
Then add that Vercel URL to `CORS_ORIGINS` on the API and restart it — do both in the same
sitting, because a CORS mismatch looks exactly like a dead API from the browser console.

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
directly to `{apiBase}/api/v1/ingest/from-dom`.

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