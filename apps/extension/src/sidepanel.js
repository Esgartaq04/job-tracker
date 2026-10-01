import { SLOW_REQUEST_MS, apiFetch, getSettings, normalizeBase, originPattern } from "./config.js";
import { collectFormFields, fillFields } from "./autofill.js";

/**
 * The autofill panel (Phase 4b). It stays open beside the form — a popup would close
 * the moment a file dialog took focus — and it holds the resume in memory only: no
 * `chrome.storage`, nothing written anywhere, gone when the panel closes.
 */
const el = (id) => document.getElementById(id);
const state = { file: null, resume: null, profile: null, pendingFrames: [] };

function status(message, tone = "") {
  el("status").textContent = message;
  el("status").className = tone;
}

async function api(path, init = {}) {
  const { apiBase, token } = await getSettings();
  if (!token) throw new Error("Connect the extension first: open its popup → Settings.");
  const waking = setTimeout(
    () => status("Waking the tracker — this can take a minute…"),
    SLOW_REQUEST_MS,
  );
  try {
    const response = await apiFetch(`${normalizeBase(apiBase)}/api/v1${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, ...init.headers },
    });
    if (response.status === 401) throw new Error("Token rejected — reconnect the extension.");
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof body.detail === "string" ? body.detail : `Tracker returned ${response.status}`);
    }
    return body;
  } finally {
    clearTimeout(waking);
  }
}

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

// ── 1. the resume ──────────────────────────────────────────────────────────

el("resume").addEventListener("change", (event) => {
  state.file = event.target.files?.[0] ?? null;
  state.profile = null;
  state.resume = null;
  el("read").disabled = !state.file;
  el("fill").disabled = true;
  el("profile").textContent = "";
});

el("read").addEventListener("click", async () => {
  if (!state.file) return;
  el("read").disabled = true;
  el("profile").textContent = "Reading…";
  try {
    const form = new FormData();
    form.append("resume", state.file);
    state.profile = await api("/autofill/profile", { method: "POST", body: form });
    state.resume = {
      name: state.file.name,
      type: state.file.type || "application/pdf",
      base64: toBase64(await state.file.arrayBuffer()),
    };
    const { first_name, last_name, full_name, email } = state.profile;
    const name = full_name || [first_name, last_name].filter(Boolean).join(" ");
    el("profile").textContent = `Read: ${[name, email].filter(Boolean).join(" · ") || "resume"}`;
    el("profile").className = "muted ok";
    el("fill").disabled = false;
    status("");
  } catch (error) {
    el("profile").textContent = error.message;
    el("profile").className = "muted error";
  } finally {
    el("read").disabled = !state.file;
  }
});

// ── 2. the form ────────────────────────────────────────────────────────────

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

/** Known before any click, like the popup's tab id: the permission prompt only shows
 *  inside the click's gesture, and awaiting a tab query first would spend it. */
let currentTab = null;
const trackTab = () => activeTab().then((tab) => (currentTab = tab ?? null));
trackTab();
chrome.tabs.onActivated.addListener(trackTab);
chrome.tabs.onUpdated.addListener((_id, _change, tab) => tab.active && trackTab());

el("fill").addEventListener("click", async () => {
  const tab = currentTab;
  // Without the `tabs` permission the URL is visible only while the toolbar click's
  // activeTab grant lasts, or once this origin has been allowed before.
  if (!tab?.url) {
    return status(
      "Click the Job Tracker toolbar button on this page once, then press Fill again.",
      "error",
    );
  }
  if (!/^https?:/.test(tab.url)) return status("Open the application form in this tab first.", "error");
  // Called first, with nothing awaited before it. Already granted, it resolves true
  // without a prompt.
  if (!(await chrome.permissions.request({ origins: [originPattern(new URL(tab.url).origin)] }))) {
    return status("Access to this site was declined, so the form can't be filled.", "error");
  }
  await fill(tab);
});

el("allow-frames").addEventListener("click", async () => {
  const granted = await chrome.permissions.request({ origins: state.pendingFrames.map(originPattern) });
  el("allow-frames").hidden = true;
  if (!granted) return status("Access to the embedded form was declined.", "error");
  await fill(await activeTab());
});

async function fill(tab) {
  el("fill").disabled = true;
  status("Reading the form…");
  try {
    // Every frame we're allowed into; frames from other origins are skipped silently
    // and reported by the top frame instead.
    const frames = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: collectFormFields,
    });

    const fields = [];
    const frameOf = new Map();
    const labels = new Map();
    const reachable = new Set();
    let embedded = [];
    for (const { frameId, result } of frames) {
      if (!result) continue;
      reachable.add(result.origin);
      embedded = embedded.concat(result.frames);
      for (const field of result.fields) {
        const id = `${frameId}:${field.id}`;
        frameOf.set(id, { frameId, localId: field.id });
        labels.set(id, field.label || field.name || field.placeholder || "Unlabelled field");
        fields.push({ ...field, id });
      }
    }

    state.pendingFrames = [...new Set(embedded)].filter((origin) => !reachable.has(origin));
    if (state.pendingFrames.length) {
      const hosts = state.pendingFrames.map((origin) => new URL(origin).host).join(", ");
      el("allow-frames").textContent = `Allow the form embedded from ${hosts}`;
      el("allow-frames").hidden = false;
    }

    if (!fields.length) {
      return status(
        state.pendingFrames.length
          ? "The form is inside an embedded frame — allow it above."
          : "No empty form fields found on this page.",
        "error",
      );
    }

    status(`Matching ${fields.length} fields to your resume…`);
    const plan = await api("/autofill/map", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_url: tab.url, fields, profile: state.profile }),
    });

    // Apply per frame: each frame only knows its own field ids.
    const perFrame = new Map();
    const bucket = (frameId) => {
      if (!perFrame.has(frameId)) perFrame.set(frameId, { assignments: [], needs: [] });
      return perFrame.get(frameId);
    };
    for (const assignment of plan.assignments) {
      const { frameId, localId } = frameOf.get(assignment.field_id) ?? {};
      if (frameId === undefined) continue;
      bucket(frameId).assignments.push({ ...assignment, id: localId, key: assignment.field_id });
    }
    for (const need of plan.needs_user) {
      const { frameId, localId } = frameOf.get(need.field_id) ?? {};
      if (frameId !== undefined) bucket(frameId).needs.push(localId);
    }

    const filled = [];
    const needs = plan.needs_user.map((need) => ({ label: labels.get(need.field_id) ?? need.label, detail: need.reason }));
    for (const [frameId, work] of perFrame) {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [frameId] },
        func: fillFields,
        args: [work.assignments, work.needs, state.resume],
      });
      for (const outcome of result ?? []) {
        const assignment = work.assignments.find((a) => a.id === outcome.id);
        const label = labels.get(assignment.key);
        const shown = assignment.attach ? `attached ${state.resume.name}` : assignment.value;
        if (outcome.ok) filled.push({ label, detail: shown });
        else needs.push({ label, detail: `couldn't fill (${outcome.reason})` });
      }
    }

    render(filled, needs);
    status(
      `Filled ${filled.length} field${filled.length === 1 ? "" : "s"}. Review the form, then submit it yourself.`,
      "ok",
    );
  } catch (error) {
    status(error.message, "error");
  } finally {
    el("fill").disabled = !state.profile;
    el("fill").textContent = "Fill again";
  }
}

function render(filled, needs) {
  const list = (target, items, empty) => {
    target.replaceChildren(
      ...(items.length ? items : [{ label: empty, detail: "" }]).map(({ label, detail }) => {
        const item = document.createElement("li");
        const name = document.createElement("span");
        name.className = "label";
        name.textContent = label;
        const value = document.createElement("span");
        value.className = "value";
        value.textContent = detail;
        item.append(name, value);
        return item;
      }),
    );
  };
  list(el("filled"), filled, "Nothing yet");
  list(el("needs"), needs, "Nothing — but still read the form before submitting");
  el("results").hidden = false;
}
