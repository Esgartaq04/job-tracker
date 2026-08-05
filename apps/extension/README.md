# Browser extension

Saves a posting from the page you're already looking at, which is how the tracker
handles LinkedIn, Indeed, Glassdoor and ZipRecruiter — sites whose terms prohibit
automated scraping and whose bot detection would block it anyway (README §4.1).

Nothing is scraped server-side: your browser has already rendered and authenticated the
page, the extension reads that DOM, and the tracker's normal tier stack runs against it.

## Install (unpacked)

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick this
   directory. Works in Chrome, Edge, Brave, and any Chromium build.
2. In the tracker, open the account menu → **Copy extension token**.
3. Click the extension, paste the token and your tracker URL, press **Connect**.

Then, on any job posting: click the extension (or press `Ctrl/Cmd+Shift+S`) and choose
**Save** or **Save & mark applied**. A ✓ badge means the card is on your board.

## Permissions, and why they're this small

| Permission | Why |
|---|---|
| `activeTab` | Read the page **only** when you click the extension. There is no standing access to any site. |
| `scripting` | Inject the one-shot extractor into that tab. |
| `storage` | Remember your tracker URL and token (`chrome.storage.sync`). |

There are no `host_permissions` and no content scripts, so the extension is inert until
you act on a tab.

## What gets sent

`POST /api/v1/ingest/from-dom` with the page's cleaned HTML (scripts, styles, SVG,
video and iframes removed), the URL, the visible text, and whatever the site-specific
selectors could read — title, company, location. Those last three are **hints**: the
server runs its normal tiers first and only fills gaps with them, so a selector that
rots degrades to "no hint" rather than to a wrong record.

## Tests

```bash
npm install --no-save playwright
node test/run.mjs          # needs a seeded API on :8000
```

Loads the unpacked extension into Chromium, runs the extractor against a
LinkedIn-shaped fixture served at the real hostname, and asserts the tracker builds the
record. Not in CI — it needs a browser and a live API; run it when the selectors or the
from-dom contract change.

## Icons

`python make_icons.py` regenerates them. They're drawn in code so the repo carries no
binary asset nobody can reproduce.
