(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "usage" || !root) return;

  var SVG_NS = "http://www.w3.org/2000/svg";
  var PERIOD_KEY = "llm-usage-period";
  var PERIODS = ["month", "last_month", "90d", "all"];
  var periodSelect = document.getElementById("usage-period");
  var exportBtn = document.getElementById("usage-export-btn");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function svgEl(tag, attrs, text) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (name) { node.setAttribute(name, String(attrs[name])); });
    if (text != null) node.textContent = text;
    return node;
  }

  function t(key, fallback, vars) {
    var loc = window.uiLocale;
    var value = loc && loc.t ? loc.t(key) : key;
    var text = value && value !== key ? value : fallback;
    Object.keys(vars || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(vars[name]));
    });
    return text;
  }

  function project() {
    var select = document.getElementById("project-select");
    return select && select.value ? select.value : "";
  }

  function num(value) { return Number(value || 0).toLocaleString(); }
  function dash(value) { return value == null ? "—" : num(value); }
  function usd(value) {
    if (value == null) return "—";
    var v = Number(value);
    return "$" + v.toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: v !== 0 && Math.abs(v) < 0.01 ? 4 : 2,
    });
  }
  function shortDate(iso) {
    var d = new Date(String(iso).slice(0, 10) + "T00:00:00");
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function savedPeriod() {
    try {
      var v = window.localStorage.getItem(PERIOD_KEY);
      return PERIODS.indexOf(v) >= 0 ? v : "month";
    } catch (e) { return "month"; }
  }

  function savePeriod(value) {
    try { window.localStorage.setItem(PERIOD_KEY, value); } catch (e) { /* storage may be blocked */ }
  }

  function currentPeriod() {
    return periodSelect && PERIODS.indexOf(periodSelect.value) >= 0 ? periodSelect.value : "month";
  }

  function query(extra) {
    var q = new URLSearchParams();
    if (project()) q.set("project", project());
    Object.keys(extra || {}).forEach(function (key) { q.set(key, extra[key]); });
    var text = q.toString();
    return text ? "?" + text : "";
  }

  function panel(parent, label, helpKey, note) {
    var wrap = el("div", "pg-panel");
    var head = el("div", "pg-panel-head");
    head.appendChild(el("div", "pg-label", label));
    var side = el("div", "us-head-side");
    if (note) side.appendChild(el("div", "pg-note", note));
    if (helpKey && window.LLMHelp) side.appendChild(window.LLMHelp.helpBtn(helpKey));
    head.appendChild(side);
    wrap.appendChild(head);
    parent.appendChild(wrap);
    return wrap;
  }

  function headRow(cols) {
    var thead = el("thead");
    var tr = el("tr");
    cols.forEach(function (col) { tr.appendChild(el("th", col.right ? "r" : "", col.text)); });
    thead.appendChild(tr);
    return thead;
  }

  function cell(row, text, className) {
    var td = el("td", className || "", text);
    row.appendChild(td);
    return td;
  }

  function header() {
    var sub = document.getElementById("usage-sub");
    if (sub) {
      sub.textContent = t("usage_subtitle", "External LLM API usage and cost estimates");
      if (window.LLMHelp && !sub.parentNode.querySelector(".help-trigger")) {
        sub.parentNode.appendChild(window.LLMHelp.helpBtn("usage:general"));
      }
    }
  }

  function localizeControls() {
    if (periodSelect) {
      var labels = {
        month: t("usage_period_month", "This month"),
        last_month: t("usage_period_last_month", "Last month"),
        "90d": t("usage_period_90d", "Last 90 days"),
        all: t("usage_period_all", "All time"),
      };
      Array.prototype.forEach.call(periodSelect.options, function (opt) {
        if (labels[opt.value]) opt.textContent = labels[opt.value];
      });
      periodSelect.setAttribute("aria-label", t("usage_period_label", "Period"));
    }
    if (exportBtn) exportBtn.textContent = t("usage_export", "↓ Export CSV");
  }

  // ---- cards ------------------------------------------------------------------

  function summaryCards(data) {
    var c = data.cards || {};
    var grid = el("div", "pg-cards");
    function card(label, value, sub, color) {
      var node = el("div", "pg-card");
      node.appendChild(el("div", "pg-label", label));
      var big = el("div", "pg-value", value);
      if (color) big.style.color = color;
      node.appendChild(big);
      node.appendChild(el("div", "pg-subline", sub));
      grid.appendChild(node);
    }
    var delta = Number(c.deltaUsd || 0);
    var deltaText = c.previousUsd > 0 || c.cloudUsd > 0
      ? t("usage_card_delta", "{d} vs previous period", { d: (delta > 0 ? "+" : delta < 0 ? "−" : "") + usd(Math.abs(delta)) })
      : t("usage_card_no_cloud", "no cloud spend");
    card(t("usage_card_cost", "Cloud cost"), usd(c.cloudUsd), deltaText, "var(--progress-llm)");
    var over = data.budget && data.budget.projectedOverCap;
    card(
      t("usage_card_projected", "Projected month-end"),
      c.projectedUsd == null ? "—" : usd(c.projectedUsd),
      c.projectedUsd == null
        ? t("usage_card_projected_na", "needs a month in progress with spend")
        : (over ? t("usage_card_projected_over", "over the monthly cap") : t("usage_card_projected_sub", "at the current rate")),
      over ? "var(--progress-threshold)" : "var(--progress-asap-text)"
    );
    card(t("usage_card_tokens", "Tokens"), dash(c.tokens), t("usage_card_tokens_sub", "input + output"));
    card(
      t("usage_card_per1k", "Avg cost / 1k strings"),
      c.usdPer1kStrings == null ? "—" : usd(c.usdPer1kStrings),
      t("usage_card_per1k_sub", "billed locales only")
    );
    return grid;
  }

  // ---- budget strip -----------------------------------------------------------

  function budgetStrip(data) {
    var b = data.budget || {};
    var box = el("div", "pg-panel pg-panel-pad us-budget");
    var head = el("div", "us-budget-head");
    head.appendChild(el("div", "pg-label", t("usage_budget_title", "Monthly budget")));
    // The cap is the operator's own setting (ADR-123): no web form writes it, so say where it lives instead of
    // linking to a page that has no budget field.
    head.appendChild(el("span", "field-hint us-budget-where",
      t("usage_budget_where", "Set in .llm-localize.toml: [budget] monthly_usd and [privacy] allow_cloud")));
    box.appendChild(head);
    if (b.localOnly) {
      box.appendChild(el("p", "us-budget-off", t("usage_budget_local_only", "Local-only mode is on ([privacy] local_only): cloud providers, remote endpoints and webhooks are blocked. Nothing leaves this machine.")));
      return box;
    }
    if (!(b.capUsd > 0) || !b.allowCloud) {
      var why = !(b.capUsd > 0)
        ? t("usage_budget_off_cap", "No monthly cap is set, so cloud providers are not used. Local runs cost $0.")
        : t("usage_budget_off_privacy", "A cap is set but cloud is not allowed ([privacy] allow_cloud). Runs stay local.");
      box.appendChild(el("p", "us-budget-off", why));
      return box;
    }
    var pct = Math.min(100, (b.spentUsd / b.capUsd) * 100);
    var meter = el("div", "pg-bar us-meter");
    var fill = el("i", pct >= 100 ? "us-fill-over" : pct >= 80 ? "us-fill-warn" : "pg-llm");
    fill.style.width = pct + "%";
    meter.appendChild(fill);
    box.appendChild(meter);
    box.appendChild(el("div", "pg-subline", t(
      "usage_budget_line", "{spent} of {cap} spent · {left} left · mode {mode}",
      { spent: usd(b.spentUsd), cap: usd(b.capUsd), left: usd(b.remainingUsd), mode: b.mode }
    )));
    if (pct >= 100) {
      box.appendChild(el("div", "us-warn", t("usage_budget_reached", "Cap reached – runs fall back to the local provider.")));
    }
    return box;
  }

  // ---- daily chart ------------------------------------------------------------

  function niceMax(value) {
    if (value <= 0) return 1;
    var mag = Math.pow(10, Math.floor(Math.log(value) / Math.LN10));
    var steps = [1, 2, 4, 5, 8, 10];
    for (var i = 0; i < steps.length; i++) if (value <= steps[i] * mag) return steps[i] * mag;
    return 10 * mag;
  }

  function dailyChart(parent, daily) {
    var total = daily.reduce(function (s, d) { return s + d.usd; }, 0);
    if (!daily.length || total <= 0) {
      parent.appendChild(el("p", "pg-empty", t("usage_chart_empty", "No cloud spend in this period.")));
      return;
    }
    var PL = 40, PR = 670, PT = 10, PB = 130;
    var max = niceMax(Math.max.apply(null, daily.map(function (d) { return d.usd; })));
    var svg = svgEl("svg", { viewBox: "0 0 680 150", "class": "pg-chart", role: "img" });
    [4, 3, 2, 1, 0].forEach(function (k, i) {
      var y = PT + ((PB - PT) * i) / 4;
      svg.appendChild(svgEl("line", { x1: PL, y1: y, x2: PR, y2: y, "class": "g" }));
      svg.appendChild(svgEl("text", { x: PL - 5, y: y + 3, "text-anchor": "end" }, usd((max * k) / 4)));
    });
    var slot = (PR - PL) / daily.length;
    var bar = Math.max(2, slot * 0.7);
    daily.forEach(function (d, i) {
      var h = ((PB - PT) * d.usd) / max;
      var rect = svgEl("rect", {
        x: (PL + slot * i + (slot - bar) / 2).toFixed(1), y: (PB - h).toFixed(1),
        width: bar.toFixed(1), height: Math.max(0, h).toFixed(1), "class": "us-bar",
      });
      rect.appendChild(svgEl("title", {}, shortDate(d.date) + ": " + usd(d.usd)));
      svg.appendChild(rect);
    });
    [0, 0.25, 0.5, 0.75, 1].forEach(function (frac) {
      var idx = Math.round(frac * (daily.length - 1));
      svg.appendChild(svgEl("text", {
        x: PL + slot * idx + slot / 2, y: 143, "text-anchor": "middle",
      }, shortDate(daily[idx].date)));
    });
    parent.appendChild(svg);
  }

  // ---- providers --------------------------------------------------------------

  function providerPanel(parent, providers) {
    var wrap = panel(parent, t("usage_providers_title", "Cost by provider"), "usage:providers");
    var body = el("div", "us-providers");
    var cloud = providers.cloud || [];
    cloud.forEach(function (row) {
      var line = el("div", "us-prov-row");
      var name = el("div", "us-prov-name");
      name.appendChild(el("span", "pg-mono", row.model || row.kind));
      name.appendChild(el("span", "pg-faint", row.kind));
      line.appendChild(name);
      var bar = el("div", "pg-bar");
      var fill = el("i", "pg-localized");
      fill.style.width = Math.round((row.share || 0) * 100) + "%";
      bar.appendChild(fill);
      line.appendChild(bar);
      var figures = el("div", "us-prov-fig");
      figures.appendChild(el("strong", "pg-mono", usd(row.usd)));
      var detail = t("usage_prov_calls", "{n} calls", { n: num(row.calls) });
      if (row.tokens != null) detail += " · " + t("usage_prov_tokens", "{n} tokens", { n: num(row.tokens) });
      else if (row.characters != null) detail += " · " + t("usage_prov_chars", "{n} chars", { n: num(row.characters) });
      figures.appendChild(el("span", "pg-faint", detail));
      line.appendChild(figures);
      body.appendChild(line);
    });
    if (!cloud.length) body.appendChild(el("p", "pg-note", t("usage_prov_none", "No cloud calls in this period.")));
    var local = providers.local || {};
    var lrow = el("div", "us-prov-row us-prov-local");
    var lname = el("div", "us-prov-name");
    lname.appendChild(el("span", "", t("usage_prov_local", "Local models")));
    lname.appendChild(el("span", "pg-faint", (local.locales || []).join(", ")));
    lrow.appendChild(lname);
    var lbar = el("div", "pg-bar");
    var lfill = el("i", "pg-llm");
    lfill.style.width = "100%";
    lbar.appendChild(lfill);
    lrow.appendChild(lbar);
    var lfig = el("div", "us-prov-fig");
    lfig.appendChild(el("strong", "pg-mono", "$0.00"));
    lfig.appendChild(el("span", "pg-faint", t("usage_prov_strings", "{n} strings", { n: num(local.strings) })));
    lrow.appendChild(lfig);
    body.appendChild(lrow);
    wrap.appendChild(body);
  }

  // ---- locales ----------------------------------------------------------------

  function localesPanel(parent, rows) {
    var wrap = panel(parent, t("usage_locales_title", "Usage by locale"), "usage:locales");
    var table = el("table", "pg-table");
    table.appendChild(headRow([
      { text: t("usage_col_locale", "Locale") },
      { text: t("usage_col_provider", "Provider") },
      { text: t("usage_col_strings", "Strings"), right: true },
      { text: t("usage_col_in", "Input tokens"), right: true },
      { text: t("usage_col_out", "Output tokens"), right: true },
      { text: t("usage_col_cost", "Cost"), right: true },
      { text: t("usage_col_per_string", "Per string"), right: true },
    ]));
    var body = el("tbody");
    rows.forEach(function (row) {
      var tr = el("tr");
      var first = cell(tr, "");
      var link = el("a", "pg-loc", row.locale);
      link.href = "/app/editor?locale=" + encodeURIComponent(row.locale);
      first.appendChild(link);
      var prov = cell(tr, row.provider + " ");
      prov.appendChild(el("span", "us-tag " + (row.local ? "us-tag-local" : "us-tag-cloud"),
        row.local ? t("usage_tag_local", "local") : t("usage_tag_cloud", "cloud")));
      cell(tr, num(row.strings), "r pg-mono");
      cell(tr, dash(row.inputTokens), "r pg-mono");
      cell(tr, dash(row.outputTokens), "r pg-mono");
      cell(tr, usd(row.usd), "r pg-mono");
      cell(tr, row.usdPerString == null ? "—" : usd(row.usdPerString), "r pg-mono");
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);
  }

  // ---- estimate ---------------------------------------------------------------

  var NOTES = {
    own_hardware: ["usage_note_own", "Own hardware"],
    frozen: ["usage_note_frozen", "Frozen"],
    over_budget: ["usage_note_over", "⚠ Exceeds remaining budget – consider a local model"],
    no_price: ["usage_note_no_price", "No published price"],
    cloud_off: ["usage_note_cloud_off", "Cloud is off – runs stay local"],
  };

  function estimatePanel(parent, est) {
    var wrap = panel(parent, t("usage_estimate_title", "Estimated cost to complete remaining strings"), "usage:estimate");
    var table = el("table", "pg-table");
    table.appendChild(headRow([
      { text: t("usage_col_locale", "Locale") },
      { text: t("usage_col_remaining", "Remaining"), right: true },
      { text: t("usage_col_est_tokens", "Est. tokens"), right: true },
      { text: t("usage_col_est_cost", "Est. cost"), right: true },
      { text: t("usage_col_if_cloud", "If cloud"), right: true },
      { text: t("usage_col_note", "Note") },
    ]));
    var body = el("tbody");
    var anyUnpriced = false;
    (est.rows || []).forEach(function (row) {
      var tr = el("tr", row.note === "over_budget" ? "us-warn-row" : (row.frozen ? "pg-frozen" : ""));
      var first = cell(tr, "");
      first.appendChild(el("span", "pg-loc", row.locale));
      cell(tr, num(row.remaining), "r pg-mono");
      cell(tr, dash(row.tokens), "r pg-mono");
      var cost = row.priced ? usd(row.usd) : "—";
      if (!row.priced) anyUnpriced = true;
      cell(tr, cost, "r pg-mono");
      cell(tr, row.ifCloudUsd == null ? "—" : usd(row.ifCloudUsd), "r pg-mono us-ref");
      var note = cell(tr, "");
      var spec = NOTES[row.note];
      if (spec) note.appendChild(document.createTextNode(t(spec[0], spec[1])));
      if (row.note === "over_budget") {
        note.appendChild(document.createTextNode(" "));
        var evalLink = el("a", "us-link", t("usage_link_eval", "Model evaluation"));
        evalLink.href = "/app/model-eval";
        note.appendChild(evalLink);
      }
      if (row.remaining > 0 && !row.frozen) {
        note.appendChild(document.createTextNode(" "));
        var ops = el("a", "us-link", t("usage_link_estimate", "Estimate in Operations →"));
        ops.href = "/app/operations?command=estimate-cost&locales=" + encodeURIComponent(row.locale);
        note.appendChild(ops);
      }
      body.appendChild(tr);
    });
    var total = el("tr", "us-total");
    cell(total, t("usage_total", "Total"), "");
    cell(total, num(est.totalRemaining), "r pg-mono");
    cell(total, dash(est.totalTokens), "r pg-mono");
    cell(total, usd(est.totalUsd), "r pg-mono");
    cell(total, "");
    cell(total, "");
    body.appendChild(total);
    table.appendChild(body);
    wrap.appendChild(table);
    var foot = t("usage_estimate_foot",
      "Ceilings from the price tables. “If cloud” is a reference for local locales and is not part of the total.");
    if (anyUnpriced) foot += " " + t("usage_estimate_unpriced", "Unpriced models are excluded from the total.");
    wrap.appendChild(el("div", "pg-foot", foot));
  }

  // ---- recent runs ------------------------------------------------------------

  function runsPanel(parent, runs) {
    var wrap = panel(parent, t("usage_runs_title", "Recent runs"), null);
    if (!runs.length) {
      wrap.appendChild(el("div", "pg-empty", t("usage_runs_none", "No run records.")));
      return;
    }
    runs.slice(0, 20).forEach(function (run) {
      var line = el("div", "us-run-row");
      line.appendChild(el("span", "pg-mono", run.runId || ""));
      line.appendChild(el("span", "", run.command || ""));
      line.appendChild(el("span", "pg-loc", (run.locales || []).join(", ")));
      line.appendChild(el("span", "pg-mono us-run-cost", run.cost));
      wrap.appendChild(line);
    });
  }

  // ---- load -------------------------------------------------------------------

  function render(data) {
    root.textContent = "";
    var wrapper = el("div", "pg");
    wrapper.appendChild(summaryCards(data));
    wrapper.appendChild(budgetStrip(data));
    var grid = el("div", "us-grid");
    var chartWrap = panel(grid, t("usage_chart_title", "Daily cloud spend"), null,
      shortDate(data.period.from) + " – " + shortDate(data.period.to));
    var chartBody = el("div", "us-chart-body");
    dailyChart(chartBody, data.daily || []);
    chartWrap.appendChild(chartBody);
    providerPanel(grid, data.providers || {});
    wrapper.appendChild(grid);
    localesPanel(wrapper, data.locales || []);
    estimatePanel(wrapper, data.estimate || {});
    runsPanel(wrapper, data.runs || []);
    root.appendChild(wrapper);
  }

  var loadToken = 0;

  function load() {
    var token = ++loadToken;
    root.textContent = "";
    root.setAttribute("aria-busy", "true");
    var note = el("p", "pg-loading", t("usage_loading", "Loading…"));
    note.setAttribute("role", "status");
    root.appendChild(note);
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/usage", { period: currentPeriod(), project: (window.LLMApi && LLMApi.project) ? LLMApi.project() : "" })
      : Promise.reject(new Error("LLMApi missing"));
    get.then(function (data) {
        if (token !== loadToken) return;
        if (!data || data.ok === false) throw new Error((data && data.error) || "error");
        root.removeAttribute("aria-busy");
        render(data);
      })
      .catch(function () {
        if (token !== loadToken) return;
        root.removeAttribute("aria-busy");
        root.textContent = "";
        root.appendChild(el("p", "empty-state", t("usage_error", "Could not load usage.")));
      });
  }

  function exportCsv() {
    var period = currentPeriod();
    var headers = {};
    if (window.__LLM_TOKEN) headers["X-LLM-Token"] = window.__LLM_TOKEN;
    exportBtn.disabled = true;
    fetch("/api/usage/export" + query({ period: period }), { headers: headers, credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("export");
        return res.blob();
      })
      .then(function (blob) {
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        var name = project() || "project";
        link.download = "usage-" + name.replace(/[^A-Za-z0-9_-]/g, "_") + "-" + period + ".csv";
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
      })
      .catch(function () { window.alert(t("usage_export_error", "Export failed.")); })
      .then(function () { exportBtn.disabled = false; });
  }

  header();
  localizeControls();
  if (periodSelect) {
    periodSelect.value = savedPeriod();
    periodSelect.addEventListener("change", function () {
      savePeriod(periodSelect.value);
      load();
    });
  }
  if (exportBtn) exportBtn.addEventListener("click", exportCsv);
  if (window.LLMApi && LLMApi.onProjectReady) {
    LLMApi.onProjectReady(function () { load(); });
  } else {
    load();
    var select = document.getElementById("project-select");
    if (select) select.addEventListener("change", load);
  }
})();
