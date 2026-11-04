(() => {
  const authed = document.body.dataset.auth === "1";
  const standalone = matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const show = (selector, on) => document.querySelectorAll(selector).forEach((el) => el.classList.toggle("hidden", !on));

  function toast(message) {
    const t = document.createElement("div");
    t.setAttribute("role", "status");
    t.className = "fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-50 mx-auto max-w-md rounded-xl bg-ink px-4 py-3 text-sm text-canvas shadow-card lg:bottom-6";
    t.textContent = message;
    document.body.append(t);
    setTimeout(() => t.remove(), 4500);
  }

  // ---- service worker, with an "Update" prompt
  if ("serviceWorker" in navigator) {
    const hadController = Boolean(navigator.serviceWorker.controller);
    let reloading = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController && !reloading) { reloading = true; location.reload(); }
    });
    window.addEventListener("load", async () => {
      try {
        const reg = await navigator.serviceWorker.register("/sw.js");
        const offer = (worker) => {
          const banner = document.getElementById("update-banner");
          if (!banner) return;
          banner.classList.remove("hidden");
          document.getElementById("update-now").onclick = () => worker.postMessage("skipWaiting");
        };
        if (reg.waiting && navigator.serviceWorker.controller) offer(reg.waiting);
        reg.addEventListener("updatefound", () => {
          const worker = reg.installing;
          if (worker) worker.addEventListener("statechange", () => {
            if (worker.state === "installed" && navigator.serviceWorker.controller) offer(worker);
          });
        });
      } catch (e) { /* the site works fine without it */ }
    });
  }

  // ---- install
  let deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    show("[data-install]", true);
    if (!localStorage.getItem("install-dismissed")) show("[data-install-banner]", true);
  });
  document.querySelectorAll("[data-install-button]").forEach((btn) => btn.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    show("[data-install], [data-install-banner]", false);
  }));
  const dismiss = document.getElementById("install-dismiss");
  if (dismiss) dismiss.addEventListener("click", () => { localStorage.setItem("install-dismissed", "1"); show("[data-install-banner]", false); });
  window.addEventListener("appinstalled", () => show("[data-install], [data-install-banner]", false));
  if (/iphone|ipad|ipod/i.test(navigator.userAgent) && !standalone) show("[data-ios-hint]", true);
  if (standalone) show("[data-not-installed]", false);

  // ---- offline queue: keep the lookups fresh and send waiting entries when there is a connection
  const csrf = () => (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || "";

  async function refreshLookups(force = false) {
    if (!navigator.onLine) return null;
    try {
      const last = await OfflineDB.getMeta("lookups_at");
      if (!force && last && Date.now() - last < 3600000) return null;
      const res = await fetch("/pwa/lookups.json", { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!res.ok) return null;
      const data = await res.json();
      await OfflineDB.setMeta("lookups", data);
      await OfflineDB.setMeta("lookups_at", Date.now());
      return data;
    } catch (e) { return null; }
  }

  async function updateChip() {
    const chip = document.getElementById("sync-chip");
    if (!chip) return;
    try {
      const lookups = await OfflineDB.getMeta("lookups");
      const items = lookups ? (await OfflineDB.queueAll()).filter((i) => i.owner === lookups.user) : [];
      chip.classList.toggle("hidden", items.length === 0);
      document.getElementById("sync-count").textContent = items.length;
    } catch (e) { /* storage unavailable  test series*/ }
  }

  async function syncQueue() {
    if (!navigator.onLine) return 0;
    try {
      const lookups = await OfflineDB.getMeta("lookups");
      if (!lookups) return 0;
      const pending = (await OfflineDB.queueAll()).filter((i) => i.owner === lookups.user && i.status === "pending");
      if (!pending.length) return 0;
      const res = await fetch("/pwa/sync/", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ items: pending.map(({ client_id, kind, data }) => ({ client_id, kind, data })) }),
      });
      if (res.status === 401 || res.status === 403) { toast("Sign in again to save your offline entries."); return 0; }
      if (!res.ok) return 0;
      let saved = 0;
      for (const r of (await res.json()).results) {
        const item = pending.find((i) => i.client_id === r.client_id);
        if (!item) continue;
        if (r.status === "ok") { await OfflineDB.queueDelete(r.client_id); saved++; }
        else { item.status = "error"; item.errors = r.errors; await OfflineDB.queuePut(item); }
      }
      if (saved) toast(`${saved} offline ${saved === 1 ? "entry" : "entries"} saved.`);
      return saved;
    } catch (e) { return 0; }
  }

  window.PWA = { toast, refreshLookups, syncQueue, updateChip };

  if (authed && "indexedDB" in window) {
    const run = async () => { await refreshLookups(); await syncQueue(); await updateChip(); };
    window.addEventListener("load", run);
    window.addEventListener("online", async () => { await refreshLookups(true); await syncQueue(); await updateChip(); });
  }
})();