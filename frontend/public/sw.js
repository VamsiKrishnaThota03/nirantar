/* Service worker for the Nirantar field app.
 *
 * Scope is deliberately narrow. Two rules:
 *
 * 1. **The app shell is cache-first.** HTML, JS and CSS are served from the
 *    cache when offline, so a health worker in a village with no signal can
 *    still open the app. Without this, "works offline" would be a claim the
 *    software does not keep: the task data is already in local storage, but
 *    the page itself would fail to load.
 *
 * 2. **API responses are never cached.** Health data is not something to
 *    leave lying in a browser cache, and a stale care obligation is worse
 *    than a missing one. The field view keeps its own explicit, visible
 *    snapshot in local storage and tells the user when it is showing it;
 *    that is a decision the user can see, which an invisible HTTP cache is
 *    not.
 */

const CACHE = "nirantar-shell-v1";
const SHELL = ["/", "/index.html"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Rule 2: never cache person-level data.
  if (url.pathname.startsWith("/api/")) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        // Refresh in the background so the next load is current, but answer
        // immediately from cache.
        event.waitUntil(
          fetch(request)
            .then((response) => {
              if (response && response.ok) {
                return caches.open(CACHE).then((cache) => cache.put(request, response));
              }
              return undefined;
            })
            .catch(() => undefined),
        );
        return cached;
      }
      return fetch(request)
        .then((response) => {
          if (response && response.ok && response.type === "basic") {
            const copy = response.clone();
            event.waitUntil(
              caches.open(CACHE).then((cache) => cache.put(request, copy)),
            );
          }
          return response;
        })
        .catch(() =>
          // Navigation offline with nothing cached for this exact URL: fall
          // back to the app shell so the SPA can boot and render its own
          // offline state.
          request.mode === "navigate"
            ? caches.match("/index.html").then((shell) => shell ?? Response.error())
            : Response.error(),
        );
    }),
  );
});
