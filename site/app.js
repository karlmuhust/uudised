// Uudised front end: shows the top 20 unread stories, keeps read / not-interested clicks.
(() => {
  "use strict";

  const TOP_N = 20;
  const LS_STATE = "uudised.state";
  const TOPIC_LABEL = {
    "ukraine-russia": "Ukraine & Russia", "tech-ai": "Tech & AI", "estonia-politics": "Estonian politics",
    economy: "Economy", security: "Security", eu: "EU", world: "World", science: "Science",
    "climate-energy": "Climate & energy", culture: "Culture", other: "Other",
  };
  const REGION_LABEL = { estonia: "Estonia", "baltics-nordics": "Baltics & Nordics", europe: "Europe", world: "World" };

  const $ = (id) => document.getElementById(id);
  const ls = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked */ } },
  };

  let stories = [];
  let byId = new Map();
  let state = ls.get(LS_STATE, { read: {}, dismissed: {} });
  let synced = false;
  let view = "feed";
  let histMode = "read";
  let lastAction = null;

  const nowIso = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");

  // ---- state sync --------------------------------------------------------
  async function api(method, body) {
    const res = await fetch("api/state", {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`Saving clicks failed (${res.status}).`);
    return res.json();
  }

  async function pullState() {
    try {
      const remote = await api("GET");
      synced = true;
      // remote wins, but keep local clicks the server doesn't know yet
      state = {
        read: { ...state.read, ...remote.read },
        dismissed: { ...state.dismissed, ...remote.dismissed },
      };
      for (const id of Object.keys(remote.read)) delete state.dismissed[id];
      for (const id of Object.keys(remote.dismissed)) delete state.read[id];
      ls.set(LS_STATE, state);
    } catch (e) {
      synced = false;
      setStatus("The local server isn't answering, so clicks are kept in this browser for now.");
    }
  }

  async function act(id, action) {
    delete state.read[id];
    delete state.dismissed[id];
    if (action === "read") state.read[id] = nowIso();
    if (action === "dismiss") state.dismissed[id] = nowIso();
    ls.set(LS_STATE, state);
    if (synced) {
      try { await api("POST", { id, action }); }
      catch (e) { setStatus(`${e.message} Saved in this browser only.`); }
    }
  }

  // ---- rendering ---------------------------------------------------------
  function setStatus(text, undo) {
    const el = $("status");
    el.textContent = text;
    if (undo) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn ghost";
      b.style.marginLeft = "8px";
      b.textContent = "Undo";
      b.addEventListener("click", async () => {
        await act(undo, "undo");
        lastAction = null;
        setStatus("Undone.");
        render();
      });
      el.append(b);
    }
  }

  function isDone(id) { return id in state.read || id in state.dismissed; }

  function feedStories() {
    return stories
      .filter((s) => !isDone(s.id))
      .sort((a, b) => b.importance - a.importance || a.first_seen.localeCompare(b.first_seen))
      .slice(0, TOP_N);
  }

  function card(s, rank) {
    const node = $("card-tpl").content.firstElementChild.cloneNode(true);
    node.dataset.id = s.id;
    const r = node.querySelector(".rank");
    if (rank != null) {
      r.innerHTML = `<span>${String(rank).padStart(2, "0")}</span><span class="meter" title="Importance ${s.importance}/100"><i style="width:${s.importance}%"></i></span>`;
    } else {
      r.innerHTML = `<span class="meter" title="Importance ${s.importance}/100"><i style="width:${s.importance}%"></i></span>`;
    }
    node.querySelector(".topic").textContent = TOPIC_LABEL[s.topic] || s.topic;
    node.querySelector(".region").textContent = REGION_LABEL[s.region] || s.region;
    node.querySelector(".flag").hidden = !s.has_update;
    const fu = node.querySelector(".followup");
    if (s.follow_up_of && byId.has(s.follow_up_of)) {
      fu.hidden = false;
      fu.title = `Follow-up to: ${byId.get(s.follow_up_of).title}`;
    }
    const a = node.querySelector(".title a");
    a.href = s.links[0].url;
    a.textContent = s.title;
    a.lang = s.lang;
    node.querySelector(".why").textContent = s.why;
    const ex = node.querySelector(".excerpt");
    ex.textContent = s.excerpt || "";
    ex.lang = s.lang;
    const ul = node.querySelector(".links");
    for (const l of s.links) {
      const li = document.createElement("li");
      const la = document.createElement("a");
      la.href = l.url; la.target = "_blank"; la.rel = "noopener noreferrer";
      la.textContent = l.source;
      la.title = l.title;
      const lang = document.createElement("span");
      lang.className = "lang"; lang.textContent = l.lang;
      li.append(la, lang);
      ul.append(li);
    }

    const readBtn = node.querySelector(".act-read");
    const skipBtn = node.querySelector(".act-skip");
    if (view === "history") {
      readBtn.textContent = "Back to feed";
      readBtn.title = "Put this story back in the feed";
      skipBtn.hidden = true;
      readBtn.addEventListener("click", () => leave(node, s.id, "undo", "Moved back to the feed."));
    } else {
      readBtn.addEventListener("click", () => leave(node, s.id, "read", "Marked as read."));
      skipBtn.addEventListener("click", () => leave(node, s.id, "dismiss", "Hidden. Future updates will learn from this."));
    }
    // opening the article does not mark it read; Karl decides with the checkmark
    return node;
  }

  function leave(node, id, action, msg) {
    node.classList.add("leaving");
    const finish = async () => {
      await act(id, action);
      lastAction = action === "undo" ? null : id;
      setStatus(msg, lastAction);
      render();
    };
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) finish();
    else setTimeout(finish, 220);
  }

  function render() {
    $("view-feed").hidden = view !== "feed";
    $("view-history").hidden = view !== "history";
    for (const v of ["feed", "history"]) $(`tab-${v}`).setAttribute("aria-pressed", String(view === v));

    if (view === "feed") {
      const list = feedStories();
      const ol = $("feed");
      ol.replaceChildren(...list.map((s, i) => card(s, i + 1)));
      $("feed-empty").hidden = list.length > 0;
    } else if (view === "history") {
      const map = histMode === "read" ? state.read : state.dismissed;
      const list = Object.entries(map)
        .filter(([id]) => byId.has(id))
        .sort((a, b) => b[1].localeCompare(a[1]))
        .map(([id]) => byId.get(id));
      $("history").replaceChildren(...list.map((s) => card(s, null)));
      $("history-empty").hidden = list.length > 0;
      $("hist-read").setAttribute("aria-pressed", String(histMode === "read"));
      $("hist-skipped").setAttribute("aria-pressed", String(histMode !== "read"));
    }
  }

  function describeUpdate(generatedAt) {
    if (!generatedAt) return "";
    const d = new Date(generatedAt);
    const fmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    const unread = stories.filter((s) => !isDone(s.id)).length;
    return `Updated ${fmt.format(d)} · ${unread} unread in the pool, showing the top ${Math.min(TOP_N, unread)}.`;
  }

  // ---- wiring ------------------------------------------------------------
  for (const v of ["feed", "history"]) {
    $(`tab-${v}`).addEventListener("click", () => { view = v; setStatus(""); render(); });
  }
  $("hist-read").addEventListener("click", () => { histMode = "read"; render(); });
  $("hist-skipped").addEventListener("click", () => { histMode = "dismissed"; render(); });
  async function boot() {
    try {
      const res = await fetch("data/stories.json", { cache: "no-store" });
      const data = await res.json();
      stories = data.stories || [];
      byId = new Map(stories.map((s) => [s.id, s]));
      await pullState();
      if (synced) setStatus(describeUpdate(data.generated_at));
    } catch {
      setStatus("Could not load stories. The first update may not have run yet.");
    }
    render();
  }
  boot();
})();
