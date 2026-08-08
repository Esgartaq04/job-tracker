import { apiFetch, getSettings, hasApiPermission, normalizeBase } from "./config.js";
import { collectPosting } from "./extract.js";

export { getSettings };

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
  // A service worker has no user gesture, so it can't request the permission itself —
  // say what to press rather than failing later as an opaque CORS error.
  if (!(await hasApiPermission(apiBase))) {
    throw new Error("Allow access to the tracker: open Settings and press Connect.");
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

  // A sleeping free instance takes 30–60s to wake, and a keyboard-shortcut save shows no
  // popup — so the badge has to say "working" or the whole thing looks like it did nothing.
  await setBadge(tab.id, "…", "#6366f1");

  let response;
  try {
    response = await apiFetch(`${normalizeBase(apiBase)}/api/v1/ingest/from-dom`, {
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
  } catch (error) {
    await clearBadge(tab.id);
    throw error;
  }

  if (!response.ok) {
    await clearBadge(tab.id);
    if (response.status === 401) {
      throw new Error("Token rejected — reconnect the extension.");
    }
    throw new Error(`Tracker returned ${response.status}`);
  }

  const application = await response.json();
  await flashBadge(tab.id, "✓", "#22c55e");
  return application;
}

async function setBadge(tabId, text, color) {
  await chrome.action.setBadgeText({ tabId, text });
  await chrome.action.setBadgeBackgroundColor({ tabId, color });
}

async function clearBadge(tabId) {
  await chrome.action.setBadgeText({ tabId, text: "" });
}

async function flashBadge(tabId, text, color) {
  await setBadge(tabId, text, color);
  setTimeout(() => clearBadge(tabId), 3000);
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
