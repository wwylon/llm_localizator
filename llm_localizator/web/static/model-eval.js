(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "model-eval" || !root) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function tabsSpec() {
    return [
      { id: "run", label: uiT("me_tab_run", "Run evaluation") },
      { id: "history", label: uiT("me_tab_history", "Results history") },
      { id: "comparison", label: uiT("me_tab_comparison", "Model comparison") },
    ];
  }
  function notYet() {
    return uiT("me_not_yet", "Not configurable yet: the bakeoff has one fixed scorer (ADR-51).");
  }
  function dimensions() {
    return [
      uiT("me_dim_bt", "Back-translation score"),
      uiT("me_dim_ph", "Placeholder preservation"),
      uiT("me_dim_gloss", "Glossary term adherence"),
      uiT("me_dim_len", "Length ratio"),
      uiT("me_dim_fluency", "Fluency (LLM judge)"),
      uiT("me_dim_throughput", "Throughput (strings/sec)"),
    ];
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

  var state = {
    tab: "run",
    data: null,
    selectedReport: "REPORT.md",
    reportText: null,
    log: null,
    form: { model: "", locale: "", corpus: "", limit: 50 },
  };

  root.replaceChildren();
  var tabs = el("div", "tabs");
  var panel = el("div", "tab-panel me-panel");
  var status = el("p", "empty-state me-status", uiT("me_loading", "Loading."));
  root.appendChild(tabs);
  root.appendChild(panel);
  root.appendChild(status);

  var headActions = document.getElementById("me-head-actions");
  if (headActions && window.LLMHelp) {
    headActions.appendChild(window.LLMHelp.helpBtn("model-eval:general"));
  }

  tabsSpec().forEach(function (item) {
    var btn = el("button", "tab-btn", item.label);
    btn.type = "button";
    btn.dataset.tab = item.id;
    btn.addEventListener("click", function () {
      state.tab = item.id;
      paint();
    });
    tabs.appendChild(btn);
  });

  function paintTabs() {
    Array.prototype.forEach.call(tabs.querySelectorAll(".tab-btn"), function (btn) {
      btn.className = "tab-btn" + (btn.dataset.tab === state.tab ? " is-active" : "");
    });
  }

  function paint() {
    paintTabs();
    panel.replaceChildren();
    var data = state.data;
    if (!data) return;
    if (!data.available) {
      panel.appendChild(el("p", "empty-state", data.error || uiT("me_unavailable", "Bakeoff reports unavailable.")));
      status.textContent = "";
      return;
    }
    if (state.tab === "run") paintRun(data);
    else if (state.tab === "history") paintHistory(data);
    else paintComparison(data);
  }

  function card(title) {
    var box = el("section", "me-card");
    if (title) box.appendChild(el("div", "me-card-label", title));
    return box;
  }

  function field(label, control, hint) {
    var wrap = el("label", "me-field");
    wrap.appendChild(el("span", "me-field-label", label));
    wrap.appendChild(control);
    if (hint) wrap.appendChild(el("span", "field-hint", hint));
    return wrap;
  }

  function select(options, value) {
    var sel = document.createElement("select");
    options.forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.label;
      sel.appendChild(o);
    });
    if (value != null) sel.value = value;
    return sel;
  }

  function disabledSelect(label) {
    var sel = select([{ value: "", label: label }], "");
    sel.disabled = true;
    sel.title = notYet();
    return sel;
  }

  function scoreOf(text) {
    var n = parseFloat(String(text || ""));
    return isNaN(n) ? null : n;
  }

  function scoreTone(n) {
    if (n == null) return "";
    return n >= 0.9 ? "is-good" : n >= 0.8 ? "is-warn" : "is-bad";
  }

  function logLine(box, kind, text) {
    box.appendChild(el("div", "log-line-" + kind, text));
  }

  function paintRun(data) {
    var form = state.form;
    var locales = data.locales || [];
    if (!form.locale || locales.indexOf(form.locale) < 0) form.locale = locales[0] || "";
    var limits = data.limit || { min: 10, max: 500, default: 50 };
    if (!form.limit) form.limit = limits.default;

    var setup = card(uiT("me_eval_setup", "Evaluation setup"));
    var row1 = el("div", "me-grid");
    var model = document.createElement("input");
    model.type = "text";
    model.className = "me-mono";
    model.placeholder = uiT("me_model_ph", "e.g. mistral:7b (empty = full matrix)");
    model.value = form.model;
    model.setAttribute("list", "me-pinned");
    var datalist = document.createElement("datalist");
    datalist.id = "me-pinned";
    (data.pinned || []).forEach(function (name) {
      var o = document.createElement("option");
      o.value = name;
      datalist.appendChild(o);
    });
    model.addEventListener("input", function () { form.model = model.value; });
    var modelField = field(
      uiT("me_model_label", "Model to evaluate"), model,
      uiT("me_model_hint", "An Ollama tag installed locally. Leave empty to queue all pinned candidates."),
    );
    modelField.appendChild(datalist);
    row1.appendChild(modelField);

    var locSel = select(
      locales.map(function (l) { return { value: l, label: l }; }),
      form.locale,
    );
    locSel.addEventListener("change", function () {
      form.locale = locSel.value;
      paint();
    });
    row1.appendChild(field(uiT("me_target_locale", "Target locale"), locSel));

    var corpusSel = select([
      { value: "", label: uiT("me_corpus_project", "Project sample (strings from this project)") },
      { value: "builtin", label: uiT("me_corpus_builtin", "Built-in corpus") },
    ], form.corpus);
    corpusSel.addEventListener("change", function () { form.corpus = corpusSel.value; });
    row1.appendChild(field(uiT("me_test_set", "Test set"), corpusSel));
    setup.appendChild(row1);

    var row2 = el("div", "me-grid");
    row2.appendChild(field(uiT("me_baseline", "Baseline model (compare against)"), disabledSelect(uiT("me_incumbent", "Incumbent from the Winners table"))));
    row2.appendChild(field(uiT("me_judge", "Judge model (for scoring)"), disabledSelect(uiT("me_bt_fixed", "Back-translation (fixed)"))));
    var size = document.createElement("input");
    size.type = "number";
    size.min = limits.min;
    size.max = limits.max;
    size.value = form.limit;
    size.addEventListener("input", function () { form.limit = size.value; });
    row2.appendChild(field(uiT("me_sample_size", "Sample size"), size, limits.min + "–" + limits.max + " " + uiT("me_strings", "strings.")));
    setup.appendChild(row2);

    var dims = el("div", "me-dims");
    dims.appendChild(el("div", "me-field-label", uiT("me_dims", "Quality dimensions to measure")));
    var chips = el("div", "me-chips");
    dimensions().forEach(function (name, i) {
      var chip = el("label", "me-chip");
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = i === 0;
      box.disabled = true;
      chip.title = notYet();
      chip.appendChild(box);
      chip.appendChild(document.createTextNode(name));
      chips.appendChild(chip);
    });
    dims.appendChild(chips);
    dims.appendChild(el("p", "field-hint", notYet()));
    setup.appendChild(dims);

    var actions = el("div", "me-actions");
    var runBtn = el("button", "btn btn-primary", uiT("me_run", "▶ Run evaluation"));
    runBtn.type = "button";
    var dryBtn = el("button", "btn", uiT("me_dry", "Dry run (count only)"));
    dryBtn.type = "button";
    actions.appendChild(runBtn);
    actions.appendChild(dryBtn);
    actions.appendChild(el(
      "span", "field-hint",
      uiT("me_queue_hint", "Queued in taskqueue (ADR-28). Time depends on model and sample size."),
    ));
    setup.appendChild(actions);
    panel.appendChild(setup);

    var logCard = card(uiT("me_run_log", "Run log"));
    var log = el("div", "ops-log me-log");
    logCard.appendChild(log);
    function paintLog() {
      log.replaceChildren();
      (state.log || []).forEach(function (line) { logLine(log, line.kind, line.text); });
    }
    if (state.log) {
      paintLog();
      panel.appendChild(logCard);
    }

    function submit(dry) {
      var body = {
        project: project(),
        locale: form.locale,
        model: form.model.trim(),
        corpus: form.corpus,
        limit: Number(form.limit),
        dry_run: dry,
      };
      status.textContent = dry ? uiT("me_counting", "Counting.") : uiT("me_submitting", "Submitting.");
      fetch("/api/model-eval/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(function (r) { return r.json(); }).then(function (result) {
        var lines = [{
          kind: "cmd",
          text: (dry ? uiT("me_log_dry", "dry run") : uiT("me_log_run", "run"))
            + " · " + (body.model || uiT("me_full_matrix", "full matrix")) + " · " + body.locale,
        }];
        (result.lines || []).forEach(function (text) { lines.push({ kind: "dim", text: text }); });
        lines.push(result.ok
          ? { kind: "ok", text: "✓ " + (result.message || result.task || uiT("me_ok", "OK")) }
          : { kind: "err", text: "✗ " + (result.error || uiT("me_run_failed", "Run failed.")) });
        state.log = lines;
        status.textContent = "";
        paint();
      }).catch(function () {
        status.textContent = uiT("setup_request_failed", "Request failed.");
      });
    }
    runBtn.addEventListener("click", function () { submit(false); });
    dryBtn.addEventListener("click", function () { submit(true); });

    paintSummary(data);

    var cal = data.calibrate || {};
    var calCard = card(uiT("me_gold_cal", "Gold calibration (C.2)"));
    calCard.appendChild(el(
      "p", "empty-state",
      uiT("me_cal_run", "Run") + " " + (cal.script || "calibrate_gold.py") + " "
        + uiT("me_cal_from", "from the engine checkout. See") + " "
        + (cal.docs || "docs/model-evaluation.md") + ". "
        + uiT("me_cal_no_scorer", "This page does not add a scorer."),
    ));
    panel.appendChild(calCard);
  }

  function winnerFor(data, locale) {
    return (data.comparison || []).filter(function (row) { return row.locale === locale; })[0];
  }

  function stat(label, value, sub, tone) {
    var cell = el("div", "me-stat");
    cell.appendChild(el("div", "me-stat-label", label));
    cell.appendChild(el("div", "me-stat-value " + (tone || ""), value));
    cell.appendChild(el("div", "me-stat-sub", sub || ""));
    return cell;
  }

  function paintSummary(data) {
    var row = winnerFor(data, state.form.locale);
    var box = card(uiT("me_recorded_winner", "Recorded Winner —") + " " + (state.form.locale || uiT("me_no_locale", "no locale")));
    if (!row) {
      box.appendChild(el(
        "p", "empty-state",
        uiT("me_no_winner_row", "No Winners row for this locale yet. Run a bakeoff, then read the result in REPORT.md."),
      ));
      panel.appendChild(box);
      return;
    }
    var n = scoreOf(row.score);
    var grid = el("div", "me-stats");
    grid.appendChild(stat(
      uiT("me_stat_winner", "Winner"), row.winner,
      uiT("me_sub_mean_bt", "mean BT score {score}").replace("{score}", row.score),
    ));
    grid.appendChild(stat(
      uiT("me_stat_mean", "Mean BT score"), row.score,
      uiT("me_sub_higher", "higher is better"), scoreTone(n),
    ));
    grid.appendChild(stat(
      uiT("me_stat_runner", "Runner-up"), row.runnerUp || "—",
      uiT("me_sub_next", "next best candidate"),
    ));
    grid.appendChild(stat(
      uiT("me_stat_locales", "Locales covered"), String((data.comparison || []).length),
      uiT("me_sub_winners_table", "in the Winners table"),
    ));
    box.appendChild(grid);
    if (row.notes) box.appendChild(el("p", "me-verdict", uiT("me_note", "Note:") + " " + row.notes));
    var go = el("button", "btn", uiT("me_view_comparison", "View comparison"));
    go.type = "button";
    go.addEventListener("click", function () { state.tab = "comparison"; paint(); });
    box.appendChild(go);
    panel.appendChild(box);
  }

  function fmtDate(iso) {
    return iso ? String(iso).replace("T", " ").replace(/:\d\d(\.\d+)?Z$/, "") : "";
  }

  function paintHistory(data) {
    var box = card(uiT("me_past", "Past evaluations"));
    var reports = data.reports || [];
    if (!reports.length) {
      box.appendChild(el("p", "empty-state", uiT("me_no_reports", "No markdown reports in the bakeoff directory.")));
      panel.appendChild(box);
      return;
    }
    var table = el("table", "glossary-table me-table");
    var head = document.createElement("tr");
    [uiT("me_th_date", "Date"), uiT("me_th_report", "Report"), uiT("me_th_size", "Size"), uiT("me_th_winners", "Winners"), ""].forEach(function (label) {
      head.appendChild(el("th", "", label));
    });
    table.appendChild(head);
    reports.forEach(function (report) {
      var tr = document.createElement("tr");
      if (report.name === state.selectedReport) tr.className = "is-active";
      tr.appendChild(el("td", "me-mono", fmtDate(report.mtime)));
      var name = el("td");
      name.appendChild(el("code", "me-mono", report.name));
      tr.appendChild(name);
      tr.appendChild(el("td", "me-mono", Math.max(1, Math.round((report.size || 0) / 1024)) + " KB"));
      var badge = el("td");
      badge.appendChild(report.has_winner
        ? el("span", "pill pill-ok", uiT("me_pill_winners", "winners"))
        : el("span", "pill", uiT("me_pill_evidence", "evidence")));
      tr.appendChild(badge);
      var view = el("td");
      var btn = el("button", "btn", uiT("me_view", "View →"));
      btn.type = "button";
      btn.addEventListener("click", function () { openReport(report.name); });
      view.appendChild(btn);
      tr.appendChild(view);
      table.appendChild(tr);
    });
    box.appendChild(table);
    panel.appendChild(box);
    if (state.reportText && state.reportText.name) {
      var viewer = card(state.reportText.name);
      viewer.appendChild(el("pre", "me-report", state.reportText.text));
      panel.appendChild(viewer);
    }
  }

  function openReport(name) {
    state.selectedReport = name;
    status.textContent = uiT("me_loading_report", "Loading report.");
    fetch("/api/model-eval?report=" + encodeURIComponent(name))
      .then(function (r) { return r.json(); })
      .then(function (result) {
        state.reportText = result.ok ? result : null;
        status.textContent = result.ok ? "" : (result.error || uiT("me_report_unavailable", "Report unavailable."));
        paint();
      });
  }

  function paintComparison(data) {
    var box = card(uiT("me_comparison", "Model quality comparison"));
    var rows = data.comparison || [];
    if (rows.length) {
      var table = el("table", "glossary-table me-table");
      var head = document.createElement("tr");
      [uiT("me_th_locale", "Locale"), uiT("me_th_winner", "Winner"), uiT("me_th_mean_bt", "Mean BT"), uiT("me_th_runner", "Runner-up"), uiT("me_th_notes", "Notes")].forEach(function (label) {
        head.appendChild(el("th", "", label));
      });
      table.appendChild(head);
      rows.forEach(function (row) {
        var tr = document.createElement("tr");
        if (row.locale === state.form.locale) tr.className = "is-active";
        var loc = el("td");
        loc.appendChild(el("span", "me-locale", row.locale));
        tr.appendChild(loc);
        var win = el("td");
        win.appendChild(el("code", "me-mono", row.winner));
        tr.appendChild(win);
        var n = scoreOf(row.score);
        var sc = el("td");
        sc.appendChild(el("span", "me-mono me-score " + scoreTone(n), row.score));
        if (n != null) {
          var bar = el("div", "score-bar");
          var fill = el("div", "score-bar-fill " + scoreTone(n));
          fill.style.width = Math.max(0, Math.min(100, Math.round(n * 100))) + "%";
          bar.appendChild(fill);
          sc.appendChild(bar);
        }
        tr.appendChild(sc);
        tr.appendChild(el("td", "me-mono", row.runnerUp || ""));
        tr.appendChild(el("td", "", row.notes || ""));
        table.appendChild(tr);
      });
      box.appendChild(table);
      box.appendChild(el(
        "p", "field-hint",
        uiT(
          "me_winners_hint",
          "Winners from REPORT.md, ranked on mean back-translation score. A close runner-up or a tie note means the choice is within noise.",
        ),
      ));
    } else {
      box.appendChild(el("p", "empty-state", uiT("me_no_winners_table", "No Winners table parsed from REPORT.md.")));
    }
    panel.appendChild(box);

    var winners = (data.reports || []).filter(function (r) { return r.has_winner; });
    var apply = card(uiT("me_apply", "Apply recommendation"));
    var line = el("div", "me-actions");
    var reportSel = select(
      winners.map(function (r) { return { value: r.name, label: r.name }; }),
      state.selectedReport,
    );
    if (winners.length && !winners.some(function (r) { return r.name === state.selectedReport; })) {
      state.selectedReport = winners[0].name;
      reportSel.value = state.selectedReport;
    }
    reportSel.addEventListener("change", function () { state.selectedReport = reportSel.value; });
    var btn = el("button", "btn btn-primary", uiT("me_record_notes", "Record in apply-notes"));
    btn.type = "button";
    btn.disabled = !winners.length;
    btn.addEventListener("click", function () {
      if (btn.disabled) return;
      status.textContent = uiT("me_writing_note", "Writing note.");
      fetch("/api/model-eval/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project: project(), report: state.selectedReport }),
      }).then(function (r) { return r.json(); }).then(function (result) {
        status.textContent = result.ok
          ? uiT("me_noted_in", "Noted in {path}. Config unchanged.")
            .replace("{path}", result.notes || "apply-notes.md")
          : (result.error || uiT("me_apply_failed", "Apply failed."));
      });
    });
    line.appendChild(el("span", "", uiT("me_ack_winners", "Acknowledge the Winners in")));
    line.appendChild(reportSel);
    line.appendChild(btn);
    apply.appendChild(line);
    apply.appendChild(el(
      "p", "field-hint",
      winners.length
        ? uiT(
          "me_apply_note_hint",
          "Only writes a dated note. To change a model, edit [locales.models] in Settings (ADR-12).",
        )
        : uiT("me_apply_disabled", "Disabled until a report has a Winners section."),
    ));
    panel.appendChild(apply);
  }

  function load() {
    var query = project() ? ("?project=" + encodeURIComponent(project())) : "";
    fetch("/api/model-eval" + query).then(function (r) { return r.json(); }).then(function (data) {
      state.data = data;
      status.textContent = "";
      paint();
    }).catch(function () {
      status.textContent = uiT("me_load_failed", "Could not load bakeoff data.");
    });
  }

  paintTabs();
  load();
})();
