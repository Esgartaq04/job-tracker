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

/** The deployed API (docs/DEPLOYMENT.md). Point this at http://localhost:8000 in the
 *  popup's Settings when working against a local API instead. */
export const DEFAULTS = {
  apiBase: "https://job-tracker-api-a8gp.onrender.com",
  token: "",
};

/**
 * The API is on a free instance that sleeps after 15 minutes idle and takes 30–60s to
 * wake. That's longer than any request should normally take, so requests get a generous
 * budget and the UI explains the wait rather than looking broken.
 */
export const REQUEST_TIMEOUT_MS = 90_000;
export const SLOW_REQUEST_MS = 3_000;

/** fetch with a deadline, and errors a person can act on. */
export async function apiFetch(url, init = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The tracker didn't respond in 90s. It may be starting up — try again.");
    }
    // A DNS failure, an offline machine and a missing host permission all land here as
    // the same opaque "Failed to fetch", so name the likely causes.
    throw new Error("Couldn't reach the tracker. Check the URL, your connection, and that you pressed Connect.");
  } finally {
    clearTimeout(timer);
  }
}

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
