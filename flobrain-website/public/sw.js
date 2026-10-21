/* FloBrain workspace service worker (Phase 10).
 * - Offline shell: page navigations fall back to /offline.html when the network is down.
 * - Never caches API responses (they are private and change often).
 * - Web Push: shows the title and opens the link, same origin only.
 */
const SHELL = "flobrain-shell-v1";
const OFFLINE_URL = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll([OFFLINE_URL, "/manifest.webmanifest"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate") return;
  event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = {};
  }
  const title = typeof data.title === "string" ? data.title.slice(0, 120) : "FloBrain";
  const url = typeof data.url === "string" && data.url.startsWith("/") ? data.url : "/w/signin";
  event.waitUntil(self.registration.showNotification(title, { body: "", icon: "/icons/flobrain-192.png", data: { url } }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data && event.notification.data.url ? event.notification.data.url : "/w/signin", self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const win of wins) {
        if ("focus" in win) {
          win.navigate(url.href);
          return win.focus();
        }
      }
      return self.clients.openWindow(url.href);
    }),
  );
});
