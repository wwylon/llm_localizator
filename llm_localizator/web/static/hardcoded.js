(function () {
  // Hardcoded-string findings (W5): hits of the stored scan, grouped by file, with a tier filter, an explain drill-down
  // (explain-scan op) and accept / ignore through scan-decide. Loading the page never scans; "Run a scan" does a
  // static scan (agent-hardcoded without --llm).
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "hardcoded" || !root) return;

  var TIERS = ["high", "medium", "low", "all"];
  var state = { hits: [], tier: "high", showDecided: false, data: null };

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function project() {
    var select = document.getElementById("project-select");
    return select && select.value ? select.value : "";
  }

  function apiGet(path, params) {
    if (window.LLMApi && LLMApi.apiGet) return LLMApi.apiGet(path, params);
    var qs = new URLSearchParams(params || {}).toString();
    return fetch(path + (qs ? "?" + qs : ""), { credentials: "same-origin" }).then(function (r) { return r.json(); });
  }

  function opPost(command, body) {
    body.project = project();
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost("/api/ops/" + command, body);
    return fetch("/api/ops/" + command, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function button(label, cls, handler) {
    var btn = el("button", "btn " + (cls || ""), label);
    btn.type = "button";
    btn.addEventListener("click", handler);
    return btn;
  }

  function tierLabel(tier) {
    return ({
      high: uiT("hc_tier_high", "High"), medium: uiT("hc_tier_medium", "Medium"),
      low: uiT("hc_tier_low", "Low"), all: uiT("hc_tier_all", "All"),
    })[tier] || tier;
  }

  function decisionLabel(decision) {
    return ({
      accepted: uiT("dash_scan_accepted", "Accepted"), applied: uiT("dash_scan_applied", "Applied"),
      ignored: uiT("dash_scan_ignored", "Ignored"),
    })[decision] || decision;
  }

  function runScan(btn) {
    btn.disabled = true;
    btn.textContent = uiT("dash_scan_running", "Scanning…");
    opPost("agent-hardcoded", { format: "json" }).then(function (res) {
      if (!res || res.ok === false) {
        btn.disabled = false;
        btn.textContent = (res && (res.error || res.summary)) || uiT("hc_scan_failed", "Scan failed");
        return;
      }
      load();
    }).catch(function (err) {
      btn.disabled = false;
      btn.textContent = String(err);
    });
  }

  function decide(action, chosen, status) {
    var ids = chosen.map(function (h) { return h.id; });
    if (!ids.length) return;
    opPost("scan-decide", { action: action, ids: ids }).then(function (res) {
      status.textContent = (res && (res.summary || res.error)) || "";
      if (!res || !res.ok) return;
      var applied = res.data && res.data.applied ? "applied" : "accepted";
      chosen.forEach(function (h) {
        h.decision = action === "reset" ? null : (action === "accept" ? applied : "ignored");
      });
      paint();
    }).catch(function (err) { status.textContent = String(err); });
  }

  function explain(hit, host, btn) {
    if (host.childNodes.length) {
      host.replaceChildren();
      return;
    }
    btn.disabled = true;
    opPost("explain-scan", { file: hit.file, line: String(hit.line) }).then(function (res) {
      btn.disabled = false;
      var pre = el("pre", "settings-mono hc-explain-out");
      pre.textContent = [(res && (res.summary || res.error)) || ""].concat((res && res.lines) || []).join("\n");
      host.replaceChildren(pre);
    }).catch(function (err) {
      btn.disabled = false;
      host.replaceChildren(el("pre", "settings-mono hc-explain-out", String(err)));
    });
  }

  function shownHits() {
    return state.hits.filter(function (h) {
      if (state.tier !== "all" && (h.confidence || "medium") !== state.tier) return false;
      if (!state.showDecided && h.decision) return false;
      return true;
    });
  }

  function filterBar(status) {
    var bar = el("div", "settings-actions hc-filter");
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", uiT("hc_tier_label", "Confidence"));
    TIERS.forEach(function (tier) {
      var n = tier === "all" ? state.hits.length
        : state.hits.filter(function (h) { return (h.confidence || "medium") === tier; }).length;
      var btn = button(tierLabel(tier) + " (" + n + ")", state.tier === tier ? "btn-primary" : "", function () {
        state.tier = tier;
        paint();
      });
      btn.dataset.tier = tier;
      btn.setAttribute("aria-pressed", state.tier === tier ? "true" : "false");
      bar.appendChild(btn);
    });
    var lab = el("label", "op-check hc-show-decided");
    var box = el("input", "");
    box.type = "checkbox";
    box.checked = state.showDecided;
    box.addEventListener("change", function () { state.showDecided = box.checked; paint(); });
    lab.appendChild(box);
    lab.appendChild(document.createTextNode(" " + uiT("hc_show_decided", "Show decided")));
    bar.appendChild(lab);
    var rescan = button(uiT("dash_scan_rerun", "Scan again"), "", function () { runScan(rescan); });
    bar.appendChild(rescan);
    bar.appendChild(status);
    return bar;
  }

  function fileTable(file, hits, status) {
    var card = el("div", "settings-card hc-file");
    card.dataset.file = file;
    var head = el("div", "settings-card-head settings-card-title-row");
    head.appendChild(el("div", "section-label settings-mono", file));
    head.appendChild(el("span", "settings-badge", String(hits.length)));
    var pending = hits.filter(function (h) { return !h.decision; });
    if (pending.length > 1) {
      head.appendChild(button(uiT("hc_accept_file", "Accept all in file"), "", function () {
        decide("accept", pending, status);
      }));
      head.appendChild(button(uiT("hc_ignore_file", "Ignore all in file"), "", function () {
        decide("ignore", pending, status);
      }));
    }
    card.appendChild(head);
    var table = el("table", "settings-table hc-table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    [uiT("hc_col_line", "Line"), uiT("hc_col_text", "Text"), uiT("hc_col_tier", "Confidence"),
      uiT("hc_col_decision", "Decision"), ""].forEach(function (label) { hr.appendChild(el("th", "", label)); });
    thead.appendChild(hr);
    table.appendChild(thead);
    var body = document.createElement("tbody");
    hits.forEach(function (h) {
      var tr = document.createElement("tr");
      tr.className = "hc-row" + (h.decision === "ignored" ? " hit-ignored" : "");
      tr.dataset.id = h.id;
      tr.appendChild(el("td", "settings-mono", String(h.line)));
      var text = el("td", "hc-text");
      text.appendChild(el("span", "", JSON.stringify(h.text)));
      if (h.existing_key) {
        text.appendChild(el("span", "field-hint", " " + uiT("op_reuse_key", "reuse {key}").replace("{key}", h.existing_key)));
      }
      tr.appendChild(text);
      var tier = el("td", "");
      tier.appendChild(el("span", "settings-badge hc-tier-" + (h.confidence || "medium"), tierLabel(h.confidence || "medium")));
      tr.appendChild(tier);
      tr.appendChild(el("td", "", h.decision ? decisionLabel(h.decision) : "—"));
      var acts = el("td", "hc-actions");
      var detail = document.createElement("tr");
      detail.className = "hc-explain";
      var detailCell = el("td", "");
      detailCell.colSpan = 5;
      detail.appendChild(detailCell);
      var why = button(uiT("hc_explain", "Explain"), "hc-explain-btn", function () { explain(h, detailCell, why); });
      acts.appendChild(why);
      if (!h.decision) {
        acts.appendChild(button(uiT("hc_accept", "Accept"), "", function () { decide("accept", [h], status); }));
        acts.appendChild(button(uiT("hc_ignore", "Ignore"), "", function () { decide("ignore", [h], status); }));
      } else if (h.decision !== "applied") {
        acts.appendChild(button(uiT("hc_reset", "Undo"), "", function () { decide("reset", [h], status); }));
      }
      tr.appendChild(acts);
      body.appendChild(tr);
      body.appendChild(detail);
    });
    table.appendChild(body);
    card.appendChild(table);
    return card;
  }

  function emptyState() {
    var card = el("div", "settings-card hc-empty");
    card.appendChild(el("p", "empty-state", uiT("dash_scan_none", "No scan yet.")));
    card.appendChild(el("p", "field-hint", uiT(
      "dash_scan_none_hint",
      "A scan finds user-visible text in the source that is not in the catalogue yet. It reads files only.")));
    var btn = button(uiT("dash_scan_run", "Run a scan"), "btn-primary hc-scan-run", function () { runScan(btn); });
    card.appendChild(btn);
    return card;
  }

  function paint() {
    root.replaceChildren();
    var data = state.data || {};
    if (!data.cached) {
      root.appendChild(emptyState());
      return;
    }
    var status = el("span", "field-hint hc-status", "");
    var summary = el("p", "field-hint hc-summary", uiT("hc_summary", "{n} findings in {files} files scanned")
      .replace("{n}", String(state.hits.length)).replace("{files}", String(data.filesScanned || 0)) +
      (data.stale ? " · " + uiT("hc_stale", "source changed since the last scan") : ""));
    root.appendChild(summary);
    root.appendChild(filterBar(status));
    var shown = shownHits();
    if (!shown.length) {
      root.appendChild(el("p", "empty-state", uiT("hc_none_in_tier", "Nothing to decide in this filter.")));
      return;
    }
    var byFile = {};
    var order = [];
    shown.forEach(function (h) {
      if (!byFile[h.file]) { byFile[h.file] = []; order.push(h.file); }
      byFile[h.file].push(h);
    });
    order.forEach(function (file) { root.appendChild(fileTable(file, byFile[file], status)); });
  }

  function load() {
    return apiGet("/api/scan/hits", { project: project() }).then(function (data) {
      if (!data || data.ok === false) {
        root.replaceChildren(el("p", "empty-state", (data && data.error) || uiT("hc_load_failed", "Could not load findings.")));
        return;
      }
      state.data = data;
      state.hits = data.hits || [];
      if (state.tier !== "all" && state.hits.length &&
          !state.hits.some(function (h) { return (h.confidence || "medium") === state.tier; })) {
        state.tier = "all";
      }
      paint();
    }).catch(function () {
      root.replaceChildren(el("p", "empty-state", uiT("hc_load_failed", "Could not load findings.")));
    });
  }

  var select = document.getElementById("project-select");
  if (select) select.addEventListener("change", load);
  load();
})();
