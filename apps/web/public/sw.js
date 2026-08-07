/**
 * Minimal service worker: enough to make the app installable and to keep the shell
 * available on a flaky connection. Deliberately not an offline-first cache — the board
 * is server state, and a stale board is worse than an honest "you're offline".
 *
 * Share-target requests are GET (see manifest.webmanifest), so they need no handling
 * here; the app reads `?url=` / `?text=` / `?title=` on startup.
 */

const SHELL = "tracker-shell-v1";
const SHELL_ASSETS = ["/", "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== SHELL).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Never cache the API: an out-of-date board that looks live is the worst outcome.
  // Same-origin behind nginx or the Vite proxy; a different origin once VITE_API_ORIGIN
  // points the SPA at a separately hosted API, which also covers the SSE stream.
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  // Vercel's analytics script and beacon are same-origin under /_vercel/. Caching them
  // would pin a stale script and hide the endpoint behind the shell cache.
  if (url.pathname.startsWith("/_vercel/")) return;

  // Navigations: network first, shell as the fallback when offline.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/")));
    return;
  }

  // Built assets are content-hashed, so a cache hit is always correct.
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ??
        fetch(request).then((response) => {
          if (response.ok && url.origin === self.location.origin) {
            const copy = response.clone();
            caches.open(SHELL).then((cache) => cache.put(request, copy));
          }
          return response;
        }),
    ),
  );
});
