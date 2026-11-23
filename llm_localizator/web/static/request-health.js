/* Request health + Profile panel (Wave 0). Always tracks /api/*; UI when profile on. */
(function (global) {
  "use strict";

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  var CAP = 80;
  var STALL_MS = 10000;
  var TIMEOUT_MS = 60000;
  var entries = [];
  var seq = 0;
  var nativeFetch = global.fetch.bind(global);
  // Recording can stay on while the floating panel stays closed until Open.
  var panelOpen = false;

  function profileOn() {
    try {
      if (global.localStorage && global.localStorage.getItem("llmProfile") === "1") return true;
    } catch (err) { /* private */ }
    try {
      return /(?:^|[?&])profile=1(?:&|$)/.test(location.search);
    } catch (err2) {
      return false;
    }
  }

  function setProfile(on) {
    try {
      if (on) global.localStorage.setItem("llmProfile", "1");
      else global.localStorage.removeItem("llmProfile");
    } catch (err) { /* ignore */ }
    if (!on) panelOpen = false;
    syncProfileChrome();
    renderPanel();
  }

  function openPanel() {
    panelOpen = true;
    if (!profileOn()) setProfile(true);
    else renderPanel();
  }

  function closePanel() {
    panelOpen = false;
    var panel = document.getElementById("llm-profile-panel");
    if (panel) panel.hidden = true;
  }

  function snapshot() {
    return entries.slice();
  }

  function clientMs(entry) {
    if (entry.durationMs != null) return entry.durationMs;
    if (entry.state === "pending" || entry.state === "stalled") {
      return Date.now() - entry.startedAt;
    }
    return -1;
  }

  /** Slowest client time first; in-flight last among equals by start time. */
  function sortedByClient() {
    return entries.slice().sort(function (a, b) {
      var da = clientMs(a);
      var db = clientMs(b);
      if (db !== da) return db - da;
      return (b.startedAt || 0) - (a.startedAt || 0);
    });
  }

  function exportPayload() {
    var rows = sortedByClient();
    return {
      exportedAt: new Date().toISOString(),
      page: location.pathname + location.search,
      profileEnabled: profileOn(),
      counts: counts(),
      sort: "clientMs_desc",
      entries: rows.map(function (e) {
        return {
          id: e.id,
          method: e.method,
          url: e.url,
          path: e.path,
          state: e.state,
          status: e.status,
          clientMs: e.durationMs != null ? e.durationMs : null,
          serverMs: e.serverMs != null ? e.serverMs : null,
          responseBytes: e.responseBytes,
          spans: e.spans || null,
          error: e.error || null,
          page: e.page || null,
          startedAt: e.startedAt ? new Date(e.startedAt).toISOString() : null,
          endedAt: e.endedAt ? new Date(e.endedAt).toISOString() : null,
        };
      }),
    };
  }

  function downloadExport() {
    var payload = exportPayload();
    var blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
      type: "application/json",
    });
    var stamp = payload.exportedAt.replace(/[:.]/g, "-").slice(0, 19);
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "llm-profile-" + stamp + ".json";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function push(entry) {
    entries.push(entry);
    while (entries.length > CAP) entries.shift();
    if (profileOn() || entry.state === "stalled" || entry.state === "error" || entry.state === "aborted") {
      renderPanel();
    }
  }

  function parseServerTiming(header) {
    var out = {};
    if (!header) return out;
    String(header).split(",").forEach(function (part) {
      var bits = part.trim().split(";");
      var name = (bits[0] || "").trim();
      if (!name) return;
      bits.slice(1).forEach(function (kv) {
        var pair = kv.trim().split("=");
        if (pair[0] === "dur" && pair[1] != null) {
          out[name] = parseFloat(pair[1]);
        }
      });
    });
    return out;
  }

  function pathOf(input) {
    try {
      var u = typeof input === "string" ? new URL(input, location.href) : new URL(input.url, location.href);
      return u.pathname + (u.search || "");
    } catch (err) {
      return String(input);
    }
  }

  function isApi(path) {
    return path.indexOf("/api/") === 0 || path.indexOf("/api?") === 0;
  }

  function withProfileQuery(url) {
    if (!profileOn()) return url;
    try {
      var u = new URL(url, location.href);
      if (u.pathname.indexOf("/api/") !== 0) return url;
      if (!u.searchParams.has("profile")) u.searchParams.set("profile", "1");
      return u.pathname + u.search + u.hash;
    } catch (err) {
      return url;
    }
  }

  global.fetch = function (input, init) {
    init = init || {};
    var path = pathOf(input);
    var track = isApi(path);
    if (!track) return nativeFetch(input, init);

    var method = (init.method || "GET").toUpperCase();
    var id = ++seq;
    var started = Date.now();
    var entry = {
      id: id,
      method: method,
      url: path.split("?")[0],
      path: path,
      startedAt: started,
      endedAt: null,
      durationMs: null,
      state: "pending",
      status: null,
      error: null,
      responseBytes: null,
      spans: null,
      page: (document.getElementById("page") || {}).dataset
        ? document.getElementById("page").dataset.page
        : null,
    };
    push(entry);

    var controller = init.signal ? null : new AbortController();
    if (controller) {
      init = Object.assign({}, init, { signal: controller.signal });
    }
    var stallTimer = setTimeout(function () {
      if (entry.state === "pending") {
        entry.state = "stalled";
        try { console.warn("[llm] stalled", entry.method, entry.url, Date.now() - started, "ms"); } catch (e) {}
        renderPanel();
      }
    }, STALL_MS);
    var timeoutTimer = setTimeout(function () {
      if (entry.state === "pending" || entry.state === "stalled") {
        if (controller) controller.abort();
      }
    }, TIMEOUT_MS);

    var url = typeof input === "string" ? withProfileQuery(input) : input;
    if (typeof input === "string" && profileOn() && method !== "GET") {
      try {
        var body = init.body ? JSON.parse(init.body) : {};
        if (body && typeof body === "object" && body.profile == null) {
          body.profile = true;
          init = Object.assign({}, init, { body: JSON.stringify(body) });
        }
      } catch (err) { /* non-json body */ }
    }

    return nativeFetch(url, init).then(function (response) {
      clearTimeout(stallTimer);
      clearTimeout(timeoutTimer);
      entry.endedAt = Date.now();
      entry.durationMs = entry.endedAt - started;
      entry.status = response.status;
      entry.state = response.ok ? "ok" : "error";
      if (!response.ok) entry.error = "HTTP " + response.status;
      var st = response.headers.get("Server-Timing");
      entry.spans = parseServerTiming(st);
      var cl = response.headers.get("Content-Length");
      if (cl) entry.responseBytes = parseInt(cl, 10) || null;
      var clone = response.clone();
      clone.json().then(function (data) {
        if (data && data._timing) {
          entry.spans = data._timing.spans || entry.spans;
          if (data._timing.responseBytes != null) entry.responseBytes = data._timing.responseBytes;
          if (data._timing.totalMs != null) entry.serverMs = data._timing.totalMs;
        }
        renderPanel();
      }).catch(function () {});
      renderPanel();
      return response;
    }).catch(function (err) {
      clearTimeout(stallTimer);
      clearTimeout(timeoutTimer);
      entry.endedAt = Date.now();
      entry.durationMs = entry.endedAt - started;
      if (err && err.name === "AbortError") {
        entry.state = "aborted";
        entry.error = "timeout";
      } else {
        entry.state = "error";
        entry.error = String(err && err.message ? err.message : err);
      }
      try { console.warn("[llm] request", entry.state, entry.method, entry.url, entry.error); } catch (e) {}
      renderPanel();
      throw err;
    });
  };

  function counts() {
    var c = { pending: 0, stalled: 0, failed: 0, ok: 0, aborted: 0 };
    entries.forEach(function (e) {
      if (e.state === "pending") c.pending++;
      else if (e.state === "stalled") c.stalled++;
      else if (e.state === "error") c.failed++;
      else if (e.state === "aborted") c.aborted++;
      else if (e.state === "ok") c.ok++;
    });
    return c;
  }

  function ensurePanel() {
    var el = document.getElementById("llm-profile-panel");
    if (el) return el;
    el = document.createElement("div");
    el.id = "llm-profile-panel";
    el.className = "llm-profile-panel";
    el.hidden = true;
    document.body.appendChild(el);
    return el;
  }

  function textCell(text, className) {
    var td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = text == null ? "" : String(text);
    return td;
  }

  function renderPanel() {
    var on = profileOn();
    var c = counts();
    var badge = document.getElementById("llm-profile-badge");
    if (badge) {
      var n = c.stalled + c.failed + c.aborted + c.pending;
      badge.hidden = n === 0 && !on;
      badge.textContent = n ? String(n) : "·";
      badge.classList.toggle("is-alert", c.stalled + c.failed + c.aborted > 0);
    }
    var panel = ensurePanel();
    if (!panelOpen || !on) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    while (panel.firstChild) panel.removeChild(panel.firstChild);

    var head = document.createElement("div");
    head.className = "llm-profile-head";
    var title = document.createElement("strong");
    title.textContent = uiT("rh_profile", "Profile");
    head.appendChild(title);
    var summary = document.createElement("span");
    summary.textContent =
      uiT("rh_pending", "pending") + " " + c.pending + " · " + uiT("rh_stalled", "stalled") + " " + c.stalled +
      " · " + uiT("rh_failed", "failed") + " " + c.failed + " · " + uiT("rh_sorted_client", "sorted by client ↓");
    head.appendChild(summary);
    function linkBtn(id, label, onClick) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-link";
      btn.id = id;
      btn.textContent = label;
      btn.onclick = onClick;
      head.appendChild(btn);
    }
    linkBtn("llm-profile-export", uiT("rh_export", "Export"), function () { downloadExport(); });
    linkBtn("llm-profile-clear", uiT("rh_clear", "Clear"), function () { entries = []; renderPanel(); });
    linkBtn("llm-profile-close", uiT("op_close", "Close"), function () { closePanel(); });
    panel.appendChild(head);

    var body = document.createElement("div");
    body.className = "llm-profile-body";
    var table = document.createElement("table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    [
      uiT("rh_th_method", "Method"),
      uiT("rh_th_path", "Path"),
      uiT("rh_th_state", "State"),
      uiT("rh_th_client", "Client ↓"),
      uiT("rh_th_size", "Size"),
      uiT("rh_th_spans", "Spans / error"),
    ].forEach(function (label) {
      var th = document.createElement("th");
      th.textContent = label;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    sortedByClient().forEach(function (e) {
      var size = e.responseBytes != null ? (Math.round(e.responseBytes / 1024) + " KB") : "—";
      var ms = clientMs(e);
      var dur = e.durationMs != null ? e.durationMs + " ms" : (ms >= 0 ? ms + " ms…" : "—");
      var spanHint = "";
      if (e.spans) {
        var names = Object.keys(e.spans).filter(function (k) { return k !== "total"; }).slice(0, 4);
        spanHint = names.map(function (k) { return k + "=" + e.spans[k]; }).join(" ");
      }
      var tr = document.createElement("tr");
      tr.className = "st-" + String(e.state || "");
      tr.appendChild(textCell(e.method));
      var pathTd = textCell(e.url);
      pathTd.title = e.path == null ? "" : String(e.path);
      tr.appendChild(pathTd);
      tr.appendChild(textCell(e.state));
      tr.appendChild(textCell(dur, "client-ms"));
      tr.appendChild(textCell(size));
      tr.appendChild(textCell(spanHint || e.error || "", "spans"));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    body.appendChild(table);
    panel.appendChild(body);
  }

  var ICON_PROFILE =
    '<svg class="ui-chrome-icon" viewBox="0 0 16 16" aria-hidden="true">' +
    '<path d="M2.5 11.5l2.8-3.2 2.2 1.8 3.2-4.1 2.8 3.2" fill="none" ' +
    'stroke="currentColor" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M2 13.25h12" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round"/>' +
    "</svg>";

  function syncProfileChrome(btn) {
    if (!btn) btn = document.getElementById("llm-profile-toggle");
    if (!btn) return;
    var on = profileOn();
    btn.classList.toggle("is-active", on);
    btn.title = on ? uiT("rh_profiler_on", "Profiler on") : uiT("rh_profiler_off", "Profiler off");
  }

  function injectToggle() {
    if (document.getElementById("llm-profile-toggle")) {
      syncProfileChrome();
      renderPanel();
      return;
    }
    if (!global.LLMChrome || !document.getElementById("lang-sel-mount")) return;
    global.LLMChrome.addControl({
      id: "llm-profile-toggle",
      label: uiT("rh_profiler", "Request profiler"),
      order: 4,
      btnClass: profileOn() ? "is-active" : "",
      icon: ICON_PROFILE + '<span id="llm-profile-badge" class="llm-profile-badge" hidden></span>',
      build: function (pop, btn) {
        function pick(value) {
          if (value === "off") {
            setProfile(false);
            syncProfileChrome(btn);
            return;
          }
          // Record on without forcing the panel; Open panel does that.
          setProfile(true);
          syncProfileChrome(btn);
        }
        global.LLMChrome.fillMenu(
          pop,
          [
            { value: "on", label: uiT("rh_record_timing", "Record timing") },
            { value: "off", label: uiT("rh_profiler_off_opt", "Off") },
          ],
          profileOn() ? "on" : "off",
          pick
        );
        var openBtn = document.createElement("button");
        openBtn.type = "button";
        openBtn.className = "ui-chrome-option";
        openBtn.setAttribute("role", "menuitem");
        openBtn.textContent = uiT("rh_open_panel", "Open panel");
        openBtn.addEventListener("click", function () {
          openPanel();
          syncProfileChrome(btn);
          global.LLMChrome.closeAll();
        });
        pop.appendChild(openBtn);
      },
      onOpen: function (pop) {
        global.LLMChrome.markSelected(pop, profileOn() ? "on" : "off");
        syncProfileChrome();
      },
    });
    syncProfileChrome();
    // Badge only on load — do not auto-pop the panel when recording was left on.
    renderPanel();
  }

  function bootToggle() {
    var ready = (global.uiLocale && typeof global.uiLocale.whenReady === "function")
      ? global.uiLocale.whenReady()
      : Promise.resolve();
    ready.then(function () {
      injectToggle();
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootToggle);
  } else {
    bootToggle();
  }
  document.addEventListener("llm-ui-locale", function () {
    var btn = document.getElementById("llm-profile-toggle");
    if (btn) {
      btn.setAttribute("aria-label", uiT("rh_profiler", "Request profiler"));
      syncProfileChrome(btn);
    }
  });

  global.LLMProfile = {
    snapshot: snapshot,
    exportPayload: exportPayload,
    downloadExport: downloadExport,
    counts: counts,
    setEnabled: setProfile,
    enabled: profileOn,
    open: openPanel,
    close: closePanel,
    render: renderPanel,
  };
  global.__LLM_REQUESTS = {
    snapshot: snapshot,
    exportPayload: exportPayload,
    counts: counts,
  };
})(window);
