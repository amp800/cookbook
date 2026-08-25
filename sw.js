// Minimal service worker so Android Chrome detects the site as installable.
// No caching — this is a static Jekyll site served by GitHub Pages.
self.addEventListener("install", function (event) {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", function (event) {
  // Pass through — let the browser/network handle everything.
  event.respondWith(fetch(event.request));
});