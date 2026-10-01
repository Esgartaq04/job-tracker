/**
 * The page half of autofill, offline: no API, no extension — the two injected functions
 * against a Greenhouse-shaped form.
 *
 *   cd apps/extension && npm install --no-save playwright && node test/autofill.mjs
 *
 * What matters most is checked hardest: that values reach a React-controlled input the
 * way typing would, that the resume lands in the hidden file input, and that nothing —
 * ever — submits the form.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "..", "src", "autofill.js"), "utf8").replaceAll(
  "export function",
  "function",
);

const browser = await chromium.launch({
  executablePath: "/opt/pw-browsers/chromium",
  args: ["--no-sandbox"],
});

try {
  const page = await browser.newPage();
  const fixture = readFileSync(join(here, "fixtures", "application-form.html"), "utf8");
  await page.route("https://boards.greenhouse.io/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: fixture }),
  );
  await page.goto("https://boards.greenhouse.io/ramp/jobs/123");

  // 1. Collect: the standalone function, exactly as Chrome would serialize it.
  const collected = await page.evaluate(`(() => { ${source}; return collectFormFields(); })()`);
  const byLabel = Object.fromEntries(collected.fields.map((field) => [field.label, field]));

  assert.deepEqual(
    collected.fields.map((field) => field.label),
    [
      "First Name",
      "Last Name",
      "Email",
      "LinkedIn Profile",
      "Resume/CV",
      "Country",
      "Are you legally authorized to work in the United States?",
      "Why do you want to work at Ramp?",
      "Send me updates about future roles",
    ],
    "pre-filled, hidden, and CAPTCHA fields are left out; labels read like the page",
  );
  assert.equal(byLabel["First Name"].required, true);
  assert.equal(byLabel["Resume/CV"].kind, "file", "a hidden file input still counts");
  assert.equal(byLabel["Resume/CV"].file_role, "resume");
  assert.deepEqual(byLabel.Country.options, ["Canada", "United States"]);
  const authorized = byLabel["Are you legally authorized to work in the United States?"];
  assert.equal(authorized.kind, "radio", "a radio group is one question");
  assert.deepEqual(authorized.options, ["Yes", "No"]);
  assert.equal(byLabel["Why do you want to work at Ramp?"].kind, "textarea");

  // 2. Fill with a plan shaped like the tracker's.
  const resume = { name: "resume.pdf", type: "application/pdf", base64: Buffer.from("%PDF-1.7 me").toString("base64") };
  // Installed as a page script so the call below uses the exact function text.
  await page.addScriptTag({ content: `${source}; window.__fillFields = fillFields;` });
  const results = await page.evaluate(
    ([assignments, needs, file]) => window.__fillFields(assignments, needs, file),
    [
      [
        { id: byLabel["First Name"].id, value: "Esteven" },
        { id: byLabel["Last Name"].id, value: "Garcia" },
        { id: byLabel.Email.id, value: "esteven@example.com" },
        { id: byLabel["LinkedIn Profile"].id, value: "https://www.linkedin.com/in/esteven" },
        { id: byLabel["Resume/CV"].id, attach: "resume" },
        { id: byLabel.Country.id, value: "United States" },
        { id: byLabel["Send me updates about future roles"].id, value: "Atlantis" },
      ],
      [authorized.id, byLabel["Why do you want to work at Ramp?"].id],
      resume,
    ],
  );

  const state = await page.evaluate(() => ({
    first: document.getElementById("first_name").value,
    last: document.getElementById("last_name").value,
    email: document.getElementById("email").value,
    phone: document.getElementById("phone").value,
    linkedin: document.querySelector("[aria-label='LinkedIn Profile']").value,
    country: document.getElementById("country").value,
    file: document.getElementById("resume").files[0]?.name ?? null,
    fileSize: document.getElementById("resume").files[0]?.size ?? 0,
    authorized: [...document.querySelectorAll("[name=authorized]")].some((r) => r.checked),
    updates: document.querySelector("[name=updates]").checked,
    reactSaw: window.__reactSaw,
    submitted: window.__submitted,
    authorizedOutline: document.querySelector("fieldset").style.outline,
  }));

  assert.equal(state.first, "Esteven");
  assert.deepEqual(state.reactSaw, ["Esteven"], "a React-controlled input heard the change");
  assert.equal(state.last, "Garcia");
  assert.equal(state.email, "esteven@example.com");
  assert.equal(state.phone, "+1 555 0199", "what was already there is untouched");
  assert.equal(state.linkedin, "https://www.linkedin.com/in/esteven");
  assert.equal(state.country, "US", "a select gets the option's value, chosen by its text");
  assert.equal(state.file, "resume.pdf");
  assert.equal(state.fileSize, "%PDF-1.7 me".length);
  assert.equal(state.authorized, false, "the sensitive question is left alone");
  assert.equal(state.updates, false, "an answer that matches no option changes nothing");
  assert.match(state.authorizedOutline, /solid/, "and it's marked for the user");
  assert.equal(state.submitted, 0, "nothing submitted the form");

  const failed = results.filter((result) => !result.ok);
  assert.equal(failed.length, 1);
  assert.equal(failed[0].reason, "no matching option");

  console.log(`✓ autofill filled ${results.length - failed.length} fields and submitted nothing`);
} finally {
  await browser.close();
}
