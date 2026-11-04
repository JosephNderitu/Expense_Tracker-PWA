{% load static %}
const VERSION = "{{ version }}";
const STATIC_CACHE = "static-" + VERSION;
const PRECACHE = {{ precache|safe }};
const OFFLINE_URL = "{{ offline_url }}";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);
    await Promise.allSettled(PRECACHE.map((url) => cache.add(url)));   // one missing file never blocks the install
    await cache.add(OFFLINE_URL);
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith("static-") && key !== STATIC_CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

// A new version waits until the person taps "Update", so it never swaps code mid-entry
self.addEventListener("message", (event) => { if (event.data === "skipWaiting") self.skipWaiting(); });

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Pages always come from the live site. They are never stored, so nothing private is kept on the device.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(async () => (await caches.match(OFFLINE_URL)) || new Response("You are offline.", { status: 503 })));
    return;
  }
  // Code, fonts and icons: instant from the device, refreshed quietly in the background
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.open(STATIC_CACHE).then(async (cache) => {
      const cached = await cache.match(req);
      const network = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => cached);
      return cached || network;
    }));
  }
  // Anything else (data, reports, private files) goes straight to the network
});

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data ? event.data.text() : "" }; }
  event.waitUntil(self.registration.showNotification(data.title || "Expense Tracker", {
    body: data.body || "",
    icon: "{% static 'icons/icon-192.png' %}",
    badge: "{% static 'icons/icon-192.png' %}",
    tag: data.tag || undefined,
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data.url || "/", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    if (windows.length) {
      try { await windows[0].focus(); return await windows[0].navigate(target); } catch (e) { /* fall through */ }
    }
    return self.clients.openWindow(target);
  })());
});