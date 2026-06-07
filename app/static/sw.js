// Service worker Pointage Bus : installable + repli hors-ligne.
// Ne touche JAMAIS aux requêtes POST (les saisies passent toujours par le réseau).
const CACHE = "pointage-v1";
const ASSETS = [
  "/offline",
  "/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return; // saisies (POST) : jamais interceptées
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Navigations : réseau d'abord, page hors-ligne en repli.
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("/offline")));
    return;
  }

  // Assets statiques + manifeste : cache d'abord.
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    e.respondWith(
      caches.match(req).then(
        (cached) =>
          cached ||
          fetch(req).then((resp) => {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
            return resp;
          })
      )
    );
  }
  // Tout le reste (ex. /api/status) : réseau, non mis en cache.
});
