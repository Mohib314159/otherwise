// Otherwise service worker: installable app + offline fallback, never a stale deploy.
//
// Every same-origin GET goes to the network first, revalidating against the HTTP
// cache (cache: "no-cache"), so a new deploy's HTML, JS and CSS are what a
// phone sees as soon as it is online. The Cache Storage copy is used only when
// the network fails. Only successful, same-origin responses are stored, so an
// error page served mid-deploy can never become the offline copy.
// /api/* is never intercepted: results and job status always come live.
const CACHE = "otherwise-offline-v2";
const SHELL = [
  "/",
  "/track-record",
  "/static/app.css",
  "/static/landing.css",
  "/static/mobile.css",
  "/static/desktop.css",
  "/static/common.js",
  "/static/landing.js",
  "/static/pwa.js",
  "/static/icon-192.png",
  "/static/favicon.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

function networkFirst(req, fallbackUrl) {
  return fetch(req, { cache: "no-cache" }).then((res) => {
    if (res.ok && res.type === "basic") {
      const copy = res.clone();
      caches.open(CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
    }
    return res;
  }).catch(() => caches.match(req).then((hit) => hit || (fallbackUrl ? caches.match(fallbackUrl) : undefined))
    .then((hit) => hit || Response.error()));
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req, "/"));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(networkFirst(req, null));
  }
});
