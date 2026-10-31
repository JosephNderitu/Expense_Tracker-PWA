(() => {
  document.querySelectorAll("[data-typeahead]").forEach((root) => {
    const input = root.querySelector("input");
    const list = root.querySelector("[role=listbox]");
    const names = JSON.parse(document.getElementById(root.dataset.source).textContent);
    let shown = [], active = -1;

    const close = () => { list.classList.add("hidden"); input.setAttribute("aria-expanded", "false"); active = -1; };
    const choose = (name) => { input.value = name; close(); };
    const paint = () => {
      [...list.children].forEach((li, i) => {
        if (li.getAttribute("role") !== "option") return;
        li.setAttribute("aria-selected", String(i === active));
      });
      if (active >= 0) input.setAttribute("aria-activedescendant", `${list.id}-${active}`);
      else input.removeAttribute("aria-activedescendant");
    };

    function render() {
      const q = input.value.trim().toLowerCase();
      const starts = names.filter((n) => n.toLowerCase().startsWith(q));
      const contains = names.filter((n) => !n.toLowerCase().startsWith(q) && n.toLowerCase().includes(q));
      shown = (q ? [...starts, ...contains] : names).slice(0, 8);
      list.replaceChildren();
      shown.forEach((name, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = `${list.id}-${i}`;
        li.className = "cursor-pointer px-3.5 py-2.5 text-sm hover:bg-line/50 aria-selected:bg-accent/10";
        li.textContent = name;
        li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(name); });
        list.appendChild(li);
      });
      if (q && !names.some((n) => n.toLowerCase() === q)) {
        const hint = document.createElement("li");
        hint.className = "px-3.5 py-2 text-xs text-muted";
        hint.textContent = `New name: "${input.value.trim()}" will be saved for next time`;
        list.appendChild(hint);
      }
      active = -1;
      list.classList.toggle("hidden", list.children.length === 0);
      input.setAttribute("aria-expanded", String(!list.classList.contains("hidden")));
      paint();
    }

    input.addEventListener("input", render);
    input.addEventListener("focus", render);
    input.addEventListener("blur", close);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); if (list.classList.contains("hidden")) render(); active = Math.min(active + 1, shown.length - 1); paint(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); paint(); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(shown[active]); }
      else if (e.key === "Escape") close();
    });
  });
})();