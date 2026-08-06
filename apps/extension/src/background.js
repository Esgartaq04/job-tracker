import { collectPosting } from "./extract.js";

const DEFAULTS = { apiBase: "http://localhost:8000", token: "" };

export async function getSettings() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
}

/**
 * Read the active tab and hand it to the tracker.
 *
 * `activeTab` means the extension can only do this for a tab the user just acted on —
 * it has no standing permission to read any site, which is the point of doing capture
 * here rather than scraping server-side.
 */
export async function savePosting({ tabId, markApplied = false } = {}) {
  const { apiBase, token } = await getSettings();
  if (!token) {
    throw new Error("Not connected — open the extension and paste your tracker token.");
  }

  const tab = tabId
    ? await chrome.tabs.get(tabId)
    : (await chrome.tabs.query({ active: true, currentWindow: true }))[0];

  if (!tab?.id || !/^https?:/.test(tab.url ?? "")) {
    throw new Error("This page can't be saved.");
  }

  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: collectPosting,
  });

  const response = await fetch(`${apiBase.replace(/\/$/, "")}/api/v1/ingest/from-dom`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      url: result.url,
      html: result.html,
      hints: result.hints,
      fallback_text: result.text,
      mark_as_applied: markApplied,
    }),
  });

  if (response.status === 401) {
    throw new Error("Token rejected — reconnect the extension.");
  }
  if (!response.ok) {
    throw new Error(`Tracker returned ${response.status}`);
  }

  const application = await response.json();
  await flashBadge(tab.id, "✓", "#22c55e");
  return application;
}

async function flashBadge(tabId, text, color) {
  await chrome.action.setBadgeText({ tabId, text });
  await chrome.action.setBadgeBackgroundColor({ tabId, color });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 3000);
}

// Keyboard shortcut: save without opening the popup.
chrome.commands?.onCommand.addListener(async (command) => {
  if (command !== "save-posting") return;
  try {
    await savePosting({});
  } catch (error) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) await flashBadge(tab.id, "!", "#f59e0b");
    console.warn("save failed:", error.message);
  }
});

// The popup runs in its own context, so it asks the worker to do the work.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "save-posting") return false;
  savePosting({ markApplied: message.markApplied })
    .then((application) => sendResponse({ ok: true, application }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));
  return true; // keep the channel open for the async reply
});
