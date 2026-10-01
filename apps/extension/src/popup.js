import {
  DEFAULTS,
  SLOW_REQUEST_MS,
  apiFetch,
  getSettings as settings,
  hasApiPermission,
  normalizeBase,
  requestApiPermission,
} from "./config.js";

const el = (id) => document.getElementById(id);

/** Known before any click: `sidePanel.open` must run inside the click's gesture, and
 *  awaiting a tab query first would spend it. */
let activeTabId = null;

function fail(message) {
  el("settings-status").textContent = message;
  el("settings-status").className = "error";
}

function show(section) {
  el("save").hidden = section !== "save";
  el("settings").hidden = section !== "settings";
}

async function render() {
  const { apiBase, token } = await settings();
  el("api-base").value = apiBase;
  el("token").value = token;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTabId = tab?.id ?? null;
  el("page").textContent = tab?.title ?? tab?.url ?? "";

  // No token — or a token whose host we're not allowed to reach — means nothing works,
  // so open straight into settings rather than letting the user press a button that can
  // only fail. Pressing Connect from here is what grants the host.
  const ready = Boolean(token) && (await hasApiPermission(apiBase));
  if (token && !ready) {
    el("settings-status").textContent = "Press Connect to allow access to the tracker.";
    el("settings-status").className = "";
  }
  show(ready ? "save" : "settings");
}

async function save(markApplied) {
  el("status").textContent = "Saving…";
  el("status").className = "";
  // The free instance sleeps; without this the popup reads "Saving…" for a silent minute.
  const waking = setTimeout(
    () => (el("status").textContent = "Waking the tracker — this can take a minute…"),
    SLOW_REQUEST_MS,
  );

  const response = await chrome.runtime.sendMessage({ type: "save-posting", markApplied });
  clearTimeout(waking);

  if (response?.ok) {
    const { company, title, duplicate } = response.application ?? {};
    const name = [company, title].filter(Boolean).join(" — ") || "posting";
    if (duplicate) {
      // Said plainly and left open: if this isn't the job on screen, the user needs to
      // see that rather than a confident "Saved" that hides it.
      el("status").textContent = `Already on your board: ${name}`;
      el("status").className = "";
      return;
    }
    el("status").textContent = `Saved ${name}`;
    el("status").className = "ok";
    setTimeout(() => window.close(), 1200);
  } else {
    el("status").textContent = response?.error ?? "Something went wrong";
    el("status").className = "error";
  }
}

el("save-btn").addEventListener("click", () => save(false));
el("save-applied-btn").addEventListener("click", () => save(true));
el("settings-btn").addEventListener("click", () => show("settings"));

// The side panel stays open beside the form, which a popup can't: it closes the moment
// a file dialog takes focus.
el("autofill-btn").addEventListener("click", () => {
  if (activeTabId === null) return;
  chrome.sidePanel
    .open({ tabId: activeTabId })
    .then(() => window.close())
    .catch((error) => {
      el("status").textContent = `Couldn't open the autofill panel: ${error.message}`;
      el("status").className = "error";
    });
});

el("save-settings").addEventListener("click", async () => {
  const apiBase = normalizeBase(el("api-base").value) || DEFAULTS.apiBase;
  const token = el("token").value.trim();

  if (!token) return fail("Paste a token first");

  try {
    new URL(apiBase);
  } catch {
    return fail("That doesn't look like a URL — include https://");
  }

  // Ask for the one origin the user typed. This click is the gesture Chrome requires,
  // and without the grant every later request is an opaque CORS failure.
  if (!(await hasApiPermission(apiBase)) && !(await requestApiPermission(apiBase))) {
    return fail("Access to the tracker was declined, so saving can't work.");
  }

  // Verify before storing, so a typo surfaces here rather than on the first save.
  el("settings-status").textContent = "Checking…";
  el("settings-status").className = "";
  const waking = setTimeout(
    () => (el("settings-status").textContent = "Waking the tracker — this can take a minute…"),
    SLOW_REQUEST_MS,
  );
  try {
    const response = await apiFetch(`${apiBase}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.status === 401) throw new Error("that token was rejected");
    if (!response.ok) throw new Error(`Tracker returned ${response.status}`);
  } catch (error) {
    return fail(error.message);
  } finally {
    clearTimeout(waking);
  }

  await chrome.storage.sync.set({ apiBase, token });
  el("settings-status").textContent = "Connected";
  el("settings-status").className = "ok";
  show("save");
});

render();
