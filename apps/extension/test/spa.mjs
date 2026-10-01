/**
 * The "saved the first job twice" bug, offline: no API, just the extractor against
 * pages whose <head> describes a different job than the one on screen.
 *
 *   cd apps/extension && npm install --no-save playwright && node test/spa.mjs
 *
 * Google Careers, LinkedIn and Indeed search are single-page apps: clicking another
 * job swaps the content with pushState. When the app doesn't also update <head>, the
 * canonical link, og: tags and JSON-LD still name the first job — and the extractor
 * used to send that canonical URL, which the server deduplicated onto the first card.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const extractorSource = readFileSync(join(here, "..", "src", "extract.js"), "utf8").replace(
  "export function",
  "function",
);
const collect = (page) =>
  page.evaluate(`(() => { ${extractorSource}; return collectPosting(); })()`);

const browser = await chromium.launch({
  executablePath: "/opt/pw-browsers/chromium",
  args: ["--no-sandbox"],
});

try {
  const page = await browser.newPage();
  const fixture = readFileSync(join(here, "fixtures", "spa-board.html"), "utf8");
  // Served at the real host: the extractor branches on hostname.
  await page.route("https://www.google.com/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: fixture }),
  );
  await page.route("https://www.linkedin.com/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>pane</body></html>" }),
  );

  // 1. On the page the server rendered, the canonical link is right and is used —
  //    stripping only the search query that led here.
  const base = "https://www.google.com/about/careers/applications/jobs/results";
  await page.goto(`${base}/111-staff-software-engineer?q=engineer`);
  const first = await collect(page);
  assert.equal(first.url, `${base}/111-staff-software-engineer`);
  assert.equal(first.hints.title, "Staff Software Engineer", "title comes from the tab title");
  assert.equal(first.hints.company, "Google");
  assert.ok(first.html.includes("og:title"), "a trustworthy head is sent intact");

  // 2. Click the second job: the app pushes a new URL and swaps the content, but the
  //    head still names job one. The save must be job two's.
  await page.evaluate(() => {
    history.pushState({}, "", "/about/careers/applications/jobs/results/222-data-analyst?q=engineer");
    document.title = "Data Analyst — Google Careers";
    document.querySelector("#detail").innerHTML =
      "<h2>Data Analyst</h2><p>Build the dashboards finance runs on.</p>";
  });
  const second = await collect(page);
  assert.equal(second.url, `${base}/222-data-analyst?q=engineer`, "not the stale canonical");
  assert.equal(second.hints.title, "Data Analyst");
  assert.ok(second.text.includes("dashboards finance"), "the visible job is the one sent");
  assert.ok(!second.html.includes("Staff Software Engineer\""), "stale JSON-LD is dropped");
  assert.ok(!second.html.includes("og:title"), "stale og: tags are dropped");
  assert.ok(!second.html.includes('rel="canonical"'), "the stale canonical is dropped");

  // 3. An apply form identifies the job only in its query string. A canonical link
  //    that drops it would name every job at once.
  await page.evaluate(() => {
    history.pushState({}, "", "/about/careers/applications/apply?jobId=AbC123&title=Data+Analyst&loc=US");
    document.querySelector("link[rel=canonical]").href =
      "https://www.google.com/about/careers/applications/apply";
    document.title = "Apply — Google Careers";
  });
  const apply = await collect(page);
  assert.equal(apply.url, "https://www.google.com/about/careers/applications/apply?jobId=AbC123&title=Data+Analyst&loc=US");
  assert.equal(apply.hints.title, "Data Analyst", "the apply form's title rides in its URL");

  // 4. LinkedIn's search pane names the open job in `currentJobId`: save that job's page.
  await page.goto("https://www.linkedin.com/jobs/search/?currentJobId=4001&keywords=intern");
  assert.equal((await collect(page)).url, "https://www.linkedin.com/jobs/view/4001");

  console.log("✓ the job on screen is the job that gets saved");
} finally {
  await browser.close();
}
