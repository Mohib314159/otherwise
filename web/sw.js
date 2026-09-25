const CACHE = "otherwise-shell-v5";
const SHELL = [
  "/",
  "/track-record",
  "/batch",
  "/static/app.css",
  "/static/landing.css",
  "/static/mobile.css",
  "/static/desktop.css",
  "/static/common.js",
  "/static/landing.js",
  "/static/pwa.js",
  "/static/track.js",
  "/static/batch.js",
  "/static/verdict.js",
  "/static/chart.js",
  "/static/icon-192.png",
  "/static/icon-512.png",
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

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match(req).then((r) => r || caches.match("/"))));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.match(req).then((cached) => cached || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
      return res;
    })));
  }
});
