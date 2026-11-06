(() => {
  const $ = (s) => document.querySelector(s);
  const state = { L: null, type: "entry", workspace: "household" };

  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (v !== false && v !== null && v !== undefined) n.setAttribute(k, v === true ? "" : v);
    }
    kids.flat().forEach((c) => c != null && n.append(c));
    return n;
  };
  const INPUT = "block min-h-11 w-full rounded-lg border border-line bg-surface px-3.5 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30";
  const today = () => { const d = new Date(); return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-"); };
  const field = (label, input) => el("label", { class: "block space-y-1.5" }, el("span", { class: "block text-sm font-medium text-ink", text: label }), input);
  const input = (name, o = {}) => el("input", { class: INPUT, name, type: o.type || "text", required: o.required, step: o.step, min: o.min, inputmode: o.inputmode, placeholder: o.placeholder, value: o.value, list: o.list, autocomplete: "off" });
  const select = (name, options, o = {}) => {
    const s = el("select", { class: INPUT, name, required: o.required });
    options.forEach(([v, l]) => s.append(el("option", { value: v, text: l, selected: String(v) === String(o.value) })));
    return s;
  };
  const truck = () => state.L.trucks.length > 1
    ? field("Truck", select("truck", state.L.trucks.map((t) => [t.id, t.name])))
    : el("input", { type: "hidden", name: "truck", value: state.L.trucks[0] ? state.L.trucks[0].id : "" });

  const TYPES = {
    entry: { label: "Expense or income", icon: "fa-receipt" },
    fuel: { label: "Fuel", icon: "fa-gas-pump" },
    job: { label: "Job", icon: "fa-route" },
  };

  function fields() {
    const L = state.L;
    if (state.type === "entry") {
      const ws = L.workspaces.find((w) => w.type === state.workspace) || L.workspaces[0];
      return [
        field("Category", select("category", ws.categories.map((c) => [c.id, c.name + (c.kind === "income" ? " (money in)" : "")]), { required: true })),
        field("Amount", input("amount", { type: "number", step: "0.01", min: "0.01", inputmode: "decimal", required: true, placeholder: "0.00" })),
        field("Date", input("date", { type: "date", required: true, value: today() })),
        field("Method", select("payment_method", L.methods, { value: "cash" })),
        field("Note (optional)", input("note")),
      ];
    }
    if (state.type === "fuel") return [
      field("Date", input("date", { type: "date", required: true, value: today() })),
      field("Gallons", input("gallons", { type: "number", step: "0.001", min: "0.001", inputmode: "decimal", required: true })),
      field("Price per gallon (optional)", input("price_per_gallon", { type: "number", step: "0.001", min: "0.001", inputmode: "decimal" })),
      field("Total cost", input("total", { type: "number", step: "0.01", min: "0.01", inputmode: "decimal", required: true })),
      state.L.workspaces.some((w) => w.type === "work" && w.currency !== "USD") ? null
        : field("State", select("state", [["", "Choose state"], ...L.states.map((s) => [s, s])], { required: true, value: L.last_state })),
      field("Method", select("payment_method", L.methods, { value: "card" })),
      field("Odometer (optional)", input("odometer", { type: "number", min: "0", inputmode: "numeric" })),
      truck(),
      field("Note (optional)", input("note")),
    ];
    return [
      field("Date", input("date", { type: "date", required: true, value: today() })),
      field("Pay for this job", input("gross_pay", { type: "number", step: "0.01", min: "0.01", inputmode: "decimal", required: true, placeholder: "0.00" })),
      field("Broker or customer", input("broker_name", { list: "brokers", placeholder: "Type a name" })),
      field("Load or BOL number", input("reference")),
      el("div", { class: "grid grid-cols-2 gap-3" }, field("From", input("origin")), field("To", input("destination"))),
      field("Miles (optional)", input("miles", { type: "number", min: "0", inputmode: "numeric" })),
      truck(),
      field("Notes (optional)", input("notes")),
      el("datalist", { id: "brokers" }, L.brokers.map((b) => el("option", { value: b }))),
    ];
  }

  const sym = () => {
    const ws = state.L.workspaces.find((w) => w.type === (state.type === "entry" ? state.workspace : "work"));
    return (ws && ws.symbol) || "$";
  };
  const LABELS = {
    entry: (d) => `${sym()}${d.amount} · ${(document.querySelector("select[name=category] option:checked") || {}).textContent || "Entry"}`,
    fuel: (d) => `${d.gallons} gal${d.state ? " · " + d.state : ""} · ${sym()}${d.total}`,
    job: (d) => `${sym()}${d.gross_pay} · ${[d.origin, d.destination].filter(Boolean).join(" to ") || "Job"}`,
  };

  function renderTabs() {
    const bar = $("#type-tabs");
    bar.replaceChildren(...Object.entries(TYPES).map(([key, t]) => el("button", {
      type: "button", "aria-pressed": String(state.type === key),
      class: "inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-full px-3 text-sm font-medium " + (state.type === key ? "bg-accent text-on-accent shadow-sm" : "text-muted hover:text-ink"),
    }, el("i", { class: "fa-solid " + t.icon }), el("span", { text: t.label }))));
    [...bar.children].forEach((b, i) => b.addEventListener("click", () => { state.type = Object.keys(TYPES)[i]; renderForm(); renderTabs(); }));
    const ws = $("#workspace-tabs");
    ws.classList.toggle("hidden", state.type !== "entry");
    ws.replaceChildren(...["household", "work"].map((w) => el("button", {
      type: "button", "aria-pressed": String(state.workspace === w),
      class: "min-h-10 flex-1 rounded-full px-3 text-sm font-medium " + (state.workspace === w ? "bg-line text-ink" : "text-muted hover:text-ink"),
      text: w === "household" ? "Household" : "Work",
    })));
    [...ws.children].forEach((b, i) => b.addEventListener("click", () => { state.workspace = ["household", "work"][i]; renderForm(); renderTabs(); }));
  }

  function renderForm() {
    const form = $("#entry-form");
    form.replaceChildren(...fields().filter(Boolean), el("button", { class: "min-h-12 w-full rounded-lg bg-accent px-4 text-sm font-medium text-on-accent hover:opacity-90", text: "Save on this device" }));
    const total = form.querySelector("[name=total]"), gal = form.querySelector("[name=gallons]"), price = form.querySelector("[name=price_per_gallon]");
    if (total && gal && price) {
      let touched = false;
      total.addEventListener("input", () => { touched = true; });
      const calc = () => { const v = parseFloat(gal.value) * parseFloat(price.value); if (!touched && Number.isFinite(v)) total.value = v.toFixed(2); };
      gal.addEventListener("input", calc);
      price.addEventListener("input", calc);
    }
  }

  async function renderQueue() {
    const list = $("#queue-list");
    const items = (await OfflineDB.queueAll()).filter((i) => i.owner === state.L.user).sort((a, b) => a.created - b.created);
    $("#queue-empty").classList.toggle("hidden", items.length > 0);
    $("#sync-now").classList.toggle("hidden", items.length === 0);
    list.replaceChildren(...items.map((i) => {
      const bad = i.status === "error";
      const row = el("li", { class: "space-y-2 px-4 py-3" },
        el("div", { class: "flex items-center gap-3" },
          el("span", { class: "grid size-9 shrink-0 place-items-center rounded-full " + (bad ? "bg-negative/10 text-negative" : "bg-accent/10 text-accent") }, el("i", { class: "fa-solid " + (bad ? "fa-circle-exclamation" : TYPES[i.kind].icon) + " text-sm" })),
          el("span", { class: "min-w-0 flex-1" }, el("span", { class: "block truncate text-sm font-medium", text: i.label }), el("span", { class: "block text-xs text-muted", text: bad ? "Could not be saved" : "Waiting to sync" })),
          el("button", { type: "button", class: "min-h-9 rounded-lg px-3 text-sm font-medium text-negative hover:bg-negative/10", text: "Remove", "data-remove": i.client_id })),
        bad ? el("div", { class: "rounded-lg bg-negative/10 px-3 py-2 text-xs text-negative" }, (i.errors || []).map((e) => el("p", { text: e })), el("button", { type: "button", class: "mt-1 font-medium underline", text: "Try again", "data-retry": i.client_id })) : null);
      return row;
    }));
    list.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", async () => { await OfflineDB.queueDelete(b.dataset.remove); await refresh(); }));
    list.querySelectorAll("[data-retry]").forEach((b) => b.addEventListener("click", async () => {
      const item = items.find((i) => i.client_id === b.dataset.retry);
      item.status = "pending"; delete item.errors;
      await OfflineDB.queuePut(item);
      await window.PWA.syncQueue();
      await refresh();
    }));
  }

  async function refresh() { await renderQueue(); window.PWA && window.PWA.updateChip(); }

  function banner() {
    const online = navigator.onLine;
    $("#status-banner").className = "flex items-center gap-3 rounded-xl border px-4 py-3 text-sm " + (online ? "border-line bg-surface text-muted" : "border-amber-500/40 bg-amber-500/10 text-amber-700");
    $("#status-text").textContent = online ? "You are online. Entries you save here are sent straight away." : "You are offline. Entries are kept on this device and sent when you are back online.";
    $("#status-icon").className = "fa-solid " + (online ? "fa-wifi" : "fa-plane");
  }

  async function init() {
    banner();
    window.addEventListener("online", async () => { banner(); await window.PWA.syncQueue(); await refresh(); });
    window.addEventListener("offline", banner);
    if (navigator.onLine) await window.PWA.refreshLookups(true);
    state.L = await OfflineDB.getMeta("lookups");
    if (!state.L) { $("#missing").classList.remove("hidden"); return; }
    $("#builder").classList.remove("hidden");
    renderTabs(); renderForm(); await renderQueue();

    $("#entry-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      if (!form.reportValidity()) return;
      const data = Object.fromEntries(new FormData(form).entries());
      if (state.type === "entry") data.workspace = state.workspace;
      const item = { client_id: crypto.randomUUID(), owner: state.L.user, kind: state.type, data, status: "pending", created: Date.now(), label: LABELS[state.type](data) };
      await OfflineDB.queuePut(item);
      window.PWA.toast(navigator.onLine ? "Saved. Sending now…" : "Saved on this device. It will send when you are online.");
      renderForm();
      await window.PWA.syncQueue();
      await refresh();
    });
    $("#sync-now").addEventListener("click", async () => { await window.PWA.syncQueue(); await refresh(); });
  }
  init();
})();