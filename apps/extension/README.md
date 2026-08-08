# Browser extension

Saves a posting from the page you're already looking at, which is how the tracker
handles LinkedIn, Indeed, Glassdoor and ZipRecruiter — sites whose terms prohibit
automated scraping and whose bot detection would block it anyway (README §4.1).

Nothing is scraped server-side: your browser has already rendered and authenticated the
page, the extension reads that DOM, and the tracker's normal tier stack runs against it.

## Install (unpacked)

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick this
   directory. Works in Chrome, Edge, Brave, and any Chromium build.
2. Open the tracker, sign in, and use the account menu → **Copy extension token**.
3. Click the extension. The **Tracker API URL** is already filled in with the deployed
   API — leave it alone unless you're running your own. Paste the token, press
   **Connect**, and accept the permission prompt Chrome raises.

The URL is the **API**, not the site you sign in to. They're different hosts in this
deployment (the app is on Vercel, the API on Render), and the extension posts straight to
`{API}/api/v1/ingest/from-dom`.

Then, on any job posting: click the extension (or press `Ctrl/Cmd+Shift+S`) and choose
**Save** or **Save & mark applied**. A ✓ badge means the card is on your board.

### The first save of the day is slow

The API runs on a free instance that sleeps after 15 minutes idle and takes 30–60 seconds
to wake. A `…` badge means the request is in flight, and the popup says so rather than
sitting on "Saving…" in silence. Requests give up after 90 seconds.

Nothing is lost if it does time out — retry once the instance is awake. `docs/DEPLOYMENT.md`
covers the keepalive ping that avoids this, and the paid tier that removes it.

## Permissions, and why they're this small

| Permission | Why |
|---|---|
| `activeTab` | Read the page **only** when you click the extension. There is no standing access to any site. |
| `scripting` | Inject the one-shot extractor into that tab. |
| `storage` | Remember your tracker URL and token (`chrome.storage.sync`). |
| *(optional)* one host | **Your tracker's API, and nothing else.** Granted when you press **Connect**, for exactly the URL you typed. |

No content scripts and no host permission for any job site, so the extension is inert
until you act on a tab.

The one host permission is not optional in practice, and it's worth knowing why it
exists: the extension's own requests to your API are ordinary cross-origin requests from
`chrome-extension://<id>`, and an unpacked install gets a **different id on every
machine** — so the API can't list them in `CORS_ORIGINS`. A granted host permission
exempts those requests from CORS entirely. Chrome shows the prompt on **Connect** because
that's your gesture; decline it and saving can't work, which the popup says rather than
failing later as an opaque network error.

## Pointing it somewhere else

`src/config.js` holds the default:

```js
export const DEFAULTS = { apiBase: "https://job-tracker-api-a8gp.onrender.com", token: "" };
```

For a local API, put `http://localhost:8000` in the popup's Settings and press Connect
again — the permission is granted per origin, so switching hosts needs a new prompt. If
you redeploy the API to a different host, change the default here so nobody has to retype
it; there's no build step, just reload the extension at `chrome://extensions`.

## What gets sent

`POST /api/v1/ingest/from-dom` with the page's cleaned HTML (scripts, styles, SVG,
video and iframes removed), the URL, the visible text, and whatever the site-specific
selectors could read — title, company, location. Those last three are **hints**: the
server runs its normal tiers first and only fills gaps with them, so a selector that
rots degrades to "no hint" rather than to a wrong record.

## Tests

```bash
npm install --no-save playwright
node test/run.mjs                                  # needs a seeded API on :8000
API_BASE=https://job-tracker-api-a8gp.onrender.com \
  TRACKER_EMAIL=you@example.com TRACKER_PASSWORD=… node test/run.mjs
```

Loads the unpacked extension into Chromium, runs the extractor against a
LinkedIn-shaped fixture served at the real hostname, and asserts the tracker builds the
record. It also asserts that **no** host is granted at install time — if that ever starts
out true, the manifest has quietly widened — that the default API URL is https with no
trailing slash, and that an unreachable host produces a message a person can act on
rather than Chrome's "Failed to fetch". Not in CI: it needs a browser and a live API. Run
it when the selectors, the permission model, or the from-dom contract change.

## Icons

`python make_icons.py` regenerates them. They're drawn in code so the repo carries no
binary asset nobody can reproduce.
