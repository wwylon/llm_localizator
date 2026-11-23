(function () {
  var body = document.getElementById("page-body");
  var select = document.getElementById("project-select");
  if (!body || !select) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function tabLabels() {
    return {
      concordance: uiT("tm_tab_concordance", "Concordance search"),
      leverage: uiT("tm_tab_leverage", "Leverage report"),
      browse: uiT("tm_tab_browse", "Browse TM"),
    };
  }

  var state = {
    project: "",
    tab: "concordance",
    locale: "",
    locales: [],
    source: true,
    target: true,
    leverage: null,
    browseSort: { key: "source", dir: 1 },
    browseRows: [],
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function headers(json) {
    var extra = json ? { "Content-Type": "application/json" } : undefined;
    if (window.LLMApi && LLMApi.authHeaders) return LLMApi.authHeaders(extra);
    var out = extra ? Object.assign({}, extra) : {};
    if (window.__LLM_TOKEN) out["X-LLM-Token"] = window.__LLM_TOKEN;
    return out;
  }

  function query(extra) {
    var q = new URLSearchParams();
    q.set("project", state.project);
    Object.keys(extra || {}).forEach(function (key) {
      if (extra[key] != null && extra[key] !== "") q.set(key, extra[key]);
    });
    return q.toString();
  }

  function fmtNum(n) {
    return Number(n || 0).toLocaleString();
  }

  function pctOf(part, whole) {
    if (!whole) return 0;
    return Math.round((100 * part) / whole);
  }

  function scoreText(value) {
    if (value == null || value === "") return "—";
    var n = Number(value);
    if (Number.isNaN(n)) return String(value);
    return n.toFixed(2);
  }

  function shortDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function statusClass(status) {
    return "tm-status tm-status-" + (status || "machine");
  }

  function statusLabel(status) {
    var id = status || "machine";
    var key = "filter" + id.charAt(0).toUpperCase() + id.slice(1);
    return uiT(key, id);
  }

  function countEntries(n) {
    return uiT(n === 1 ? "tm_n_entries_one" : "tm_n_entries", n === 1 ? "{n} entry" : "{n} entries")
      .replace("{n}", fmtNum(n));
  }

  function setSubtitle() {
    var sub = document.getElementById("tm-sub");
    if (!sub) return;
    var lev = state.leverage || {};
    var entries = lev.tmEntries || 0;
    var locales = lev.tmLocales || 0;
    sub.textContent = uiT("tm_sub", "{entries} across {locales}")
      .replace("{entries}", countEntries(entries))
      .replace("{locales}", uiT(locales === 1 ? "tm_n_locales_one" : "tm_n_locales",
        locales === 1 ? "{n} locale" : "{n} locales").replace("{n}", fmtNum(locales)))
      + " ";
    if (window.LLMHelp) {
      var help = window.LLMHelp.helpBtn("tm:" + state.tab);
      help.addEventListener("click", function (ev) {
        ev.stopImmediatePropagation();
        window.LLMHelp.showHelp("tm:" + state.tab);
      }, true);
      sub.appendChild(help);
    }
  }

  function keyCell(row, extra) {
    var label = row.key ? (row.namespace ? row.namespace + "." : "") + row.key : "—";
    return el("td", "tm-mono tm-key" + (row.key ? "" : " is-none") + (extra || ""), label);
  }

  function scoreCell(value, extra) {
    var n = Number(value);
    var tone = value == null || value === "" || Number.isNaN(n) ? "" : n >= 0.8 ? " tm-score-hi" : " tm-score-mid";
    return el("td", "tm-mono" + tone + (extra || ""), scoreText(value));
  }

  var scope = (window.LLMApi && LLMApi.requestScope) ? LLMApi.requestScope() : null;

  function load() {
    state.project = select.value;
    body.replaceChildren(el("p", "empty-state", uiT("dash_loading", "Loading…")));
    var token = scope ? scope.next() : null;
    var getLite = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/overview-lite", { project: state.project }, token ? { signal: token.signal } : {})
      : fetch("/api/overview-lite?" + query()).then(function (r) { return r.json(); });
    // Paint tabs as soon as locales are known; leverage fills in after
    // (it walks coverage and can take seconds on a large project).
    getLite.then(function (lite) {
        if (scope && token && !scope.isCurrent(token)) return;
        state.locales = (lite.activeLocales || []).concat(lite.frozenLocales || []);
        if (!state.locale || state.locales.indexOf(state.locale) < 0) {
          state.locale = state.locales[0] || "";
        }
        setSubtitle();
        render();
        return refreshLeverage(token).then(function () {
          if (scope && token && !scope.isCurrent(token)) return;
          if (state.tab === "leverage") render();
          else setSubtitle();
        });
      }).catch(function (err) {
        if (err && err.name === "AbortError") return;
        body.replaceChildren(el("p", "empty-state", String(err.message || err)));
        var sub = document.getElementById("tm-sub");
        if (sub) sub.textContent = "";
      });
  }

  function refreshLeverage(token) {
    var getLev = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/tm/leverage", { project: state.project, locale: state.locale }, token ? { signal: token.signal } : {})
      : fetch("/api/tm/leverage?" + query()).then(function (r) { return r.json(); });
    return getLev.then(function (payload) {
        if (scope && token && !scope.isCurrent(token)) return;
        state.leverage = payload || {};
        setSubtitle();
      });
  }

  function render() {
    body.replaceChildren();
    var tabs = el("div", "tabs tm-tabs");
    ["concordance", "leverage", "browse"].forEach(function (name) {
      var button = el(
        "button",
        "tab-btn" + (state.tab === name ? " is-active" : ""),
        tabLabels()[name],
      );
      button.type = "button";
      button.addEventListener("click", function () {
        state.tab = name;
        render();
        setSubtitle();
      });
      tabs.appendChild(button);
    });
    var slot = document.getElementById("tm-tabs");
    if (slot) slot.replaceChildren(tabs);
    else body.appendChild(tabs);

    var panel = el("div", "tab-panel tm-panel");
    body.appendChild(panel);
    if (state.tab === "leverage") return paintLeverage(panel);
    if (state.tab === "browse") return paintBrowse(panel);
    paintConcordance(panel);
  }

  function localeSelect(locales, value) {
    var node = document.createElement("select");
    node.setAttribute("aria-label", uiT("rev_field_locale", "Locale"));
    locales.forEach(function (locale) {
      var option = el("option", "", locale);
      option.value = locale;
      if (locale === value) option.selected = true;
      node.appendChild(option);
    });
    return node;
  }

  function labeled(text, input) {
    var label = el("label", "field", text);
    label.insertBefore(input, label.firstChild);
    return label;
  }

  function highlight(text, needle) {
    var span = document.createElement("span");
    var raw = text == null ? "" : String(text);
    var q = (needle || "").trim();
    if (!q) {
      span.textContent = raw;
      return span;
    }
    var lower = raw.toLowerCase();
    var find = q.toLowerCase();
    var start = 0;
    var idx = lower.indexOf(find);
    if (idx < 0) {
      span.textContent = raw;
      return span;
    }
    while (idx >= 0) {
      if (idx > start) span.appendChild(document.createTextNode(raw.slice(start, idx)));
      var strong = el("strong", "", raw.slice(idx, idx + find.length));
      span.appendChild(strong);
      start = idx + find.length;
      idx = lower.indexOf(find, start);
    }
    if (start < raw.length) span.appendChild(document.createTextNode(raw.slice(start)));
    return span;
  }

  function useButton(translation, disabled) {
    var use = el("button", "btn tm-use-btn", uiT("tm_use", "Use →"));
    use.type = "button";
    if (disabled) {
      use.disabled = true;
      return use;
    }
    use.addEventListener("click", function () {
      try { sessionStorage.setItem("llm_tm_insert", translation || ""); } catch (err) { /* ignore */ }
      if (window.llmNavigate) window.llmNavigate("/app/editor");
      else window.location.href = "/app/editor";
    });
    return use;
  }

  function paintConcordance(panel) {
    var card = el("div", "tm-search-card");
    card.appendChild(el("div", "tm-section-label", uiT("tm_search_title", "Search translation memory")));
    var bar = el("div", "tm-search-row");
    var localesBox = localeSelect(state.locales, state.locale);
    var input = document.createElement("input");
    input.type = "search";
    input.placeholder = uiT("tm_query_ph", "e.g. board, save changes, {name}…");
    input.setAttribute("aria-label", uiT("tm_query_aria", "Concordance query"));
    input.className = "tm-query";
    var source = document.createElement("input");
    source.type = "checkbox";
    source.checked = state.source;
    var target = document.createElement("input");
    target.type = "checkbox";
    target.checked = state.target;
    var run = el("button", "btn btn-primary", uiT("ed_search_btn", "Search"));
    run.type = "button";
    bar.appendChild(input);
    bar.appendChild(localesBox);
    var scope = el("div", "tm-scope");
    scope.appendChild(labeled(uiT("tm_source", "Source"), source));
    scope.appendChild(labeled(uiT("tm_target", "Target"), target));
    bar.appendChild(scope);
    bar.appendChild(run);
    card.appendChild(bar);
    panel.appendChild(card);

    var results = el("div", "tm-results");
    results.id = "tm-results";
    results.appendChild(el("p", "excerpt", uiT("tm_enter_query", "Enter a query and search.")));
    panel.appendChild(results);

    function go() {
      state.locale = localesBox.value;
      state.source = source.checked;
      state.target = target.checked;
      var q = input.value.trim();
      results.replaceChildren(el("p", "excerpt", uiT("tm_searching", "Searching…")));
      var concQuery = {
        project: state.project,
        locale: state.locale,
        query: q,
        source: source.checked ? "1" : "0",
        target: target.checked ? "1" : "0",
      };
      var getConc = (window.LLMApi && LLMApi.apiGet)
        ? LLMApi.apiGet("/api/tm/concordance", concQuery)
        : fetch("/api/tm/concordance?" + query({
            locale: state.locale,
            query: q,
            source: source.checked ? "1" : "0",
            target: target.checked ? "1" : "0",
          })).then(function (response) { return response.json(); });
      getConc.then(function (payload) {
        var matches = (payload.data && payload.data.matches) || [];
        results.replaceChildren();
        var heading = el(
          "div",
          "tm-section-label",
          (matches.length === 1
            ? uiT("tm_results_one", "Results — {n} match")
            : uiT("tm_results_many", "Results — {n} matches"))
            .replace("{n}", String(matches.length))
            + (q
              ? uiT("tm_results_for", ' for "{q}"').replace("{q}", q)
              : ""),
        );
        results.appendChild(heading);
        if (!matches.length) {
          results.appendChild(el("p", "excerpt", uiT("tm_no_matches", "No matches.")));
          return;
        }
        results.appendChild(concordanceTable(matches, q, state.locale));
      }).catch(function (err) {
        results.replaceChildren(el("p", "search-error", String(err.message || err)));
      });
    }

    run.addEventListener("click", go);
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") go();
    });
  }

  function concordanceTable(matches, needle, locale) {
    var table = el("table", "tm-table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    [
      uiT("tm_col_match", "Match"),
      uiT("tm_col_source_en", "Source (en)"),
      uiT("tm_col_translation", "Translation ({locale})").replace("{locale}", locale),
      uiT("tm_col_key", "Key"),
      uiT("tm_col_score", "Score"),
      uiT("tm_col_status", "Status"),
      "",
    ].forEach(function (label) {
      hr.appendChild(el("th", "", label));
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    matches.forEach(function (hit) {
      var tr = el("tr", hit.superseded ? "is-superseded" : "");
      var pct = hit.matchPct;
      var matchTd = el("td", "tm-match" + (pct >= 100 ? " is-exact" : pct < 80 ? " is-low" : ""),
        (pct != null ? pct : "—") + "%");
      tr.appendChild(matchTd);
      var srcTd = document.createElement("td");
      srcTd.appendChild(highlight(hit.source || "", needle));
      tr.appendChild(srcTd);
      var tgtTd = el("td", "tm-target");
      tgtTd.appendChild(highlight(hit.translation || "", state.target ? needle : ""));
      if (hit.superseded) {
        tgtTd.appendChild(document.createTextNode(" "));
        tgtTd.appendChild(el("span", "tm-superseded-mark", uiT("tm_superseded", "(superseded)")));
      }
      tr.appendChild(tgtTd);
      tr.appendChild(keyCell(hit));
      tr.appendChild(scoreCell(hit.quality));
      var statusTd = document.createElement("td");
      statusTd.appendChild(el("span", statusClass(hit.status), statusLabel(hit.status)));
      tr.appendChild(statusTd);
      var useTd = document.createElement("td");
      useTd.appendChild(useButton(hit.translation, !!hit.superseded));
      tr.appendChild(useTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function paintLeverage(panel) {
    var lev = state.leverage || {};
    if (!lev.locales) {
      panel.appendChild(el("p", "empty-state", uiT("tm_loading_leverage", "Loading leverage…")));
      return;
    }
    var totals = lev.totals || {};
    var classified = totals.classified || 0;
    var agentImport = (totals.agent_edited || 0) + (totals.imported || 0);

    var cards = el("div", "tm-summary-grid");
    cards.appendChild(summaryCard(
      uiT("tm_reuse", "TM reuse"),
      pctOf(totals.tm_reused || 0, classified),
      totals.tm_reused || 0,
      "accent",
    ));
    cards.appendChild(summaryCard(
      uiT("tm_llm_gen", "LLM generated"),
      pctOf(totals.llm_generated || 0, classified),
      totals.llm_generated || 0,
      "",
    ));
    cards.appendChild(summaryCard(
      uiT("tm_human", "Human edited"),
      pctOf(totals.human_edited || 0, classified),
      totals.human_edited || 0,
      "human",
    ));
    cards.appendChild(summaryCard(
      uiT("tm_agent_imp", "Agent / imported"),
      pctOf(agentImport, classified),
      agentImport,
      "",
    ));
    panel.appendChild(cards);

    var wrap = el("div", "tm-leverage-wrap");
    wrap.appendChild(el("div", "tm-section-label", uiT("an_t_title", "Leverage by locale")));
    var table = el("table", "tm-table tm-leverage-table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    [uiT("rev_field_locale", "Locale"), uiT("tm_translated", "Translated"), uiT("tm_reuse", "TM reuse"), uiT("tm_llm_gen", "LLM generated"), uiT("tm_human", "Human edited"), uiT("tm_agent_import", "Agent / import"), uiT("tm_breakdown", "Breakdown")]
      .forEach(function (label, i) {
        var th = el("th", i >= 2 && i <= 5 ? "tm-num" : "", label);
        hr.appendChild(th);
      });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    (lev.locales || []).forEach(function (row) {
      var bucket = (row.tm_reused || 0) + (row.llm_generated || 0)
        + (row.human_edited || 0) + (row.agent_edited || 0) + (row.imported || 0);
      var agentRow = (row.agent_edited || 0) + (row.imported || 0);
      var tr = document.createElement("tr");
      if (row.frozen) tr.className = "is-frozen";
      var locTd = document.createElement("td");
      locTd.appendChild(el("span", "tm-mono tm-locale-code", row.locale));
      if (row.frozen) locTd.appendChild(el("span", "tm-frozen-mark", " frozen"));
      tr.appendChild(locTd);
      tr.appendChild(el("td", "tm-mono", fmtNum(row.translated)));
      tr.appendChild(el("td", "tm-num tm-mono", pctOf(row.tm_reused || 0, bucket) + "%"));
      tr.appendChild(el("td", "tm-num tm-mono", pctOf(row.llm_generated || 0, bucket) + "%"));
      tr.appendChild(el("td", "tm-num tm-mono", pctOf(row.human_edited || 0, bucket) + "%"));
      tr.appendChild(el("td", "tm-num tm-mono", pctOf(agentRow, bucket) + "%"));
      var barTd = document.createElement("td");
      barTd.appendChild(stackedBar({
        tm: row.tm_reused || 0,
        llm: row.llm_generated || 0,
        human: row.human_edited || 0,
        other: agentRow,
        total: bucket,
      }));
      tr.appendChild(barTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    var legend = el("div", "tm-legend");
    [
      ["tm", "tm_legend_tm", "TM reuse (cheap, consistent)"],
      ["llm", "tm_legend_llm", "LLM generated"],
      ["human", "tm_legend_human", "Human edited"],
      ["other", "tm_legend_other", "Agent / import"],
    ].forEach(function (item) {
      var itemEl = el("span", "tm-legend-item");
      itemEl.appendChild(el("span", "tm-legend-swatch tm-bar-seg-" + item[0]));
      itemEl.appendChild(document.createTextNode(uiT(item[1], item[2])));
      legend.appendChild(itemEl);
    });
    wrap.appendChild(legend);
    panel.appendChild(wrap);
  }

  function summaryCard(label, pct, count, tone) {
    var card = el("div", "tm-summary-card");
    card.appendChild(el("div", "tm-section-label", label));
    card.appendChild(el("div", "tm-summary-pct" + (tone ? " is-" + tone : ""), pct + "%"));
    card.appendChild(el(
      "div",
      "tm-summary-sub",
      fmtNum(count) + " " + (count === 1
        ? uiT("tm_pair_one", "string-locale pair")
        : uiT("tm_pair_many", "string-locale pairs")),
    ));
    return card;
  }

  function stackedBar(parts) {
    var bar = el("div", "tm-bar");
    var total = parts.total || 0;
    [["tm", parts.tm], ["llm", parts.llm], ["human", parts.human], ["other", parts.other]]
      .forEach(function (pair) {
        if (!pair[1] || !total) return;
        var seg = el("div", "tm-bar-seg tm-bar-seg-" + pair[0]);
        seg.style.width = pctOf(pair[1], total) + "%";
        bar.appendChild(seg);
      });
    if (!bar.childNodes.length) bar.appendChild(el("div", "tm-bar-empty"));
    return bar;
  }

  function paintBrowse(panel) {
    var bar = el("div", "tm-browse-toolbar");
    var localesBox = localeSelect(state.locales, state.locale);
    var provider = document.createElement("select");
    provider.setAttribute("aria-label", uiT("tm_provider", "Provider"));
    function fillProviders(list) {
      var current = provider.value;
      provider.replaceChildren();
      var all = el("option", "", uiT("tm_all_providers", "all providers"));
      all.value = "";
      provider.appendChild(all);
      (list || []).forEach(function (name) {
        var opt = el("option", "", name);
        opt.value = name;
        provider.appendChild(opt);
      });
      provider.value = current;
    }
    fillProviders([]);
    var text = document.createElement("input");
    text.type = "search";
    text.placeholder = uiT("tm_filter_ph", "filter…");
    text.setAttribute("aria-label", uiT("tm_text", "Text"));
    var count = el("span", "tm-browse-count", "");
    var exportBtn = el("button", "btn", uiT("tm_export", "Export TMX"));
    exportBtn.type = "button";
    exportBtn.addEventListener("click", function () {
      openExport(localesBox.value);
    });
    bar.appendChild(localesBox);
    bar.appendChild(provider);
    bar.appendChild(text);
    bar.appendChild(count);
    var spacer = el("div", "tm-toolbar-spacer");
    bar.appendChild(spacer);
    bar.appendChild(exportBtn);
    panel.appendChild(bar);

    var tableHost = el("div", "tm-browse-scroll");
    panel.appendChild(tableHost);

    function go() {
      state.locale = localesBox.value;
      tableHost.replaceChildren(el("p", "excerpt", uiT("dash_loading", "Loading…")));
      var browseQuery = {
        project: state.project,
        locale: state.locale,
        provider: provider.value,
        q: text.value,
        limit: "250",
      };
      var getBrowse = (window.LLMApi && LLMApi.apiGet)
        ? LLMApi.apiGet("/api/tm/browse", browseQuery)
        : fetch("/api/tm/browse?" + query({
            locale: state.locale,
            provider: provider.value,
            q: text.value,
            limit: "250",
          })).then(function (response) { return response.json(); });
      getBrowse.then(function (payload) {
        state.browseRows = payload.rows || [];
        fillProviders(payload.providers);
        count.textContent = countEntries(state.browseRows.length);
        tableHost.replaceChildren(browseTable(state.browseRows, state.locale));
      }).catch(function (err) {
        tableHost.replaceChildren(el("p", "search-error", String(err.message || err)));
      });
    }

    localesBox.addEventListener("change", go);
    provider.addEventListener("change", go);
    text.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") go();
    });
    go();
  }

  function browseTable(rows, locale) {
    var sorted = rows.slice().sort(function (a, b) {
      var key = state.browseSort.key;
      var av = a[key];
      var bv = b[key];
      if (key === "quality") {
        av = av == null ? -1 : Number(av);
        bv = bv == null ? -1 : Number(bv);
      } else {
        av = (av == null ? "" : String(av)).toLowerCase();
        bv = (bv == null ? "" : String(bv)).toLowerCase();
      }
      if (av < bv) return -1 * state.browseSort.dir;
      if (av > bv) return 1 * state.browseSort.dir;
      return 0;
    });

    var table = el("table", "tm-table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    var cols = [
      { key: "source", label: uiT("tm_col_source_en", "Source (en)") },
      { key: "translation",
        label: uiT("tm_col_translation", "Translation ({locale})").replace("{locale}", locale) },
      { key: "namespace", label: uiT("tm_col_namespace", "Namespace") },
      { key: "quality", label: uiT("tm_col_score", "Score") },
      { key: "provider", label: uiT("tm_provider", "Provider") },
      { key: "status", label: uiT("tm_col_status", "Status") },
      { key: "createdAt", label: uiT("tm_col_created", "Created") },
    ];
    cols.forEach(function (col) {
      var th = el("th", "tm-sortable", col.label);
      th.addEventListener("click", function () {
        if (state.browseSort.key === col.key) {
          state.browseSort.dir *= -1;
        } else {
          state.browseSort.key = col.key;
          state.browseSort.dir = 1;
        }
        var host = table.parentNode;
        if (host) host.replaceChildren(browseTable(state.browseRows, locale));
      });
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    sorted.forEach(function (row) {
      var tr = el("tr", row.superseded ? "is-superseded" : "");
      tr.appendChild(el("td", "", row.source || ""));
      tr.appendChild(el("td", "tm-target", row.translation || ""));
      tr.appendChild(el("td", "tm-mono tm-key" + (row.namespace ? "" : " is-none"), row.namespace || "—"));
      tr.appendChild(scoreCell(row.quality));
      tr.appendChild(el("td", "", row.provider || row.model || "—"));
      var statusTd = document.createElement("td");
      statusTd.appendChild(el("span", statusClass(row.status), statusLabel(row.status)));
      tr.appendChild(statusTd);
      tr.appendChild(el("td", "tm-muted", shortDate(row.createdAt)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function closeModal(node) {
    if (node && node.parentNode) node.parentNode.removeChild(node);
  }

  function openExport(preferredLocale) {
    var modal = el("div", "modal tm-modal");
    var box = el("div", "modal-body tm-modal-body");
    var h2 = el("h2", "", uiT("tm_export", "Export TMX") + " ");
    if (window.LLMHelp) h2.appendChild(window.LLMHelp.helpBtn("tm:import-export"));
    box.appendChild(h2);
    var field = el("label", "field", uiT("rev_field_locale", "Locale"));
    var localesBox = localeSelect(state.locales, preferredLocale || state.locale);
    field.appendChild(localesBox);
    box.appendChild(field);
    var actions = el("div", "tm-modal-actions");
    var cancel = el("button", "btn", uiT("wf_cancel", "Cancel"));
    cancel.type = "button";
    cancel.addEventListener("click", function () { closeModal(modal); });
    var go = el("button", "btn btn-primary", uiT("tm_export_btn", "Export"));
    go.type = "button";
    go.addEventListener("click", function () {
      var locale = localesBox.value;
      go.disabled = true;
      var getBlob = (window.LLMApi && LLMApi.apiBlob)
        ? LLMApi.apiBlob("/api/tm/export", { project: state.project, locale: locale })
        : fetch("/api/tm/export?" + query({ locale: locale }), {
            headers: headers(false),
            credentials: "same-origin",
          }).then(function (response) {
            if (!response.ok) {
              return response.json().then(function (err) {
                throw new Error(err.error || uiT("tm_export_failed", "Export failed"));
              }, function () { throw new Error(uiT("tm_export_failed", "Export failed")); });
            }
            return response.blob();
          });
      getBlob.then(function (blob) {
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = locale + ".tmx";
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
        closeModal(modal);
      }).catch(function (err) {
        go.disabled = false;
        var note = box.querySelector(".search-error");
        if (!note) { note = el("p", "search-error"); box.insertBefore(note, actions); }
        note.textContent = String(err.message || err);
      });
    });
    actions.appendChild(cancel);
    actions.appendChild(go);
    box.appendChild(actions);
    modal.appendChild(box);
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) closeModal(modal);
    });
    document.body.appendChild(modal);
  }

  function openImport() {
    var modal = el("div", "modal tm-modal");
    var box = el("div", "modal-body tm-modal-body");
    var h2 = el("h2", "", uiT("tm_import", "Import TMX") + " ");
    if (window.LLMHelp) h2.appendChild(window.LLMHelp.helpBtn("tm:import-export"));
    box.appendChild(h2);

    var fileField = el("label", "field", uiT("tm_tmx_file", "TMX file"));
    var fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".tmx,.xml";
    fileField.appendChild(fileInput);
    box.appendChild(fileField);

    var localeField = el("label", "field", uiT("rev_field_locale", "Locale"));
    var localesBox = localeSelect(state.locales, state.locale);
    localeField.appendChild(localesBox);
    box.appendChild(localeField);

    var conflictField = el("label", "field", uiT("tm_conflict", "Conflict resolution"));
    var conflict = document.createElement("select");
    [
      ["skip", uiT("tm_conflict_skip", "Skip existing (keep current TM entries)")],
      ["overwrite-if-higher", uiT("tm_conflict_higher", "Overwrite if imported score is higher")],
      ["always", uiT("tm_conflict_always", "Always overwrite")],
    ].forEach(function (pair) {
      var opt = el("option", "", pair[1]);
      opt.value = pair[0];
      conflict.appendChild(opt);
    });
    conflictField.appendChild(conflict);
    box.appendChild(conflictField);

    var dryWrap = el("label", "field tm-dry-run");
    var dry = document.createElement("input");
    dry.type = "checkbox";
    dry.checked = true;
    dryWrap.appendChild(dry);
    dryWrap.appendChild(document.createTextNode(uiT("tm_dry_run", "Dry run — preview changes without writing")));
    box.appendChild(dryWrap);

    var preview = el("div", "tm-import-preview");
    box.appendChild(preview);

    var actions = el("div", "tm-modal-actions");
    var cancel = el("button", "btn", uiT("wf_cancel", "Cancel"));
    cancel.type = "button";
    cancel.addEventListener("click", function () { closeModal(modal); });
    var go = el("button", "btn btn-primary", uiT("tm_import_btn", "Import"));
    go.type = "button";
    go.addEventListener("click", function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) {
        preview.replaceChildren(el("p", "search-error", uiT("tm_choose_file", "Choose a TMX file.")));
        return;
      }
      go.disabled = true;
      preview.replaceChildren(el(
        "p",
        "excerpt",
        dry.checked
          ? uiT("tm_previewing", "Previewing…")
          : uiT("tm_importing", "Importing…"),
      ));
      var reader = new FileReader();
      reader.onload = function () {
        var text = String(reader.result || "");
        var b64 = btoa(unescape(encodeURIComponent(text)));
        var importBody = {
          project: state.project,
          locale: localesBox.value,
          conflict: conflict.value,
          dry_run: !!dry.checked,
          tmx_base64: b64,
        };
        var postImport = (window.LLMApi && LLMApi.apiPost)
          ? LLMApi.apiPost("/api/tm/import", importBody)
          : fetch("/api/tm/import", {
              method: "POST",
              headers: headers(true),
              credentials: "same-origin",
              body: JSON.stringify(importBody),
            }).then(function (r) { return r.json(); });
        postImport.then(function (result) {
          go.disabled = false;
          if (!result.ok) {
            preview.replaceChildren(el(
              "p",
              "search-error",
              result.summary || result.error || uiT("tm_import_failed", "Import failed"),
            ));
            return;
          }
          var counts = (result.data && result.data.counts) || {};
          var lines = el("div", "tm-import-counts");
          lines.appendChild(el("p", "", result.summary || uiT("wf_done", "Done")));
          lines.appendChild(el(
            "p",
            "excerpt",
            uiT(
              "tm_import_counts",
              "added {a}, overwritten {o}, skipped {s}, unkeyed {u}",
            )
              .replace("{a}", String(counts.added || 0))
              .replace("{o}", String(counts.overwritten || 0))
              .replace("{s}", String(counts.skipped || 0))
              .replace("{u}", String(counts.unkeyed || 0)),
          ));
          preview.replaceChildren(lines);
          if (!dry.checked) {
            refreshLeverage().then(function () {
              if (state.tab === "leverage" || state.tab === "browse") render();
              else setSubtitle();
            });
          }
        }).catch(function (err) {
          go.disabled = false;
          preview.replaceChildren(el("p", "search-error", String(err.message || err)));
        });
      };
      reader.onerror = function () {
        go.disabled = false;
        preview.replaceChildren(el("p", "search-error", uiT("tm_read_failed", "Could not read file.")));
      };
      reader.readAsText(file);
    });
    actions.appendChild(cancel);
    actions.appendChild(go);
    box.appendChild(actions);
    modal.appendChild(box);
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) closeModal(modal);
    });
    document.body.appendChild(modal);
  }

  function bindHeadActions() {
    var importBtn = document.getElementById("tm-import-btn");
    var exportBtn = document.getElementById("tm-export-btn");
    if (importBtn && !importBtn.dataset.bound) {
      importBtn.dataset.bound = "1";
      importBtn.addEventListener("click", openImport);
    }
    if (exportBtn && !exportBtn.dataset.bound) {
      exportBtn.dataset.bound = "1";
      exportBtn.addEventListener("click", function () { openExport(state.locale); });
    }
  }

  function boot() {
    bindHeadActions();
    select.addEventListener("change", function () {
      state.project = select.value;
      if (state.project) load();
    });
    if (select.value) {
      state.project = select.value;
      load();
    }
  }

  // Wait for the ui-locale dictionary so uiT() does not bake English fallbacks into
  // the tabs and counts under en-XX (leftover-hunt false positives).
  var ready = (window.uiLocale && typeof window.uiLocale.whenReady === "function")
    ? window.uiLocale.whenReady()
    : Promise.resolve();
  ready.then(boot);
})();
