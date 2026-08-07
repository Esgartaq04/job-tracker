/**
 * Where the tracker lives, and permission to talk to it.
 *
 * The extension has no `host_permissions` for job sites by design — it reads a tab only
 * after you click it (`activeTab`). But its own requests to the API are ordinary
 * cross-origin requests from `chrome-extension://<id>`, and an unpacked install gets a
 * different id on every machine, so the API can't list them in `CORS_ORIGINS`.
 *
 * A granted host permission exempts the extension's own requests from CORS. Rather than
 * hardcoding one deployment's host in the manifest, the origin is requested at runtime
 * from the Connect button — the user's gesture, for exactly the host they typed.
 */

export const DEFAULTS = { apiBase: "http://localhost:8000", token: "" };

export async function getSettings() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
}

export function normalizeBase(apiBase) {
  return (apiBase || "").trim().replace(/\/+$/, "");
}

/** `https://api.example.com/*` — the narrowest pattern that covers the API. */
export function originPattern(apiBase) {
  return `${new URL(normalizeBase(apiBase)).origin}/*`;
}

export async function hasApiPermission(apiBase) {
  try {
    return await chrome.permissions.contains({ origins: [originPattern(apiBase)] });
  } catch {
    return false; // not a valid URL — the caller reports that more usefully
  }
}

/** Must be called from a user gesture; Chrome rejects it from a service worker. */
export async function requestApiPermission(apiBase) {
  return chrome.permissions.request({ origins: [originPattern(apiBase)] });
}
