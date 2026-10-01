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
**Save** or **Save & mark applied**. A ✓ badge means the card is on your board. If the
job was already tracked, the popup says **Already on your board** and names the card, so
a save that matched the wrong card can't pass for a success.

## Autofill an application (fill only — you submit)

On an application form, click the extension → **Autofill application…**. A side panel
opens next to the page:

1. **Pick your resume** (PDF or Word) and press **Read resume**. The tracker's AI reads
   it into your name, contact details, links, education and experience.
2. **Fill this page.** The first time on a site, Chrome asks to allow that one site.
   Fields are filled in, outlined **green**; questions left for you are outlined
   **amber** and listed in the panel with the reason.
3. **Read the whole form, answer the amber ones, and press Submit yourself.** The
   extension never submits, clicks a button, or presses Enter.

On a multi-page form, press **Fill again** on each page; the resume stays loaded until
you close the panel. If the panel says to click the toolbar button first, do that once
on the page: it can only see a tab's address after a click, or on a site you've allowed.

**Never answered for you:** work authorization, visa sponsorship, citizenship, gender,
race/ethnicity, veteran or disability status, salary expectations, criminal history, and
any consent, signature or attestation. These are matched by rule before any AI sees the
form. Essay questions ("Why do you want to work here?") are left for you too.

**Not handled yet:** custom dropdown widgets that aren't real `<select>`s (Workday,
react-select), CAPTCHAs, and forms inside frames you decline to allow. They end up in
"needs you".

**Your resume** is held in the panel's memory only. It's sent to your tracker, and on to
its AI, to read it, and never stored by the extension or the tracker. Closing the panel
forgets it.

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
| `sidePanel` | Show the autofill panel. Grants no access to any site. |
| *(optional)* one host | **Your tracker's API, and nothing else.** Granted when you press **Connect**, for exactly the URL you typed. |
| *(optional)* each form's host | **Only if you use autofill**, for exactly the site whose form you're filling, granted when you press **Fill this page** (and, for a form embedded from another site, by its own **Allow** button). |

No content scripts and no host permission for any job site at install, so the extension
is inert until you act on a tab.

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

Autofill sends, to `POST /api/v1/autofill/profile`, the resume file; and to
`POST /api/v1/autofill/map`, the page URL, the parsed profile, and a description of each
empty form field (its label, name, type, whether it's required, and its options). Field
values already on the page are not sent.

## Tests

```bash
npm install --no-save playwright
node test/spa.mjs                                  # offline: the job on screen is the job saved
node test/autofill.mjs                             # offline: fills a form, never submits
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

`spa.mjs` reproduces the "saved the first job twice" bug: a page whose `<head>` still
describes the job it first loaded, a pushState to a second job, and a Google-style apply
form whose canonical link drops the `jobId`. `autofill.mjs` runs the two injected autofill
functions against a Greenhouse-shaped form with a React-style value tracker and a submit
trap. Both need only a browser.

## Icons

`python make_icons.py` regenerates them. They're drawn in code so the repo carries no
binary asset nobody can reproduce.
