(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "progress" || !root) return;

  var SVG_NS = "http://www.w3.org/2000/svg";
  var C_HUMAN = "var(--progress-human)";
  var C_LLM = "var(--progress-llm)";
  var C_LOC = "var(--progress-localized)";
  var LOCALE_COLORS = [C_LOC, "var(--progress-locale-line)", C_LLM, C_HUMAN];

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
    // Prefer window.uiT so en-XX markers win over English en-fallback in uiLocale.t.
    var text = (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
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
  function rate(value) {
    var v = Number(value || 0);
    return v >= 10 ? num(Math.round(v)) : String(Math.round(v * 10) / 10);
  }
  function pctOf(part, whole) { return whole > 0 ? (part / whole) * 100 : 0; }
  function pctText(part, whole) { return String(Math.round(pctOf(part, whole))); }

  function shortDate(iso) {
    var d = new Date(String(iso).slice(0, 10) + "T00:00:00");
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function panel(label, note, pad) {
    var wrap = el("div", "pg-panel" + (pad ? " pg-panel-pad" : ""));
    var head = el("div", "pg-panel-head");
    head.appendChild(el("div", "pg-label", label));
    if (note != null) head.appendChild(note);
    wrap.appendChild(head);
    root.appendChild(wrap);
    return wrap;
  }

  function cell(row, text, className, style) {
    var td = el("td", className || "", text);
    if (style) td.style.cssText = style;
    row.appendChild(td);
    return td;
  }

  function headRow(cols) {
    var thead = el("thead");
    var tr = el("tr");
    cols.forEach(function (col) {
      tr.appendChild(el("th", col.right ? "r" : "", col.text));
    });
    thead.appendChild(tr);
    return thead;
  }

  function legendChip(color, label) {
    var chip = el("span");
    var swatch = el("i");
    swatch.style.background = color;
    chip.appendChild(swatch);
    chip.appendChild(document.createTextNode(label));
    return chip;
  }

  function header() {
    var subRow = el("div", "pg-sub-row");
    subRow.appendChild(el("p", "pg-sub", t(
      "progress_subtitle",
      "Translation stages over time — localized, LLM-verified, human-verified")));
    if (window.LLMHelp) subRow.appendChild(window.LLMHelp.helpBtn("progress:general"));
    root.appendChild(subRow);
    var legend = el("div", "pg-legend");
    legend.appendChild(legendChip(C_HUMAN, t("progress_legend_human", "Human verified")));
    legend.appendChild(legendChip(C_LLM, t("progress_legend_llm", "LLM verified")));
    legend.appendChild(legendChip(C_LOC, t("progress_legend_localized", "Localized")));
    legend.appendChild(legendChip("var(--progress-missing)", t("progress_legend_missing", "Missing")));
    root.appendChild(legend);
  }

  function summaryCards(locales) {
    var sum = { total: 0, localized: 0, llm: 0, human: 0 };
    locales.forEach(function (row) {
      sum.total = Math.max(sum.total, row.total || 0);
      sum.localized += row.localized || 0;
      sum.llm += row.llmVerified || 0;
      sum.human += row.humanVerified || 0;
    });
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
    card(t("progress_card_total", "Total source strings"), num(sum.total),
      t("progress_card_total_sub", "across {n} locales", { n: locales.length }));
    card(t("progress_card_localized", "Localized (any locale)"), num(sum.localized),
      t("progress_card_localized_sub", "total string-locale pairs"), "var(--color-accent)");
    card(t("progress_card_llm", "LLM-verified"), num(sum.llm),
      t("progress_card_pct_sub", "{p}% of translated", { p: pctText(sum.llm, sum.localized) }), C_LLM);
    card(t("progress_card_human", "Human-verified"), num(sum.human),
      t("progress_card_pct_sub", "{p}% of translated", { p: pctText(sum.human, sum.localized) }), C_HUMAN);
    root.appendChild(grid);
  }

  function barSegment(cls, width, title) {
    var seg = el("i", cls);
    seg.style.width = Math.max(0, width) + "%";
    if (title) seg.title = title;
    return seg;
  }

  function stagePanel(locales) {
    var total = locales.reduce(function (m, r) { return Math.max(m, r.total || 0); }, 0);
    var wrap = panel(t("progress_stages_title", "Per-locale stage breakdown"), null, false);
    var table = el("table", "pg-table");
    table.appendChild(headRow([
      { text: t("progress_col_locale", "Locale") },
      { text: t("progress_stage_col", "Stage progress (of {n} source strings)", { n: num(total) }) },
      { text: t("progress_col_localized", "Localized"), right: true },
      { text: t("progress_col_llm", "LLM-verified"), right: true },
      { text: t("progress_col_human", "Human-verified"), right: true },
      { text: t("progress_col_missing", "Missing"), right: true },
    ]));
    var body = el("tbody");
    locales.forEach(function (row) {
      var tr = el("tr", row.frozen ? "pg-frozen" : "");
      var rowTotal = row.total || 0;
      var human = row.humanVerified || 0;
      var llm = row.llmVerified || 0;
      var localized = row.localized || 0;
      var other = Math.max(0, localized - human - llm);
      var missing = Math.max(0, rowTotal - localized);

      var name = cell(tr, "", "");
      name.appendChild(el("span", "pg-loc", row.locale));
      if (row.frozen) {
        name.appendChild(el("br"));
        name.appendChild(el("span", "pg-faint", t("progress_frozen", "frozen")));
      }

      var barCell = cell(tr, "", "");
      var bar = el("div", "pg-bar");
      bar.appendChild(barSegment("pg-human", pctOf(human, rowTotal), num(human) + " " + t("progress_legend_human", "Human verified").toLowerCase()));
      bar.appendChild(barSegment("pg-llm", pctOf(llm, rowTotal), num(llm) + " " + t("progress_legend_llm", "LLM verified").toLowerCase()));
      bar.appendChild(barSegment("pg-localized", pctOf(other, rowTotal), num(other) + " " + t("progress_legend_localized", "Localized").toLowerCase()));
      barCell.appendChild(bar);
      var caption = el("div", "pg-bar-caption", t("progress_pct_localized", "{p}% localized", { p: pctText(localized, rowTotal) }));
      if (row.priority === "asap") {
        var tag = el("span", "", " · " + t("progress_asap", "ASAP"));
        tag.style.cssText = "color:var(--color-accent);font-weight:600;";
        caption.appendChild(tag);
      } else if (row.frozen) {
        caption.appendChild(document.createTextNode(" · " + t("progress_frozen", "frozen")));
      }
      barCell.appendChild(caption);

      cell(tr, num(localized), "r pg-mono");
      cell(tr, num(llm), "r pg-mono").style.color = C_LLM;
      var humanCell = cell(tr, num(human), "r pg-mono");
      if (human > 0) { humanCell.style.color = C_HUMAN; humanCell.style.fontWeight = "600"; }
      else humanCell.style.color = "var(--color-neutral-500)";
      cell(tr, num(missing), "r pg-mono").style.color = "var(--color-neutral-500)";
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);
  }

  // ---- charts ---------------------------------------------------------------

  var PL = 40, PR = 610, PT = 10, PB = 130;

  function chartBase(days, yLabels) {
    var svg = svgEl("svg", { viewBox: "0 0 680 150", "class": "pg-chart", role: "img" });
    var steps = yLabels.length - 1;
    yLabels.forEach(function (label, i) {
      var y = PT + ((PB - PT) * i) / steps;
      svg.appendChild(svgEl("line", { x1: PL, y1: y, x2: PR, y2: y, "class": "g" }));
      svg.appendChild(svgEl("text", { x: PL - 5, y: y + 3, "text-anchor": "end" }, label));
    });
    [0, 0.25, 0.5, 0.75, 1].forEach(function (frac) {
      var idx = Math.round(frac * (days.length - 1));
      svg.appendChild(svgEl("text", { x: xAt(idx, days.length), y: 143, "text-anchor": "middle" }, shortDate(days[idx])));
    });
    return svg;
  }

  function xAt(i, n) { return PL + ((PR - PL) * i) / Math.max(1, n - 1); }

  function polyline(values, n, yOf, color, width, dash) {
    var runs = [], current = [];
    values.forEach(function (value, i) {
      if (value == null) {
        if (current.length) runs.push(current);
        current = [];
        return;
      }
      current.push(xAt(i, n).toFixed(1) + "," + yOf(value).toFixed(1));
    });
    if (current.length) runs.push(current);
    var group = svgEl("g");
    runs.forEach(function (points) {
      var line = svgEl("polyline", {
        points: points.join(" "), "class": "line", stroke: color, "stroke-width": width,
      });
      if (dash) line.setAttribute("stroke-dasharray", dash);
      if (points.length === 1) {
        var xy = points[0].split(",");
        group.appendChild(svgEl("circle", { cx: xy[0], cy: xy[1], r: 2.5, fill: color }));
      }
      group.appendChild(line);
    });
    return group;
  }

  function niceMax(value) {
    if (value <= 4) return 4;
    var mag = Math.pow(10, Math.floor(Math.log(value) / Math.LN10));
    var steps = [1, 2, 4, 5, 8, 10];
    for (var i = 0; i < steps.length; i++) {
      if (value <= steps[i] * mag) return steps[i] * mag;
    }
    return 10 * mag;
  }

  function legendLine(color, text, dashed) {
    var item = el("span");
    var swatch = el("i");
    swatch.style.background = color;
    if (dashed) {
      swatch.style.background = "transparent";
      swatch.style.borderTop = "2px dashed " + color;
      swatch.style.height = "0";
    }
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(text));
    return item;
  }

  function velocityPanel(series) {
    var avg = series.avgPerDay || 0;
    var note = el("div", "pg-note", t("progress_avg", "avg {n} strings/day", { n: rate(avg) }));
    var wrap = panel(t("progress_velocity_title", "Translation progress — last 30 days (all active locales combined)"), note, true);
    var stages = series.stages || {};
    var days = series.days || [];
    var top = Math.max.apply(null, [0].concat(stages.localized || [], stages.llm || [], stages.human || []));
    if (!days.length || top <= 0) {
      wrap.appendChild(el("p", "pg-note", t("progress_no_data", "No data yet.")));
      return;
    }
    var max = niceMax(top);
    var labels = [4, 3, 2, 1, 0].map(function (k) { return num(Math.round((max * k) / 4)); });
    var svg = chartBase(days, labels);
    function yOf(v) { return PB - ((PB - PT) * v) / max; }
    svg.appendChild(polyline(stages.localized || [], days.length, yOf, C_LOC, 2.5));
    svg.appendChild(polyline(stages.llm || [], days.length, yOf, C_LLM, 2));
    svg.appendChild(polyline(stages.human || [], days.length, yOf, C_HUMAN, 2, "5,3"));
    var xToday = xAt(days.length - 1, days.length);
    svg.appendChild(svgEl("line", {
      x1: xToday, y1: PT, x2: xToday, y2: PB, stroke: C_LOC,
      "stroke-width": 1, "stroke-dasharray": "3,2", opacity: ".5",
    }));
    var today = svgEl("text", { x: xToday + 2, y: 22 }, t("progress_today", "today"));
    today.setAttribute("fill", "var(--progress-localized)");
    svg.appendChild(today);
    wrap.appendChild(svg);
    var legend = el("div", "pg-chart-legend");
    legend.appendChild(legendLine(C_LOC, t("progress_col_localized", "Localized")));
    legend.appendChild(legendLine(C_LLM, t("progress_col_llm", "LLM-verified")));
    legend.appendChild(legendLine(C_HUMAN, t("progress_col_human", "Human-verified"), true));
    wrap.appendChild(legend);
  }

  var SOURCE_COLORS = {
    human: "var(--progress-src-human)", tm: "var(--progress-src-tm)", mt: "var(--progress-src-mt)",
    ai: "var(--progress-src-ai)", imported: "var(--progress-src-imported)",
  };
  var SOURCE_LABELS = {
    human: ["progress_src_human", "Human"], tm: ["progress_src_tm", "Translation memory"],
    mt: ["progress_src_mt", "Machine translation"], ai: ["progress_src_ai", "AI"],
    imported: ["progress_src_imported", "Imported"],
  };

  function sourcesPanel(series) {
    var sources = series.sources || {};
    var days = series.days || [];
    var classes = Object.keys(SOURCE_COLORS);
    var all = [0];
    classes.forEach(function (c) { all = all.concat(sources[c] || []); });
    var top = Math.max.apply(null, all);
    var wrap = panel(t("progress_sources_title", "Throughput by source — last 30 days (keys per day, by who produced them)"), null, true);
    if (!days.length || top <= 0) {
      wrap.appendChild(el("p", "pg-note", t("progress_no_data", "No data yet.")));
      return;
    }
    var max = niceMax(top);
    var labels = [4, 3, 2, 1, 0].map(function (k) { return num(Math.round((max * k) / 4)); });
    var svg = chartBase(days, labels);
    function yOf(v) { return PB - ((PB - PT) * v) / max; }
    classes.forEach(function (c) {
      if ((sources[c] || []).some(function (n) { return n > 0; })) {
        svg.appendChild(polyline(sources[c], days.length, yOf, SOURCE_COLORS[c], 2));
      }
    });
    wrap.appendChild(svg);
    var legend = el("div", "pg-chart-legend");
    classes.forEach(function (c) {
      var total = (sources[c] || []).reduce(function (a, b) { return a + b; }, 0);
      legend.appendChild(legendLine(SOURCE_COLORS[c], t(SOURCE_LABELS[c][0], SOURCE_LABELS[c][1]) + " " + num(total)));
    });
    wrap.appendChild(legend);
  }

  function qualityPanel(locales, series) {
    var select = el("select", "pg-select");
    var all = el("option", "", t("progress_all_locales", "All locales"));
    all.value = "";
    select.appendChild(all);
    locales.forEach(function (row) {
      var opt = el("option", "", row.locale);
      opt.value = row.locale;
      select.appendChild(opt);
    });
    var wrap = panel(t("progress_quality_title", "Mean quality score — last 30 days (per locale, 7-day rolling avg)"), select, true);
    var holder = el("div");
    wrap.appendChild(holder);
    var quality = series.quality || {};
    var days = series.days || [];
    var threshold = series.qualityThreshold == null ? 0.55 : series.qualityThreshold;

    function draw() {
      holder.textContent = "";
      var chosen = select.value;
      var shown = locales.filter(function (row) {
        var rolling = (quality[row.locale] || {}).rolling7 || [];
        return (!chosen || row.locale === chosen) && rolling.some(function (v) { return v != null; });
      });
      if (!days.length || !shown.length) {
        holder.appendChild(el("p", "pg-note", t("progress_no_data", "No data yet.")));
        return;
      }
      var svg = chartBase(days, ["1.0", "0.75", "0.5", "0.25", "0"]);
      function yOf(v) { return PB - (PB - PT) * Math.max(0, Math.min(1, v)); }
      var legend = el("div", "pg-chart-legend");
      shown.forEach(function (row, i) {
        var color = LOCALE_COLORS[i % LOCALE_COLORS.length];
        svg.appendChild(polyline((quality[row.locale] || {}).rolling7 || [], days.length, yOf, color, 2));
        var avg = row.meanScore == null ? "—" : Number(row.meanScore).toFixed(2);
        legend.appendChild(legendLine(color, row.locale + " · " + t("progress_avg_label", "{n} avg", { n: avg })));
      });
      var yT = yOf(threshold);
      svg.appendChild(svgEl("line", {
        x1: PL, y1: yT, x2: PR, y2: yT, stroke: "var(--progress-threshold)",
        "stroke-width": 1, "stroke-dasharray": "4,3", opacity: ".6",
      }));
      var label = svgEl("text", { x: PR + 4, y: yT + 3 }, t("progress_threshold", "{n} threshold", { n: threshold }));
      label.setAttribute("fill", "var(--progress-threshold)");
      svg.appendChild(label);
      holder.appendChild(svg);
      var source = el("span", "", t("progress_quality_source", "source: scores sidecar"));
      source.style.color = "var(--color-neutral-600)";
      legend.appendChild(source);
      holder.appendChild(legend);
    }
    select.addEventListener("change", draw);
    draw();
  }

  // ---- ETA and runs -----------------------------------------------------------

  function etaCell(tr, eta, opts) {
    var td = cell(tr, "", "r");
    if (opts.frozen) {
      td.textContent = opts.first ? t("progress_frozen_dash", "— frozen") : "—";
      td.style.color = "var(--color-neutral-500)";
      return;
    }
    if (!eta) {
      td.textContent = "—";
      td.style.color = "var(--color-neutral-500)";
      return;
    }
    if (eta.days === 0) {
      td.textContent = t("progress_done", "Done");
    } else if (opts.first) {
      td.textContent = shortDate(eta.date) + " (~" + eta.days + "d)";
    } else {
      td.textContent = shortDate(eta.date);
    }
    if (opts.first) {
      td.style.fontWeight = "600";
      td.style.color = opts.asap ? "var(--progress-asap-text)" : C_LLM;
    } else {
      td.className = "r pg-mono";
      td.style.color = "var(--color-neutral-700)";
    }
  }

  function etaPanel(locales) {
    var note = el("div", "pg-note", t("progress_eta_basis", "based on 7-day rolling velocity"));
    var wrap = panel(t("progress_eta_title", "Completion estimate"), note, false);
    var table = el("table", "pg-table");
    table.appendChild(headRow([
      { text: t("progress_col_locale", "Locale") },
      { text: t("progress_col_priority", "Priority") },
      { text: t("progress_col_remaining", "Remaining"), right: true },
      { text: t("progress_col_velocity", "Velocity"), right: true },
      { text: t("progress_col_eta_loc", "ETA — 100% localized"), right: true },
      { text: t("progress_col_eta_llm", "ETA — 100% LLM-verified"), right: true },
      { text: t("progress_col_eta_human", "ETA — 100% human"), right: true },
    ]));
    var order = { asap: 0, normal: 1, frozen: 2 };
    var sorted = locales.slice().sort(function (a, b) {
      return (order[a.priority] - order[b.priority]) || a.locale.localeCompare(b.locale);
    });
    var body = el("tbody");
    sorted.forEach(function (row) {
      var frozen = row.priority === "frozen";
      var asap = row.priority === "asap";
      var tr = el("tr", frozen ? "pg-frozen" : (asap ? "pg-asap" : ""));
      var name = cell(tr, "", "");
      var loc = el("span", "pg-loc", row.locale);
      if (frozen) loc.style.color = "var(--color-neutral-600)";
      name.appendChild(loc);
      var prioCell = cell(tr, "", "");
      prioCell.appendChild(el("span", "pg-prio" + (asap ? " pg-prio-asap" : ""),
        t("progress_prio_" + row.priority, row.priority)));
      cell(tr, t("progress_strings", "{n} strings", { n: num((row.missing || 0) + (row.stale || 0)) }), "r pg-mono");
      var vel = cell(tr, t("progress_per_day", "{n}/day", { n: frozen ? 0 : rate(row.velocity7PerDay) }), "r pg-mono");
      vel.style.color = "var(--color-neutral-700)";
      var eta = row.etaDates || {};
      etaCell(tr, eta.localized, { frozen: frozen, first: true, asap: asap });
      etaCell(tr, eta.llm, { frozen: frozen });
      etaCell(tr, eta.human, { frozen: frozen });
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    wrap.appendChild(el("div", "pg-foot", t(
      "progress_eta_note",
      "ETA assumes current velocity is maintained. ASAP locales are scheduled first. Frozen locales are excluded from automatic runs.")));
  }

  function duration(seconds) {
    var s = Math.round(Number(seconds));
    if (!isFinite(s) || s <= 0) return "—";
    var m = Math.floor(s / 60);
    var rest = s % 60;
    return m ? m + "m " + (rest < 10 ? "0" : "") + rest + "s" : rest + "s";
  }

  function runStamp(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso || "");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " · " +
      d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function runDescription(run) {
    var span = el("span");
    var n = num(run.delta);
    var text;
    if (run.command === "translate") text = t("progress_run_translated", "Translated {n} strings", { n: n });
    else if (run.command === "improve") text = t("progress_run_improved", "Improved {n} strings", { n: n });
    else text = t("progress_run_other", "{cmd} · {n} strings", { cmd: run.command, n: n });
    span.appendChild(document.createTextNode(text));
    if (run.model) {
      span.appendChild(document.createTextNode(" " + t("progress_run_via", "via") + " "));
      var model = el("span", "pg-mono", run.model);
      model.style.fontSize = "11.5px";
      span.appendChild(model);
    }
    if (run.provider) {
      span.appendChild(document.createTextNode(" " + t("progress_run_on", "on") + " " + run.provider));
    }
    return span;
  }

  function runsPanel(runs) {
    var wrap = panel(t("progress_runs_title", "Recent translation runs"), null, false);
    if (!runs.length) {
      wrap.appendChild(el("div", "pg-empty", t("progress_no_runs", "No runs recorded yet.")));
      return;
    }
    runs.forEach(function (run) {
      var line = el("div", "pg-runs-row");
      var stamp = el("span", "pg-mono", runStamp(run.at));
      stamp.style.cssText = "font-size:11px;color:var(--color-neutral-600);";
      line.appendChild(stamp);
      line.appendChild(el("span", "pg-loc", (run.locales || []).join(", ")));
      line.appendChild(runDescription(run));
      var delta = el("span", "pg-mono", "+" + num(run.delta));
      delta.style.cssText = "text-align:right;color:" + C_LLM + ";";
      line.appendChild(delta);
      var took = el("span", "", duration(run.wallSeconds));
      took.style.cssText = "font-size:11px;color:var(--color-neutral-500);text-align:right;";
      line.appendChild(took);
      wrap.appendChild(line);
    });
  }

  // ---- load ---------------------------------------------------------------------

  function render(data) {
    root.textContent = "";
    var wrapper = el("div", "pg");
    var holder = root;
    root.appendChild(wrapper);
    // Panels append to `root`; move them under the wrapper afterwards.
    var locales = data.locales || [];
    if (!locales.length) {
      wrapper.appendChild(el("p", "empty-state", t("progress_no_locales", "No target locales configured.")));
      return;
    }
    var series = data.series || {};
    header();
    summaryCards(locales);
    stagePanel(locales);
    velocityPanel(series);
    sourcesPanel(series);
    qualityPanel(locales, series);
    etaPanel(locales);
    runsPanel(data.runs || []);
    var children = Array.prototype.slice.call(holder.childNodes);
    children.forEach(function (child) { if (child !== wrapper) wrapper.appendChild(child); });
  }

  var loadToken = 0;

  function showLoading() {
    root.textContent = "";
    root.setAttribute("aria-busy", "true");
    var note = el("p", "pg-loading", t("progress_loading", "Loading…"));
    note.setAttribute("role", "status");
    root.appendChild(note);
  }

  function load() {
    var token = ++loadToken;
    showLoading();
    var name = project();
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/progress", name ? { project: name } : {})
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
        root.appendChild(el("p", "empty-state", t("progress_error", "Could not load progress.")));
      });
  }

  if (window.LLMApi && LLMApi.onProjectReady) {
    LLMApi.onProjectReady(function () { load(); });
  } else {
    load();
    var select = document.getElementById("project-select");
    if (select) select.addEventListener("change", load);
  }
})();
