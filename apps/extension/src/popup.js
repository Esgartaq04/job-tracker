const DEFAULTS = { apiBase: "http://localhost:8000", token: "" };

const el = (id) => document.getElementById(id);

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
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
  el("page").textContent = tab?.title ?? tab?.url ?? "";

  // No token means nothing works, so open straight into settings rather than
  // letting the user press a button that can only fail.
  show(token ? "save" : "settings");
}

async function save(markApplied) {
  el("status").textContent = "Saving…";
  el("status").className = "";

  const response = await chrome.runtime.sendMessage({ type: "save-posting", markApplied });

  if (response?.ok) {
    const { company, title } = response.application ?? {};
    el("status").textContent = `Saved ${[company, title].filter(Boolean).join(" — ") || "posting"}`;
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

el("save-settings").addEventListener("click", async () => {
  const apiBase = el("api-base").value.trim() || DEFAULTS.apiBase;
  const token = el("token").value.trim();

  if (!token) {
    el("settings-status").textContent = "Paste a token first";
    el("settings-status").className = "error";
    return;
  }

  // Verify before storing, so a typo surfaces here rather than on the first save.
  try {
    const response = await fetch(`${apiBase.replace(/\/$/, "")}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error(`Tracker returned ${response.status}`);
  } catch (error) {
    el("settings-status").textContent = `Couldn't reach the tracker: ${error.message}`;
    el("settings-status").className = "error";
    return;
  }

  await chrome.storage.sync.set({ apiBase, token });
  el("settings-status").textContent = "Connected";
  el("settings-status").className = "ok";
  show("save");
});

render();
