(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "analysis" || !root) return;

  var headActions = document.getElementById("an-head-actions");
  var subEl = document.getElementById("an-sub");
  var report = null;
  var loadToken = 0;

  function t(key, fallback, vars) {
    var loc = window.uiLocale;
    var value = loc && loc.t ? loc.t(key) : key;
    var text = value && value !== key ? value : fallback;
    Object.keys(vars || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(vars[name]));
    });
    return text;
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

  function help(topic) {
    if (!window.LLMHelp || !window.LLMHelp.helpBtn) return null;
    return window.LLMHelp.helpBtn("analysis:" + topic);
  }

  function fmtNum(n) {
    return Number(n || 0).toLocaleString();
  }

  function fmtUsd(n) {
    return "$" + Number(n || 0).toFixed(2);
  }

  function fmtEffort(min) {
    if (min == null || min === 0) return "—";
    if (min < 1) return "< 1 " + t("an_min_unit", "min");
    if (min < 60) return "~" + Math.round(min) + " " + t("an_min_unit", "min");
    return "~" + Math.floor(min / 60) + " h " + Math.round(min % 60) + " " + t("an_min_unit", "min");
  }

  function pct(part, whole) {
    return whole ? Math.round((part / whole) * 100) : 0;
  }

  // ---- header -----------------------------------------------------------

  var nsSelect = el("select", "pg-select");
  nsSelect.id = "an-namespace";
  nsSelect.setAttribute("aria-label", t("an_ns_label", "Namespace"));
  var reBtn = el("button", "btn", t("an_reanalyze", "↻ Re-analyze"));
  reBtn.type = "button";
  var exportBtn = el("button", "btn", t("an_export", "↓ Export report"));
  exportBtn.type = "button";
  exportBtn.disabled = true;
  if (headActions) {
    headActions.appendChild(nsSelect);
    headActions.appendChild(reBtn);
    headActions.appendChild(exportBtn);
  }
  if (subEl) {
    subEl.textContent = t(
      "an_sub",
      "Word count breakdown, TM leverage, estimated effort and cost — before running translate",
    );
    var subHelp = help("general");
    if (subHelp) subEl.appendChild(subHelp);
  }

  var body = el("div", "an");
  root.replaceChildren(body);

  // ---- pieces -----------------------------------------------------------

  function card(label, value, sub) {
    var node = el("div", "pg-card");
    node.appendChild(el("div", "pg-label", label));
    node.appendChild(el("div", "pg-value", value));
    if (sub) node.appendChild(el("div", "pg-subline", sub));
    return node;
  }

  function panel(titleText, topic, noteText) {
    var node = el("section", "pg-panel");
    var head = el("div", "pg-panel-head");
    var title = el("h2", "an-h2", titleText);
    var btn = topic ? help(topic) : null;
    if (btn) title.appendChild(btn);
    head.appendChild(title);
    if (noteText) head.appendChild(el("span", "pg-note", noteText));
    node.appendChild(head);
    return node;
  }

  function bar(row) {
    var wrap = el("div", "an-bar-wrap");
    var node = el("div", "pg-bar an-bar");
    var parts = [
      ["an-seg-exact", row.exact],
      ["an-seg-fh", row.fuzzyHigh],
      ["an-seg-fl", row.fuzzyLow],
      ["an-seg-none", row.noMatch],
    ];
    parts.forEach(function (part) {
      if (!part[1] || !row.due) return;
      var seg = el("i", part[0]);
      seg.style.width = (part[1] / row.due * 100) + "%";
      node.appendChild(seg);
    });
    wrap.appendChild(node);
    return wrap;
  }

  function costCell(row) {
    if (row.priceError) return t("an_price_missing", "not recorded");
    if (row.maxUsd == null) return "—";
    return row.cloud ? "~" + fmtUsd(row.maxUsd) : fmtUsd(0);
  }

  function legend() {
    var node = el("div", "pg-legend");
    [
      ["an-seg-exact", t("an_col_exact", "100%")],
      ["an-seg-fh", t("an_col_fh", "Fuzzy 75–99")],
      ["an-seg-fl", t("an_col_fl", "Fuzzy 55–74")],
      ["an-seg-none", t("an_col_none", "No match")],
    ].forEach(function (item) {
      var span = el("span", "");
      span.appendChild(el("i", item[0]));
      span.appendChild(document.createTextNode(item[1]));
      node.appendChild(span);
    });
    return node;
  }

  // ---- sections ---------------------------------------------------------

  function cardsSection(data) {
    var a = data.active;
    var fuzzy = a.fuzzyHigh + a.fuzzyLow;
    var cards = el("div", "pg-cards an-cards");
    cards.appendChild(card(
      t("an_c_strings", "Total source strings"),
      fmtNum(data.sourceStrings),
      t("an_c_strings_sub", "{words} words", { words: fmtNum(data.sourceWords) }),
    ));
    cards.appendChild(card(
      t("an_c_exact", "100% TM matches"),
      fmtNum(a.exact),
      t("an_c_pct_due", "{pct}% of due strings", { pct: pct(a.exact, a.due) }),
    ));
    cards.appendChild(card(
      t("an_c_fuzzy", "Fuzzy matches"),
      data.tmBands === "exact" ? "—" : fmtNum(fuzzy),
      data.tmBands === "exact"
        ? t("an_c_fuzzy_skip", "exact TM only (fast path)")
        : t("an_c_pct_due", "{pct}% of due strings", { pct: pct(fuzzy, a.due) }),
    ));
    cards.appendChild(card(
      t("an_c_new", "New / no match"),
      fmtNum(a.noMatch),
      t("an_c_pct_due", "{pct}% of due strings", { pct: pct(a.noMatch, a.due) }),
    ));
    var anyCloud = data.locales.some(function (r) { return !r.frozen && r.cloud; });
    cards.appendChild(card(
      t("an_c_cost", "Est. cloud cost"),
      a.maxUsd == null ? "—" : fmtUsd(a.maxUsd),
      anyCloud ? t("an_c_cost_max", "max ceiling") : t("an_c_cost_local", "local — no cloud cost"),
    ));
    return cards;
  }

  function tableSection(data) {
    var node = panel(
      t("an_t_title", "Leverage by locale"),
      "breakdown",
      t("an_t_note", "Counts cover strings that are due: missing, empty or stale"),
    );
    var inner = el("div", "an-legend-pad");
    inner.appendChild(legend());
    node.appendChild(inner);
    var table = el("table", "pg-table an-table");
    var thead = el("thead", "");
    var hr = el("tr", "");
    [
      ["an_col_locale", "Locale", ""],
      ["an_col_due", "Due", "r"],
      ["an_col_exact", "100%", "r"],
      ["an_col_fh", "Fuzzy 75–99", "r"],
      ["an_col_fl", "Fuzzy 55–74", "r"],
      ["an_col_none", "No match", "r"],
      ["an_col_bar", "Leverage", ""],
      ["an_col_effort", "Est. effort", "r"],
      ["an_col_cost", "Est. cloud cost", "r"],
    ].forEach(function (col) {
      hr.appendChild(el("th", col[2], t(col[0], col[1])));
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = el("tbody", "");
    data.locales.forEach(function (row) {
      var tr = el("tr", row.frozen ? "pg-frozen is-frozen" : "");
      var loc = el("td", "");
      loc.appendChild(el("span", "pg-loc", row.locale));
      if (row.frozen) loc.appendChild(el("span", "an-tag", t("an_frozen", "frozen")));
      if (row.asap) loc.appendChild(el("span", "an-tag an-tag-asap", t("an_asap", "ASAP")));
      tr.appendChild(loc);
      tr.appendChild(el("td", "r", fmtNum(row.due)));
      [row.exact, row.fuzzyHigh, row.fuzzyLow, row.noMatch].forEach(function (n, i) {
        tr.appendChild(el("td", i === 3 && n > 0 ? "r an-c-none" : "r", fmtNum(n)));
      });
      var barCell = el("td", "");
      barCell.appendChild(bar(row));
      tr.appendChild(barCell);
      var effort = el("td", "r", fmtEffort(row.effortMin));
      if (row.effortMin == null && row.due - row.exact > 0) {
        effort.title = t("an_no_history", "No measured runs yet for this locale");
      }
      tr.appendChild(effort);
      tr.appendChild(el("td", "r", costCell(row)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var a = data.active;
    var tfoot = el("tfoot", "");
    var fr = el("tr", "an-total");
    fr.appendChild(el("td", "", t("an_total", "Active locales total")));
    fr.appendChild(el("td", "r", fmtNum(a.due)));
    [a.exact, a.fuzzyHigh, a.fuzzyLow, a.noMatch].forEach(function (n) {
      fr.appendChild(el("td", "r", fmtNum(n)));
    });
    fr.appendChild(el("td", "", ""));
    fr.appendChild(el("td", "r", fmtEffort(a.effortMin)));
    fr.appendChild(el("td", "r", a.maxUsd == null ? "—" : fmtUsd(a.maxUsd)));
    tfoot.appendChild(fr);
    table.appendChild(tfoot);
    var scroll = el("div", "an-scroll");
    scroll.appendChild(table);
    node.appendChild(scroll);
    return node;
  }

  function repetitionsSection(data) {
    var rep = data.repetitions;
    var node = panel(t("an_rep_title", "Internal repetitions"), "repetitions");
    if (!rep.top.length) {
      node.appendChild(el("div", "pg-empty", t("an_rep_none", "No repeated source strings.")));
      return node;
    }
    rep.top.forEach(function (item) {
      var row = el("div", "an-rep-row");
      var text = el("div", "an-rep-text");
      text.appendChild(el("div", "pg-mono an-rep-key", item.key));
      text.appendChild(el("div", "pg-faint", item.source));
      row.appendChild(text);
      if (item.namespaces > 1) {
        row.appendChild(el(
          "span", "pg-note",
          t("an_rep_in", "appears in {n} namespaces", { n: item.namespaces }),
        ));
      }
      row.appendChild(el("span", "pg-prio", "×" + item.count));
      node.appendChild(row);
    });
    node.appendChild(el("div", "pg-foot", t(
      "an_rep_note",
      "{n} repeated sources — each is translated separately in a run; "
        + "saving one in the editor copies it to its empty twins.",
      { n: fmtNum(rep.total) },
    )));
    return node;
  }

  function providersSection(data) {
    var node = panel(t("an_prov_title", "Provider assignment for this run"), "providers");
    var active = data.locales.filter(function (r) { return !r.frozen; });
    var groups = {};
    active.forEach(function (row) {
      var key = row.provider.id + "|" + row.provider.model;
      (groups[key] = groups[key] || { rows: [], first: row }).rows.push(row);
    });
    Object.keys(groups).forEach(function (key) {
      var group = groups[key];
      var first = group.first;
      var row = el("div", "an-prov-row");
      row.appendChild(el("span", "pg-loc", group.rows.map(function (r) { return r.locale; }).join(" · ")));
      row.appendChild(el(
        "span", "",
        first.provider.id + " / " + first.provider.model + " (" + first.provider.kind + ")",
      ));
      var usd = group.rows.reduce(function (sum, r) { return sum + (r.maxUsd || 0); }, 0);
      row.appendChild(el(
        "span", "pg-prio " + (first.cloud ? "pg-prio-asap" : ""),
        first.cloud ? "~" + fmtUsd(usd) : fmtUsd(0),
      ));
      node.appendChild(row);
    });
    data.locales.filter(function (r) { return r.frozen; }).forEach(function (r) {
      var row = el("div", "an-prov-row pg-frozen");
      row.appendChild(el("span", "pg-loc", r.locale));
      row.appendChild(el("span", "", t("an_frozen_note", "frozen — excluded from this run")));
      node.appendChild(row);
    });
    var a = data.active;
    var remaining = data.budget.remainingUsd;
    var blocked = active.filter(function (r) { return r.cloudBlocked; });
    var warns = [];
    if (a.maxUsd) {
      var over = a.maxUsd > remaining;
      warns.push(t(
        over ? "an_warn_over" : "an_warn_cost",
        over
          ? "Cloud locales are billed: up to {usd} for this run, above the remaining budget {rem}."
          : "Cloud locales are billed: up to {usd} for this run (remaining budget {rem}).",
        { usd: fmtUsd(a.maxUsd), rem: fmtUsd(remaining) },
      ));
    }
    if (blocked.length) {
      warns.push(t(
        "an_warn_blocked",
        "{locales}: a cloud provider is configured but cloud is off (allow_cloud or budget), so they run locally.",
        { locales: blocked.map(function (r) { return r.locale; }).join(", ") },
      ));
    }
    if (warns.length) {
      var box = el("div", "an-warn");
      warns.forEach(function (text) { box.appendChild(el("p", "", text)); });
      var link = el("a", "", t("an_settings", "Settings →"));
      link.href = "/app/settings";
      box.appendChild(link);
      node.appendChild(box);
    }
    return node;
  }

  function actionSection(data) {
    var a = data.active;
    var node = el("section", "pg-panel an-action");
    var text = el("div", "an-action-text");
    var title = el("h2", "an-h2", t("an_ready", "Ready to run translate?"));
    var btn = help("queue");
    if (btn) title.appendChild(btn);
    text.appendChild(title);
    text.appendChild(el("p", "pg-note", t(
      "an_ready_sub",
      "{locales} · {due} strings · {effort} · {cost}",
      {
        locales: a.locales.join(", ") || "—",
        due: fmtNum(a.due),
        effort: fmtEffort(a.effortMin),
        cost: a.maxUsd == null ? "—" : fmtUsd(a.maxUsd),
      },
    )));
    var status = el("p", "pg-note an-queue-status");
    status.setAttribute("role", "status");
    text.appendChild(status);
    node.appendChild(text);

    var buttons = el("div", "an-action-btns");
    var go = el("a", "btn", t("an_go_ops", "Go to Operations →"));
    var query = "?command=translate&locales=" + encodeURIComponent(a.locales.join(","));
    if (project()) query += "&project=" + encodeURIComponent(project());
    go.href = "/app/operations" + query;
    var queue = el("button", "btn btn-primary", t("an_queue", "Queue translate jobs"));
    queue.type = "button";
    var over = a.maxUsd != null && a.maxUsd > data.budget.remainingUsd;
    if (!a.due || !a.locales.length) {
      queue.disabled = true;
      queue.title = t("an_none_due", "Nothing to translate — no missing, empty or stale strings.");
    } else if (over) {
      queue.disabled = true;
      queue.title = t("an_queue_over", "The cost ceiling exceeds the remaining budget.");
    }
    queue.addEventListener("click", function () {
      var msg = t("an_queue_confirm", "Queue translate for {locales}?", { locales: a.locales.join(", ") });
      if (!window.confirm(msg)) return;
      queue.disabled = true;
      status.textContent = t("an_queueing", "Queueing…");
      var payload = {
        project: project(),
        locales: a.locales,
        submit: true,
        dry_run: false,
      };
      if (nsSelect.value) payload.namespaces = [nsSelect.value];
      fetch("/api/ops/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      }).then(function (res) {
        return res.json().then(function (out) { return { ok: res.ok && out.ok !== false, out: out }; });
      }).then(function (r) {
        status.textContent = r.out.summary || r.out.error
          || (r.ok ? t("an_queued", "Queued.") : t("an_queue_failed", "Could not queue."));
        status.classList.toggle("an-err", !r.ok);
      }).catch(function (err) {
        status.textContent = String(err && err.message ? err.message : err);
        status.classList.add("an-err");
      }).then(function () { queue.disabled = false; });
    });
    buttons.appendChild(go);
    buttons.appendChild(queue);
    node.appendChild(buttons);
    return node;
  }

  function lengthSection(data) {
    var node = panel(
      t("an_len_title", "Length by locale"),
      "",
      t("an_len_sub", "Median character length vs source (translated keys only). Longer languages expand more."),
    );
    var rows = data.lengthByLocale || [];
    if (!rows.length) {
      node.appendChild(el("div", "pg-empty", t("an_len_none", "No translated length samples yet.")));
      return node;
    }
    var table = el("table", "pg-table");
    var hr = el("tr", "");
    [
      [t("an_col_locale", "Locale"), ""],
      [t("an_len_median", "Median ratio"), "r"],
      [t("an_len_mean", "Mean ratio"), "r"],
      [t("an_len_keys", "Keys"), "r"],
    ].forEach(function (col) { hr.appendChild(el("th", col[1], col[0])); });
    var thead = el("thead", "");
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = el("tbody", "");
    rows.forEach(function (row) {
      var tr = el("tr", "");
      tr.appendChild(el("td", "pg-loc", row.locale));
      tr.appendChild(el("td", "r", String(row.medianRatio)));
      tr.appendChild(el("td", "r", String(row.meanRatio)));
      tr.appendChild(el("td", "r", String(row.n)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    node.appendChild(table);
    return node;
  }

  // ---- load / paint / export ---------------------------------------------

  function paint(data) {
    body.replaceChildren();
    if (!data || !data.ok) {
      body.appendChild(el("p", "empty-state", (data && data.error) || t("an_failed", "Analysis failed.")));
      if (data && data.hint) body.appendChild(el("p", "empty-state", data.hint));
      exportBtn.disabled = true;
      return;
    }
    report = data;
    exportBtn.disabled = false;
    if (!nsSelect.options.length || nsSelect.dataset.project !== project()) {
      nsSelect.replaceChildren();
      nsSelect.appendChild(el("option", "", t("an_all_ns", "All namespaces")));
      nsSelect.options[0].value = "";
      (data.namespaces || []).forEach(function (name) {
        var opt = el("option", "", name);
        opt.value = name;
        nsSelect.appendChild(opt);
      });
      nsSelect.dataset.project = project();
    }
    nsSelect.value = data.namespace || "";
    body.appendChild(cardsSection(data));
    if (!data.active.due) {
      body.appendChild(el("p", "empty-state", t(
        "an_none_due", "Nothing to translate — no missing, empty or stale strings.",
      )));
    }
    body.appendChild(tableSection(data));
    var pair = el("div", "an-pair");
    pair.appendChild(repetitionsSection(data));
    pair.appendChild(providersSection(data));
    body.appendChild(pair);
    body.appendChild(actionSection(data));
    body.appendChild(lengthSection(data));
  }

  function reportQuery(fresh, bands) {
    var q = {};
    if (project()) q.project = project();
    if (nsSelect.value) q.namespace = nsSelect.value;
    if (fresh === true) q.refresh = "1";
    if (!bands) q.bands = "0";
    return q;
  }

  function reportUrl(fresh, bands) {
    var q = reportQuery(fresh, bands);
    var query = Object.keys(q).map(function (k) {
      return encodeURIComponent(k) + "=" + encodeURIComponent(q[k]);
    });
    return "/api/analysis/report" + (query.length ? "?" + query.join("&") : "");
  }

  function fetchReport(fresh, bands) {
    if (window.LLMApi && LLMApi.apiGet) {
      return LLMApi.apiGet("/api/analysis/report", reportQuery(fresh, bands));
    }
    return fetch(reportUrl(fresh, bands), { credentials: "same-origin" })
      .then(function (res) { return res.json(); });
  }

  function load(fresh) {
    var token = ++loadToken;
    var paintedFull = false;
    body.replaceChildren(el("p", "pg-loading", t("an_loading", "Analyzing…")));
    // Two requests on purpose: bands=0 paints due/effort/cost without TM
    // near-match; bands=1 (default) fills exact/fuzzy bars. Fired in parallel
    // so wall time is max(phase), not sum — they share a server-side due cache.
    var gaps = fetchReport(fresh, false).then(function (data) {
        // Do not clobber a full report that arrived first.
        if (token === loadToken && !paintedFull) paint(data);
        return data;
      });
    var full = fetchReport(fresh, true).then(function (data) {
        if (token === loadToken) {
          paintedFull = true;
          paint(data);
        }
        return data;
      });
    Promise.all([gaps, full]).catch(function (err) {
      if (token === loadToken) {
        paint({ ok: false, error: String(err && err.message ? err.message : err) });
      }
    });
  }

  function csvCell(value) {
    var text = String(value == null ? "" : value);
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function exportCsv() {
    if (!report) return;
    var head = ["locale", "frozen", "due", "words", "exact", "fuzzy_75_99", "fuzzy_55_74",
      "no_match", "effort_min", "max_usd", "provider", "model"];
    var lines = [head.join(",")];
    report.locales.forEach(function (r) {
      lines.push([
        r.locale, r.frozen, r.due, r.words, r.exact, r.fuzzyHigh, r.fuzzyLow, r.noMatch,
        r.effortMin == null ? "" : r.effortMin, r.maxUsd == null ? "" : r.maxUsd,
        r.provider.id, r.provider.model,
      ].map(csvCell).join(","));
    });
    var link = el("a", "");
    link.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
    link.download = "analysis-" + (project() || "project") + ".csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  reBtn.addEventListener("click", function () { load(true); });
  nsSelect.addEventListener("change", function () { load(); });
  exportBtn.addEventListener("click", exportCsv);
  if (window.LLMApi && LLMApi.onProjectReady) {
    LLMApi.onProjectReady(function () {
      nsSelect.replaceChildren();
      load();
    });
  } else {
    var projectSelect = document.getElementById("project-select");
    if (projectSelect) {
      projectSelect.addEventListener("change", function () {
        nsSelect.replaceChildren();
        load();
      });
    }
    load();
  }
})();
