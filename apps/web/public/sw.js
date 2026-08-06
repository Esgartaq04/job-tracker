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
  if (url.pathname.startsWith("/api/")) return;

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
