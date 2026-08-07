/**
 * Verifies the extension against a running tracker, end to end:
 * loads the unpacked extension into Chromium, runs the injected extractor over a
 * LinkedIn-shaped fixture, and posts the result to /ingest/from-dom.
 *
 *   cd apps/extension && npm install --no-save playwright && node test/run.mjs
 *
 * Not in CI: it needs a browser and a live API. Run it when the selectors or the
 * from-dom contract change — those are the parts that rot.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

import { DEFAULTS, apiFetch, normalizeBase, originPattern } from "../src/config.js";

// The host pattern decides what the extension may reach, so it gets checked before a
// browser is involved. A trailing slash or a path must not widen or break it.
assert.equal(originPattern("https://api.example.com"), "https://api.example.com/*");
assert.equal(originPattern("https://api.example.com/"), "https://api.example.com/*");
assert.equal(originPattern("http://localhost:8000/api/v1"), "http://localhost:8000/*");
assert.equal(normalizeBase("  https://api.example.com//  "), "https://api.example.com");

// The default must be the deployed API and must be a valid permission target — a
// trailing slash here would silently produce a pattern that grants nothing.
assert.match(DEFAULTS.apiBase, /^https:\/\/[^/]+$/, "default apiBase: https, no trailing slash");
assert.equal(originPattern(DEFAULTS.apiBase), `${DEFAULTS.apiBase}/*`);

// An unreachable host must produce something a person can act on. Chrome reports a
// missing host permission, a DNS failure and being offline identically as
// "Failed to fetch", so leaking that string through would be useless.
await assert.rejects(
  () => apiFetch("http://127.0.0.1:9/nope"),
  (error) => !/failed to fetch/i.test(error.message) && /Couldn't reach the tracker/.test(error.message),
);

const here = dirname(fileURLToPath(import.meta.url));
// A fresh posting id per run: re-saving a tracked URL correctly focuses the existing
// card instead of re-extracting it, which would make this test order-dependent.
const POSTING_ID = Date.now();
const extensionPath = join(here, "..");
const API = process.env.API_BASE ?? "http://127.0.0.1:8000";
const EMAIL = process.env.TRACKER_EMAIL ?? "demo@example.com";
const PASSWORD = process.env.TRACKER_PASSWORD ?? "demo-password-123";

// The extractor is written as a module for the service worker, but Chrome serializes
// it into the page — so it has to stand alone. Stripping the export here is exactly
// the constraint the real injection imposes, and proves the function keeps no closure.
const extractorSource = readFileSync(join(here, "..", "src", "extract.js"), "utf8").replace(
  "export function",
  "function",
);

const token = await (async () => {
  const response = await fetch(`${API}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  assert.equal(response.status, 200, "could not sign in — is the API seeded and running?");
  return (await response.json()).access_token;
})();

const context = await chromium.launchPersistentContext("", {
  executablePath: "/opt/pw-browsers/chromium",
  args: [
    "--no-sandbox",
    `--disable-extensions-except=${extensionPath}`,
    `--load-extension=${extensionPath}`,
  ],
});

try {
  const page = await context.newPage();

  // Serve the fixture *at the real URL*: the extractor branches on hostname, so a
  // file:// page would silently exercise the generic path instead of LinkedIn's.
  const fixture = readFileSync(join(here, "fixtures", "linkedin.html"), "utf8");
  await page.route("https://www.linkedin.com/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: fixture }),
  );
  await page.goto(`https://www.linkedin.com/jobs/view/${POSTING_ID}?trk=public_jobs`);

  const captured = await page.evaluate(`(() => { ${extractorSource}; return collectPosting(); })()`);

  // 1. The extractor reads what the page renders.
  assert.equal(captured.hints.title, "Software Engineer Intern");
  assert.equal(captured.hints.company, "Ramp");
  assert.equal(captured.hints.location, "New York, NY");
  assert.equal(captured.url, `https://www.linkedin.com/jobs/view/${POSTING_ID}?trk=public_jobs`);
  assert.ok(captured.text.includes("ledger service"), "visible text should carry the posting");

  // 2. It strips what the tracker has no use for.
  assert.ok(!captured.html.includes("__INITIAL_STATE__"), "scripts should be stripped");
  assert.ok(!captured.html.includes("<style"), "styles should be stripped");
  assert.ok(captured.html.includes("ledger service"), "the posting itself must survive");

  // 3. The tracker accepts it and builds a real record.
  const response = await fetch(`${API}/api/v1/ingest/from-dom`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      url: captured.url,
      html: captured.html,
      hints: captured.hints,
      fallback_text: captured.text,
    }),
  });
  assert.equal(response.status, 200);

  const application = await response.json();
  assert.equal(application.company, "Ramp");
  assert.equal(application.title, "Software Engineer Intern");
  assert.equal(application.location, "New York, NY");
  assert.ok(application.description.includes("ledger service"));
  // Tracking params are stripped, so re-saving the same posting finds this card.
  assert.equal(application.canonical_url, `https://www.linkedin.com/jobs/view/${POSTING_ID}`);

  // 4. The extension is actually loaded (its service worker registered).
  const [worker] = context.serviceWorkers();
  assert.ok(worker, "extension service worker should be running");

  // 5. The API host is not granted by installing — it is granted by pressing Connect.
  // If this ever starts out true, the manifest has quietly widened.
  const origin = new URL(API).origin;
  const granted = await worker.evaluate(
    (pattern) => chrome.permissions.contains({ origins: [pattern] }),
    `${origin}/*`,
  );
  assert.equal(granted, false, "the tracker host must be an opt-in permission, not a default");

  // And nothing else is granted either — no job site is readable without a click.
  const anySite = await worker.evaluate(() =>
    chrome.permissions.contains({ origins: ["https://www.linkedin.com/*"] }),
  );
  assert.equal(anySite, false, "no host permission for job sites — activeTab is the whole point");

  console.log("✓ extension captured:", application.company, "—", application.title);
  console.log("  canonical:", application.canonical_url);
  console.log("  tier:", application.extraction_meta.tier);
} finally {
  await context.close();
}
