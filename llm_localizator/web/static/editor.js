(function (root) {
  function regexpError(pattern) {
    try {
      new RegExp(pattern);
      return "";
    } catch (err) {
      return err && err.message ? err.message : "invalid pattern";
    }
  }

  function editDistance(left, right, maxDist) {
    var a = String(left || "");
    var b = String(right || "");
    var cap = maxDist == null ? -1 : maxDist;
    if (cap >= 0 && Math.abs(a.length - b.length) > cap) return cap + 1;
    var prev = [];
    var i, j;
    for (j = 0; j <= b.length; j += 1) prev[j] = j;
    for (i = 1; i <= a.length; i += 1) {
      var cur = [i];
      var best = cur[0];
      for (j = 1; j <= b.length; j += 1) {
        var cost = a[i - 1] === b[j - 1] ? 0 : 1;
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (cur[j] < best) best = cur[j];
      }
      if (cap >= 0 && best > cap && i > cap) return cap + 1;
      prev = cur;
    }
    return prev[b.length];
  }

  function fullEditDistance(left, right) {
    return editDistance(left, right, null);
  }

  /** Decide which CAT action a keydown should trigger. Pure for tests. */
  function shortcutAction(event, opts) {
    opts = opts || {};
    var key = event.key || "";
    var ctrl = !!(event.ctrlKey || event.metaKey);
    var alt = !!event.altKey;
    var tag = (opts.targetTag || "").toLowerCase();
    var id = opts.targetId || "";
    var inField = tag === "input" || tag === "textarea" || tag === "select";
    var inTranslation = id === "translation-field" || id.indexOf("plural-") === 0;
    var inSearch = id === "editor-search" || (tag === "input" && opts.targetType === "search");

    if (key === "?" || (ctrl && key === "/")) {
      if (inField && !inTranslation && !opts.helpOpen) return null;
      return "help";
    }
    if (key === "Escape" && opts.helpOpen) return "help";
    if (opts.helpOpen) return null;

    // Save may fire inside the translation field; never from search.
    if ((ctrl && key === "Enter") || (ctrl && (key === "s" || key === "S"))) {
      if (inSearch) return null;
      if (!inField || inTranslation) return "save";
      return null;
    }
    if (key === "Escape") {
      if (inTranslation) return "revert";
      return null;
    }
    // Navigation shortcuts do not fire inside fields.
    if (inField) return null;
    if (alt && key === "ArrowDown") return "next";
    if (alt && key === "ArrowUp") return "prev";
    if (ctrl && event.shiftKey && (key === "Insert" || key === "i" || key === "I")) {
      return "copySource";
    }
    return null;
  }

  function translateBody(project, locale, keys) {
    return {
      project: project,
      locales: locale ? [locale] : [],
      keys: keys.slice(),
    };
  }

  root.llmEditor = {
    regexpError: regexpError,
    editDistance: function (left, right) { return editDistance(left, right, 2); },
    fullEditDistance: fullEditDistance,
    shortcutAction: shortcutAction,
    translateBody: translateBody,
  };

  if (!root.document || !root.document.getElementById) return;

  var body = document.getElementById("page-body");
  var select = document.getElementById("project-select");
  if (!body || !select) return;

  var _displayNames = null;
  try { _displayNames = new Intl.DisplayNames(["en"], { type: "language" }); } catch (e) {}
  function localeLabel(code) {
    if (!_displayNames) return code;
    try { var n = _displayNames.of(code); return n && n !== code ? code + " – " + n : code; } catch (e) { return code; }
  }

  function renderMarkdown(text) {
    var s = String(text || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    s = s.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    s = s.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    s = s.replace(/^# (.+)$/gm, "<h1>$1</h1>");
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");
    s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
    s = s.replace(/_(.+?)_/g, "<em>$1</em>");
    s = s.replace(/`(.+?)`/g, "<code>$1</code>");
    // Only http(s)/mailto/relative targets; quotes cannot break out of href.
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_m, label, url) {
      var u = url.trim();
      if (!/^(https?:|mailto:|\/|#|\.\.?\/)/i.test(u) && /^[a-z][a-z0-9+.-]*:/i.test(u)) {
        return label;
      }
      u = u.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
      return '<a href="' + u + '" rel="noopener noreferrer">' + label + '</a>';
    });
    s = s.replace(/\n/g, "<br>");
    return s;
  }

  var state = {
    project: "",
    lite: null,
    namespace: "__all__",
    nsPrefix: "",
    collection: "messages",
    locale: "",
    compare: [],
    only: "all",
    mode: "exact",
    query: "",
    fields: { key: true, source: true, translation: true, notes: false },
    offset: 0,
    limit: 250,
    selected: {},
    editedSession: {},
    matchingTotal: 0,
    row: null,
    tab: "translation",
    deepKey: "",
    me: null,
    searchSuppressFocus: false,
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function params(extra) {
    var q = new URLSearchParams();
    q.set("project", state.project);
    Object.keys(extra || {}).forEach(function (key) {
      if (extra[key] != null && extra[key] !== "") q.set(key, extra[key]);
    });
    return q.toString();
  }

  function post(url, payload) {
    var body = Object.assign({ project: state.project }, payload);
    if (window.LLMApi && LLMApi.apiPost) {
      return LLMApi.apiPost(url, body).then(function (data) {
        if (data && data.status != null) data._status = data.status;
        return data;
      });
    }
    var headers = authHeaders();
    headers["Content-Type"] = "application/json";
    return fetch(url, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(body),
    }).then(function (response) {
      return response.json().then(function (data) {
        data._status = response.status;
        return data;
      });
    });
  }

  function apiGet(path, extra) {
    var query = Object.assign({ project: state.project }, extra || {});
    if (window.LLMApi && LLMApi.apiGet) return LLMApi.apiGet(path, query);
    return fetch(path + "?" + params(extra), { headers: authHeaders() })
      .then(function (response) { return response.json(); });
  }

  function activeLocales(lite) {
    return (lite && lite.activeLocales) || [];
  }

  function allLocales(lite) {
    return activeLocales(lite).concat((lite && lite.frozenLocales) || []);
  }

  function sessionMe() {
    return state.me || root.__LLM_ME || null;
  }

  function sessionIsAdmin() {
    var me = sessionMe();
    return !!(me && me.authenticated && (me.role === "Admin" || me.via === "token"));
  }

  /** Locales this session may request. Admin and token admin see every target. */
  function visibleLocales(lite) {
    var all = allLocales(lite);
    var me = sessionMe();
    if (!me || !me.authenticated) return all;
    if (me.role === "Admin" || me.via === "token") return all;
    var assigned = (me.user && me.user.locales) || [];
    if (me.role === "Translator") {
      return all.filter(function (loc) { return assigned.indexOf(loc) >= 0; });
    }
    if (assigned.length) {
      return all.filter(function (loc) { return assigned.indexOf(loc) >= 0; });
    }
    return all;
  }

  function whenMe() {
    // A full load sets __LLM_READY after /api/auth/me. In-app navigation keeps
    // the existing shell, which may already have published __LLM_ME without
    // that flag. Waiting only for the flag leaves the list on "Loading…".
    // Do not time out with a null me — that treats the session as open and
    // requests every locale, which 403s once the real actor is a Translator.
    if (root.__LLM_READY || root.__LLM_ME) return Promise.resolve(root.__LLM_ME || null);
    return new Promise(function (resolve) {
      var done = false;
      function finish() {
        if (done) return;
        done = true;
        root.removeEventListener("llm-me", finish);
        resolve(root.__LLM_ME || null);
      }
      root.addEventListener("llm-me", finish);
      if (root.__LLM_READY || root.__LLM_ME) finish();
    });
  }

  function authHeaders() {
    if (window.LLMApi && LLMApi.authHeaders) {
      var h = LLMApi.authHeaders();
      delete h["Content-Type"];
      return h;
    }
    var out = {};
    if (root.__LLM_TOKEN) out["X-LLM-Token"] = root.__LLM_TOKEN;
    return out;
  }

  function loadLite() {
    return apiGet("/api/overview-lite", {}).then(function (lite) {
      if (lite && lite.error && !lite.activeLocales) {
        throw new Error(lite.error || "overview-lite failed");
      }
      state.lite = lite;
      var allowed = visibleLocales(lite);
      var activeAllowed = allowed.filter(function (loc) {
        return (lite.frozenLocales || []).indexOf(loc) < 0;
      });
      var fromUrl = new URLSearchParams(location.search);
      var localeFromUrl = fromUrl.get("locale");
      if (localeFromUrl && allowed.indexOf(localeFromUrl) >= 0) {
        state.locale = localeFromUrl;
      } else if (!state.locale || allowed.indexOf(state.locale) < 0) {
        state.locale = (activeAllowed[0] || allowed[0] || "");
      }
      var namespaces = (lite.namespaces || []).map(function (item) { return item.name; });
      var nsFromUrl = fromUrl.get("namespace");
      if (nsFromUrl && namespaces.indexOf(nsFromUrl) >= 0) {
        state.namespace = nsFromUrl;
        state.nsPrefix = "";
      }
      var prefixFromUrl = fromUrl.get("nsPrefix") || fromUrl.get("domain");
      if (prefixFromUrl) {
        state.nsPrefix = prefixFromUrl;
        state.namespace = "__all__";
      }
      state.deepKey = fromUrl.get("key") || "";
      var collFromUrl = fromUrl.get("collection");
      if (collFromUrl) state.collection = collFromUrl;
      if (lite.scaleHints && lite.scaleHints.pageSizeAllDisabled) {
        if (!state.namespace || state.namespace === "__all__") {
          state.namespace = namespaces[0] || "";
          state.nsPrefix = "";
        }
      } else if (!state.namespace || (state.namespace === "__all__" && !namespaces.length)) {
        state.namespace = namespaces[0] || "__all__";
      }
      return lite;
    });
  }

  function fetchMessages() {
    var extra = {
      locales: state.locale,
      namespace: state.nsPrefix ? "__all__" : state.namespace,
      only: state.only,
      q: state.query || "",
      mode: state.mode === "regexp" ? "regexp"
        : (state.mode === "approx" || state.mode === "fuzzy" ? "fuzzy" : "exact"),
      offset: String(state.offset),
      limit: String(state.limit),
      detail: state.fields.notes ? "full" : "minimal",
    };
    if (state.nsPrefix) extra.nsPrefix = state.nsPrefix;
    return apiGet("/api/messages", extra);
  }

  function rowHay(row) {
    var parts = [];
    if (state.fields.key) parts.push(row.key || "");
    if (state.fields.source) parts.push(row.source || "");
    if (state.fields.translation) parts.push((row.values && row.values[state.locale]) || "");
    if (state.fields.notes) parts.push(row.note || "");
    return parts;
  }

  function applyClientFilter(rows) {
    // Search runs server-side via ``mode``; only validate regexp syntax here.
    if (state.query && state.mode === "regexp") {
      var error = regexpError(state.query);
      if (error) return { error: error, rows: [] };
    }
    return { error: "", rows: rows };
  }

  function selectedKeys() {
    return Object.keys(state.selected).filter(function (key) { return state.selected[key]; });
  }

  function render() {
    body.replaceChildren();
    body.appendChild(toolbar());
    if (state.collection && state.collection !== "messages") {
      var host = el("div", "editor-table-host");
      host.id = "string-list";
      body.appendChild(host);
      loadCollection(state.collection);
      return;
    }
    var host = el("div", "editor-table-host");
    host.id = "string-list";
    body.appendChild(host);
    refreshList();
  }

  function statusOptions() {
    return [
      { value: "all", label: uiT("filterAll", "all statuses") },
      { value: "missing", label: uiT("filterMissing", "missing") },
      { value: "stale", label: uiT("filterStale", "stale") },
      { value: "machine", label: uiT("filterMachine", "machine") },
      { value: "human", label: uiT("filterHuman", "human") },
      { value: "agent", label: uiT("filterAgent", "agent") },
      { value: "imported", label: uiT("filterImported", "imported") },
      { value: "low_score", label: uiT("filterLowScore", "low score") },
      { value: "has_findings", label: uiT("filterHasProblems", "has problems") },
      { value: "untranslated", label: uiT("filterUntranslated", "untranslated") },
      { value: "verified", label: uiT("filterVerified", "verified") },
      { value: "pre_translated", label: uiT("filterPreTranslated", "pre-translated") },
    ];
  }

  function statusLabel(status) {
    if (!status) return "";
    var hit = statusOptions().filter(function (item) { return item.value === status; })[0];
    return hit ? hit.label : status;
  }

  function domainChoices(lite) {
    var names = (lite.namespaces || []).map(function (item) { return item.name; });
    var seen = {};
    var out = [];
    function add(value, label, kind) {
      if (seen[value]) return;
      seen[value] = true;
      out.push({ value: value, label: label, kind: kind });
    }
    add("__all__", "All", "all");
    names.forEach(function (name) {
      var parts = name.split("/");
      for (var i = 1; i < parts.length; i += 1) {
        var prefix = parts.slice(0, i).join("/");
        add("prefix:" + prefix, prefix.replace(/\//g, "."), "prefix");
      }
      add("ns:" + name, name.replace(/\//g, "."), "ns");
    });
    return out;
  }

  function currentDomainValue() {
    if (state.nsPrefix) return "prefix:" + state.nsPrefix;
    if (state.namespace === "__all__") return "__all__";
    return "ns:" + state.namespace;
  }

  function applyDomainValue(value) {
    state.offset = 0;
    if (value === "__all__") {
      state.namespace = "__all__";
      state.nsPrefix = "";
      return;
    }
    if (value.indexOf("prefix:") === 0) {
      state.nsPrefix = value.slice("prefix:".length);
      state.namespace = "__all__";
      return;
    }
    if (value.indexOf("ns:") === 0) {
      state.namespace = value.slice("ns:".length);
      state.nsPrefix = "";
    }
  }

  function toolbar() {
    var bar = el("div", "toolbar");
    var lite = state.lite || {};

    var lang = document.createElement("select");
    lang.setAttribute("aria-label", uiT("ed_lang_aria", "Language"));
    visibleLocales(lite).forEach(function (locale) {
      var frozen = (lite.frozenLocales || []).indexOf(locale) >= 0;
      var option = el("option", "", localeLabel(locale)
        + (frozen ? " " + uiT("ed_frozen_suffix", "[frozen]") : ""));
      option.value = locale;
      if (locale === state.locale) option.selected = true;
      lang.appendChild(option);
    });
    lang.addEventListener("change", function () {
      var next = lang.value;
      var frozen = (lite.frozenLocales || []).indexOf(next) >= 0;
      if (frozen && !window.confirm(
        uiT(
          "ed_frozen_confirm",
          "{locale} is frozen (excluded from automatic runs). Open it for manual review anyway?",
        ).replace("{locale}", next)
      )) {
        lang.value = state.locale;
        return;
      }
      state.locale = next;
      state.offset = 0;
      state.row = null;
      render();
    });
    bar.appendChild(lang);

    var wfChip = el("a", "wf-chip", "");
    wfChip.href = "/app/workflow";
    wfChip.hidden = true;
    function paintWfChip() {
      var info = state.wfSummary && state.wfSummary.locales && state.wfSummary.locales[state.locale];
      if (!info) { wfChip.hidden = true; return; }
      wfChip.hidden = false;
      wfChip.textContent = uiT("ed_workflow", "Workflow:") + " " + (info.workflow || uiT("ed_wf_none", "none"));
      wfChip.title = uiT(
        "ed_workflow_tip",
        "The workflow that processes this language — open the Workflow page",
      );
    }
    if (state.wfSummary) paintWfChip();
    else {
      apiGet("/api/workflow/summary", {
        project: (document.getElementById("project-select") || {}).value || state.project || "",
      })
        .then(function (d) { if (d && d.ok !== false && !d.error) { state.wfSummary = d; paintWfChip(); } })
        .catch(function () {});
    }
    bar.appendChild(wfChip);

    var collections = lite.collections || [{ name: "messages" }];
    if (collections.length > 1) {
      var cat = document.createElement("select");
      cat.setAttribute("aria-label", uiT("ed_aria_category", "Category"));
      collections.forEach(function (item) {
        var option = el("option", "", item.name);
        option.value = item.name;
        if (item.name === state.collection) option.selected = true;
        cat.appendChild(option);
      });
      cat.addEventListener("change", function () {
        state.collection = cat.value;
        state.offset = 0;
        state.row = null;
        render();
      });
      bar.appendChild(cat);
    }

    var domainChoiceList = domainChoices(lite);
    var domain = document.createElement("select");
    domain.setAttribute("aria-label", uiT("ed_aria_section", "Section"));
    var domainVal = currentDomainValue();
    domainChoiceList.forEach(function (item) {
      var option = el("option", "", item.label);
      option.value = item.value;
      if (item.value === domainVal) option.selected = true;
      domain.appendChild(option);
    });
    domain.addEventListener("change", function () {
      applyDomainValue(domain.value);
      refreshList();
    });
    if (domainChoiceList.length > 1) bar.appendChild(domain);

    var only = document.createElement("select");
    only.setAttribute("aria-label", uiT("ed_aria_status", "Status"));
    statusOptions().forEach(function (item) {
      var option = el("option", "", item.label);
      option.value = item.value;
      if (item.value === state.only) option.selected = true;
      only.appendChild(option);
    });
    only.addEventListener("change", function () {
      state.only = only.value;
      state.offset = 0;
      refreshList();
    });
    bar.appendChild(only);
    bar.appendChild(searchControl());

    if (window.LLMHelp) bar.appendChild(window.LLMHelp.helpBtn("editor:filters"));

    var stats = el("span", "editor-count", "");
    stats.id = "editor-count";
    bar.appendChild(stats);
    return bar;
  }

  function searchControl() {
    var search = el("div", "search");
    var input = document.createElement("input");
    input.type = "search";
    input.id = "editor-search";
    input.placeholder = uiT("ed_search_ph", "search…");
    input.value = state.query;
    input.setAttribute("aria-label", uiT("ed_aria_search", "Search"));
    var toggle = el("button", "search-toggle", "▾");
    toggle.type = "button";
    toggle.setAttribute("aria-label", uiT("ed_aria_search_opts", "Search options"));
    var panel = el("div", "search-panel");
    panel.id = "editor-search-panel";
    function setOpen(open) {
      panel.classList.toggle("is-open", !!open);
      if (!open) state.searchSuppressFocus = true;
    }
    function isOpen() {
      return panel.classList.contains("is-open");
    }
    toggle.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(!isOpen());
    });
    input.addEventListener("focus", function () {
      if (state.searchSuppressFocus) {
        state.searchSuppressFocus = false;
        return;
      }
      setOpen(true);
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        input.blur();
      }
      if (event.key === "Enter") {
        event.preventDefault();
        runSearch();
      }
    });
    panel.appendChild(el("div", "search-panel-label", uiT("ed_search_mode", "Search mode")));
    var modes = el("div", "search-modes");
    [
      { value: "exact", label: uiT("ed_mode_exact", "Exact — literal substring") },
      { value: "regexp", label: uiT("ed_mode_regexp", "Regexp — pattern") },
      { value: "approx", label: uiT("ed_mode_fuzzy", "Fuzzy — all query words (server-side)") },
      { value: "semantic", label: uiT("ed_mode_semantic", "Semantic — unavailable (embeddings parked)"), disabled: true },
    ].forEach(function (item) {
      var label = el("label", "search-mode", item.label);
      var radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "editor-search-mode";
      radio.value = item.value;
      radio.checked = state.mode === item.value;
      if (item.disabled) {
        radio.disabled = true;
        label.className += " is-disabled";
      } else {
        radio.addEventListener("change", function () {
          state.mode = item.value;
        });
      }
      label.insertBefore(radio, label.firstChild);
      modes.appendChild(label);
    });
    panel.appendChild(modes);
    var fields = el("div", "search-fields");
    ["key", "source", "translation", "notes"].forEach(function (name) {
      var label = el("label", "", name);
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = !!state.fields[name];
      box.addEventListener("change", function () {
        state.fields[name] = box.checked;
        refreshList();
      });
      label.insertBefore(box, label.firstChild);
      fields.appendChild(label);
    });
    panel.appendChild(fields);
    var goRow = el("div", "search-go");
    var go = el("button", "btn btn-primary", uiT("ed_go", "Go"));
    go.type = "button";
    function runSearch() {
      state.query = input.value;
      state.offset = 0;
      setOpen(false);
      refreshList();
    }
    go.addEventListener("click", runSearch);
    input.addEventListener("change", runSearch);
    goRow.appendChild(go);
    panel.appendChild(goRow);
    var error = el("p", "search-error");
    error.id = "search-error";
    panel.appendChild(error);
    search.appendChild(input);
    search.appendChild(toggle);
    search.appendChild(panel);

    if (!root.__LLM_SEARCH_OUTSIDE__) {
      root.__LLM_SEARCH_OUTSIDE__ = true;
      document.addEventListener("mousedown", function (event) {
        var panelEl = document.getElementById("editor-search-panel");
        var searchEl = panelEl && panelEl.parentElement;
        if (!panelEl || !panelEl.classList.contains("is-open")) return;
        if (searchEl && searchEl.contains(event.target)) return;
        panelEl.classList.remove("is-open");
        state.searchSuppressFocus = true;
      });
      document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        var panelEl = document.getElementById("editor-search-panel");
        if (!panelEl || !panelEl.classList.contains("is-open")) return;
        panelEl.classList.remove("is-open");
        state.searchSuppressFocus = true;
      });
    }
    return search;
  }

  function updateStats() {
    var count = document.getElementById("editor-count");
    if (!count) return;
    var matching = state.matchingTotal || 0;
    var selected = selectedKeys().length;
    var edited = Object.keys(state.editedSession).length;
    count.textContent = uiT(
      "ed_stats", "matching: {matching} · selected: {selected} · edited this session: {edited}",
    )
      .split("{matching}").join(String(matching))
      .split("{selected}").join(String(selected))
      .split("{edited}").join(String(edited));
  }

  function refreshList() {
    var list = document.getElementById("string-list");
    if (!list) return;
    if (state.collection && state.collection !== "messages") {
      loadCollection(state.collection);
      return;
    }
    if (!state.locale) {
      list.replaceChildren(el("p", "empty-state", uiT("ed_no_locales", "No locales assigned")));
      state.matchingTotal = 0;
      updateStats();
      return;
    }
    var gen = (state.listGen = (state.listGen || 0) + 1);
    fetchMessages().then(function (payload) {
      if (gen !== state.listGen) return;
      if (payload && payload.ok === false) {
        list.replaceChildren(el("p", "search-error", payload.error || uiT("ed_messages_failed", "Could not load messages")));
        return;
      }
      var filtered = applyClientFilter(payload.rows || []);
      var error = document.getElementById("search-error");
      if (error) error.textContent = filtered.error || "";
      var total = state.mode === "exact"
        ? ((payload.counts && payload.counts.total) || 0)
        : filtered.rows.length;
      state.matchingTotal = total;
      list.replaceChildren();
      var bulk = bulkBar();
      if (bulk) list.appendChild(bulk);
      list.appendChild(renderTable(filtered.rows));
      list.appendChild(pager(payload.counts || { total: total }));
      updateStats();
      if (state.deepKey) {
        var wanted = filtered.rows.filter(function (row) { return row.key === state.deepKey; })[0];
        if (wanted) {
          state.deepKey = "";
          openRow(wanted);
        }
      } else if (state.row) {
        var still = filtered.rows.filter(function (row) {
          return rowId(row) === rowId(state.row);
        })[0];
        if (still) paintExpand(still);
      }
    }).catch(function (err) {
      list.replaceChildren(el("p", "search-error", String(err.message || err)));
    });
  }

  function rowId(row) {
    return row.namespace + "\t" + row.key;
  }

  function scoreClass(score) {
    if (score == null || score === "") return "score-none";
    var n = Number(score);
    if (!isFinite(n)) return "score-none";
    if (n >= 0.8) return "score-good";
    if (n >= 0.6) return "score-mid";
    return "score-low";
  }

  function scoreText(score) {
    if (score == null || score === "") return "—";
    var n = Number(score);
    if (!isFinite(n)) return "—";
    return n.toFixed(2);
  }

  function rowStatus(row) {
    return (row.statuses && row.statuses[state.locale]) || "missing";
  }

  function renderTable(rows) {
    var wrap = el("div", "tbl-wrap");
    var table = el("table", "editor-table");
    var colgroup = el("colgroup", "");
    ["c-check", "c-key", "c-src", "c-loc", "c-status", "c-score"].forEach(function (name) {
      var col = document.createElement("col");
      col.className = name;
      colgroup.appendChild(col);
    });
    table.appendChild(colgroup);
    var thead = el("thead", "");
    var hr = el("tr", "");
    [
      "",
      uiT("ed_col_key", "key"),
      uiT("ed_col_source", "source"),
      state.locale || uiT("ed_col_translation", "translation"),
      uiT("ed_col_status", "status"),
      uiT("ed_col_score", "score"),
    ].forEach(function (label) {
      hr.appendChild(el("th", "", label));
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = el("tbody", "");
    tbody.id = "editor-tbody";
    rows.forEach(function (row) {
      tbody.appendChild(tableRow(row));
    });
    if (!rows.length) {
      var empty = el("tr", "");
      var td = el("td", "empty-state", uiT("ed_nothing_matches", "Nothing matches."));
      td.colSpan = 6;
      empty.appendChild(td);
      tbody.appendChild(empty);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function tableRow(row) {
    var id = rowId(row);
    var tr = el("tr", "editor-row"
      + (state.row && rowId(state.row) === id ? " is-active" : "")
      + (state.editedSession[id] ? " is-recent" : ""));
    tr.dataset.llmNs = row.namespace;
    tr.dataset.llmKey = row.key;

    var tdCheck = el("td", "c-check");
    var box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!state.selected[id];
    box.addEventListener("click", function (event) { event.stopPropagation(); });
    box.addEventListener("change", function () {
      state.selected[id] = box.checked;
      if (!box.checked) delete state.selected[id];
      updateStats();
      var bulkHost = document.getElementById("string-list");
      if (bulkHost) {
        var old = bulkHost.querySelector(".bulk-bar");
        var next = bulkBar();
        if (old && next) old.replaceWith(next);
        else if (old) old.remove();
        else if (next) bulkHost.insertBefore(next, bulkHost.firstChild);
      }
    });
    tdCheck.appendChild(box);
    tr.appendChild(tdCheck);

    var keyLabel = (state.namespace === "__all__" || state.nsPrefix)
      ? ((row.namespace || "") + "." + row.key)
      : row.key;
    tr.appendChild(el("td", "c-key", keyLabel));
    var tdSrc = el("td", "c-src");
    phText(tdSrc, row.source || "");
    tr.appendChild(tdSrc);

    var tdLoc = el("td", "c-loc");
    var area = document.createElement("textarea");
    area.className = "cell-edit";
    area.dir = "auto";
    area.lang = state.locale;
    area.spellcheck = true;
    area.rows = 2;
    area.id = "cell-" + id.replace(/\t/g, "__");
    area.value = (row.values && row.values[state.locale]) || "";
    area.addEventListener("click", function (event) { event.stopPropagation(); });
    area.addEventListener("focus", function () {
      state.row = row;
      tr.classList.add("is-active");
    });
    area.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && (event.key === "s" || event.key === "S" || event.key === "Enter")) {
        event.preventDefault();
        saveCell(row, area);
      }
    });
    area.addEventListener("blur", function () {
      var original = (row.values && row.values[state.locale]) || "";
      if (area.value !== original) saveCell(row, area);
    });
    tdLoc.appendChild(area);
    tr.appendChild(tdLoc);

    var status = rowStatus(row);
    tr.appendChild(el("td", "c-status")).appendChild(el("span", "pill pill-" + status, status));
    tr.appendChild(el("td", "c-score " + scoreClass(row.qualityScore), scoreText(row.qualityScore)));

    tr.addEventListener("click", function (event) {
      if (event.target && event.target.tagName === "TEXTAREA") return;
      if (event.target && event.target.type === "checkbox") return;
      openRow(row);
    });
    return tr;
  }

  function saveCell(row, area) {
    var payload = {
      locale: state.locale,
      namespace: row.namespace,
      key: row.key,
      value: area.value,
    };
    post("/api/save", payload).then(function (data) {
      if (!data.ok) throw new Error(data.error || uiT("ed_save_failed", "save failed"));
      state.editedSession[rowId(row)] = true;
      if (!row.values) row.values = {};
      row.values[state.locale] = area.value;
      if (!row.statuses) row.statuses = {};
      row.statuses[state.locale] = "human";
      updateStats();
      var tr = area.closest("tr");
      if (tr) {
        tr.classList.add("is-recent");
        var statusCell = tr.querySelector(".c-status .pill");
        if (statusCell) {
          statusCell.className = "pill pill-human";
          statusCell.textContent = "human";
        }
      }
      scheduleValidate(row);
    }).catch(showError);
  }

  function closeExpand() {
    var existing = document.getElementById("editor-expand-row");
    if (existing) existing.remove();
    var tbody = document.getElementById("editor-tbody");
    if (tbody) {
      Array.prototype.forEach.call(tbody.querySelectorAll("tr.editor-row.is-active"), function (node) {
        node.classList.remove("is-active");
      });
    }
    state.row = null;
    state._saveFn = null;
    state._revertFn = null;
    state._copySourceFn = null;
  }

  function paintExpand(row) {
    var tbody = document.getElementById("editor-tbody");
    if (!tbody) return;
    var existing = document.getElementById("editor-expand-row");
    if (existing) existing.remove();
    var tr = el("tr", "editor-expand-row");
    tr.id = "editor-expand-row";
    var td = el("td", "editor-expand-cell");
    td.colSpan = 6;
    var pane = el("div", "pane editor-expand-pane");
    pane.id = "editor-pane";
    pane.addEventListener("input", function () {
      if (state.row) scheduleValidate(state.row);
    });
    td.appendChild(pane);
    tr.appendChild(td);
    var anchor = null;
    Array.prototype.forEach.call(tbody.querySelectorAll("tr.editor-row"), function (node) {
      if (node.dataset.llmNs === row.namespace && node.dataset.llmKey === row.key) {
        anchor = node;
        node.classList.add("is-active");
      } else {
        node.classList.remove("is-active");
      }
    });
    if (anchor && anchor.nextSibling) tbody.insertBefore(tr, anchor.nextSibling);
    else tbody.appendChild(tr);
    paintPane(row);
  }

  function openRow(row) {
    var open = document.getElementById("editor-expand-row");
    if (open && state.row && rowId(state.row) === rowId(row)) {
      closeExpand();
      return;
    }
    state.row = row;
    apiGet("/api/messages/row", {
      locales: rowLocales().join(","),
      namespace: row.namespace,
      key: row.key,
    }).then(function (payload) {
      if (!payload.ok) throw new Error(payload.error || uiT("ed_row_failed", "Could not load this row"));
      // Another row may have been opened while this request was in flight.
      if (state.row && rowId(state.row) !== rowId(row) && rowId(state.row) !== rowId(payload.row)) {
        return;
      }
      state.row = payload.row;
      paintExpand(payload.row);
    }).catch(function (err) {
      showError(err);
    });
  }

  function pager(counts) {
    var node = el("div", "pager");
    var total = counts.total || 0;
    var page = Math.floor(state.offset / state.limit) + 1;
    var pages = Math.max(1, Math.ceil(total / state.limit));
    var prev = el("button", "btn", "←");
    prev.type = "button";
    prev.setAttribute("aria-label", uiT("ed_aria_prev", "Previous"));
    prev.disabled = state.offset <= 0;
    prev.addEventListener("click", function () {
      state.offset = Math.max(0, state.offset - state.limit);
      refreshList();
    });
    var next = el("button", "btn", "→");
    next.type = "button";
    next.setAttribute("aria-label", uiT("ed_aria_next", "Next"));
    next.disabled = state.offset + state.limit >= total;
    next.addEventListener("click", function () {
      state.offset += state.limit;
      refreshList();
    });
    node.appendChild(prev);
    node.appendChild(el("span", "pager-label", page + " / " + pages));
    node.appendChild(next);
    return node;
  }

  function findReplacePanel(bar) {
    var old = document.getElementById("find-replace-panel");
    if (old) { old.remove(); return; }
    var panel = el("div", "bulk fr-panel");
    panel.id = "find-replace-panel";
    var find = el("input", "search-input");
    find.placeholder = uiT("ed_find", "Find");
    var repl = el("input", "search-input");
    repl.placeholder = uiT("ed_replace_with", "Replace with");
    var caseLabel = el("label", "", " " + uiT("ed_match_case", "Match case"));
    var caseBox = document.createElement("input");
    caseBox.type = "checkbox";
    caseLabel.insertBefore(caseBox, caseLabel.firstChild);
    var preview = el("button", "btn", uiT("ed_preview", "Preview"));
    preview.type = "button";
    var apply = el("button", "btn btn-primary", uiT("ed_replace_checked", "Replace checked"));
    apply.type = "button";
    apply.disabled = true;
    var out = el("div", "fr-rows");
    var rows = [];
    var chosen = {};
    selectedKeys().forEach(function (id) { chosen[id.replace(/\t/, ".")] = true; });
    function base() {
      return {
        locale: state.locale, find: find.value, replace: repl.value, case_sensitive: caseBox.checked,
        namespace: state.namespace === "__all__" ? "" : state.namespace,
      };
    }
    preview.addEventListener("click", function () {
      out.replaceChildren();
      apply.disabled = true;
      post("/api/ops/find-replace", base()).then(function (res) {
        if (!res.ok) { out.appendChild(el("span", "search-error", res.summary || res.error || "failed")); return; }
        rows = (res.data && res.data.rows) || [];
        out.appendChild(el("p", "", res.summary));
        rows.forEach(function (r) {
          var label = el("label", "fr-row");
          var box = document.createElement("input");
          box.type = "checkbox";
          box.dataset.key = r.namespace + "." + r.key;
          box.disabled = !!r.skip;
          box.checked = !r.skip && (!Object.keys(chosen).length || !!chosen[box.dataset.key]);
          label.appendChild(box);
          label.appendChild(el("span", "", " " + box.dataset.key + ": " + r.before + " → " + r.after + (r.skip ? "  [skipped: " + r.skip + "]" : "")));
          out.appendChild(label);
        });
        apply.disabled = !rows.some(function (r) { return !r.skip; });
      }).catch(showError);
    });
    apply.addEventListener("click", function () {
      var keys = Array.prototype.map.call(out.querySelectorAll("input[type=checkbox]:checked"), function (b) { return b.dataset.key; });
      if (!keys.length) return;
      if (!window.confirm(
        uiT("ed_replace_confirm", "Replace in {n} string(s) of {locale}? They are saved as your edits.")
          .replace("{n}", String(keys.length))
          .replace("{locale}", state.locale),
      )) return;
      post("/api/ops/find-replace", Object.assign(base(), { keys: keys, confirm: true })).then(function (res) {
        out.replaceChildren(el("p", "", res.summary || res.error || uiT("ed_done", "done")));
        apply.disabled = true;
        refreshList();
      }).catch(showError);
    });
    [find, repl, caseLabel, preview, apply].forEach(function (n) { panel.appendChild(n); });
    panel.appendChild(out);
    bar.parentNode.insertBefore(panel, bar.nextSibling);
  }

  function bulkBar() {
    var keys = selectedKeys();
    if (!keys.length) return null;
    var bar = el("div", "bulk bulk-bar");
    bar.appendChild(el("span", "", (keys.length === 1
      ? uiT("ed_selected_one", "{n} string selected")
      : uiT("ed_selected_other", "{n} strings selected")).replace("{n}", String(keys.length))));
    var translate = el("button", "btn btn-primary", uiT("ed_translate_selected", "Translate selected"));
    translate.type = "button";
    translate.addEventListener("click", function () {
      var locale = state.locale;
      if ((state.lite.frozenLocales || []).indexOf(locale) >= 0) {
        locale = activeLocales(state.lite)[0] || "";
      }
      var selected = keys.map(function (id) {
        var parts = id.split("\t");
        return parts[0] + "." + parts[1];
      });
      post("/api/ops/estimate-cost", {
        locales: locale ? [locale] : [],
        keys: selected,
      }).then(function (estData) {
        var est = (estData && estData.data) || {};
        if (est.local === false) {
          bar.appendChild(el("span", "", "batch_usd=" + est.batch_usd + " remaining_usd=" + est.remaining_usd));
        }
        return post("/api/ops/translate", translateBody(state.project, locale, selected));
      }).then(function (data) {
        if (!data) return;
        bar.appendChild(el("span", "", data.summary || data.error || "queued"));
      });
    });
    var approve = el("button", "btn", uiT("ed_approve_all", "Approve all"));
    approve.type = "button";
    approve.addEventListener("click", function () {
      Promise.all(keys.map(function (id) {
        var parts = id.split("\t");
        return post("/api/verify", { locale: state.locale, namespace: parts[0], key: parts[1], verify: true });
      })).then(function () { refreshList(); });
    });
    var exp = el("button", "btn", uiT("ed_export_selection", "Export selection"));
    exp.type = "button";
    exp.addEventListener("click", function () {
      post("/api/export", {
        locales: [state.locale],
        namespace: state.namespace === "__all__" ? "" : state.namespace,
        keys: keys.map(function (id) {
          var parts = id.split("\t");
          return parts[0] + "." + parts[1];
        }),
        format: "csv",
      }).then(function (data) {
        if (!data.ok) throw new Error(data.error || uiT("ed_export_failed", "Export failed"));
        var blob = b64ToBlob(data.file_base64, data.content_type);
        var link = el("a", "", data.filename || "export");
        link.href = URL.createObjectURL(blob);
        link.download = data.filename || "export.csv";
        link.click();
      }).catch(function (err) {
        bar.appendChild(el("span", "search-error", String(err.message || err)));
      });
    });
    var clear = el("button", "btn", uiT("ed_clear", "Clear"));
    clear.type = "button";
    clear.addEventListener("click", function () {
      state.selected = {};
      refreshList();
    });
    function bulkClear(label, extra) {
      var btn = el("button", "btn", label);
      btn.type = "button";
      btn.addEventListener("click", function () {
        var base = Object.assign({
          project: state.project, locale: state.locale,
          namespace: state.namespace === "__all__" ? "" : state.namespace,
        }, extra);
        post("/api/ops/bulk-clear", base).then(function (preview) {
          var n = preview && preview.data ? preview.data.count : 0;
          if (!preview.ok || !n) {
            bar.appendChild(el("span", "", preview.summary || preview.error || uiT("ed_nothing_to_clear", "nothing to clear")));
            return null;
          }
          if (!window.confirm(
            uiT(
              "ed_bulk_clear_confirm",
              "{label}: {n} key(s) in {locale} go back to the backlog. Human, verified and locked keys are kept. Continue?",
            )
              .replace("{label}", label)
              .replace("{n}", String(n))
              .replace("{locale}", state.locale),
          )) return null;
          return post("/api/ops/bulk-clear", Object.assign({ confirm: true }, base));
        }).then(function (done) {
          if (!done) return;
          bar.appendChild(el("span", "", done.summary || done.error || uiT("ed_done", "done")));
          refreshList();
        }).catch(showError);
      });
      return btn;
    }
    var reverify = el("button", "btn", uiT("ed_reverify", "Re-verify"));
    reverify.type = "button";
    reverify.addEventListener("click", function () {
      post("/api/ops/rescore", {
        project: state.project, locales: [state.locale], confirm: true,
        namespace: state.namespace === "__all__" ? "" : state.namespace,
      }).then(function (data) {
        bar.appendChild(el("span", "", data.summary || data.error || "queued"));
      }).catch(showError);
    });
    bar.appendChild(translate);
    bar.appendChild(reverify);
    bar.appendChild(bulkClear(uiT("ed_clear_stale", "Clear stale"), { stale_to_source: true }));
    bar.appendChild(bulkClear(uiT("ed_purge_old", "Purge old machine text"), { purge_machine_older_than: 90 }));
    bar.appendChild(bulkClear(uiT("ed_requeue_broken", "Requeue broken text"), { invalid: true, latin_leftover: true }));
    var improve = el("button", "btn", uiT("ed_improve_selected", "Improve selected"));
    improve.type = "button";
    improve.addEventListener("click", function () {
      var locale = state.locale;
      post("/api/ops/improve", {
        project: state.project,
        locales: locale ? [locale] : [],
        keys: keys.map(function (id) {
          var parts = id.split("\t");
          return parts[0] + "." + parts[1];
        }),
      }).then(function (data) {
        bar.appendChild(el("span", "", data.summary || data.error || "queued"));
      });
    });
    bar.appendChild(improve);
    bar.appendChild(approve);
    function setLocked(locked) {
      Promise.all(keys.map(function (id) {
        var parts = id.split("\t");
        return post("/api/lock", {
          locale: state.locale,
          namespace: parts[0],
          key: parts[1],
          locked: locked,
        });
      })).then(function () { refreshList(); });
    }
    var lock = el("button", "btn", uiT("ed_lock", "Lock"));
    lock.type = "button";
    lock.addEventListener("click", function () { setLocked(true); });
    var unlock = el("button", "btn", uiT("ed_unlock", "Unlock"));
    unlock.type = "button";
    unlock.addEventListener("click", function () { setLocked(false); });
    bar.appendChild(lock);
    bar.appendChild(unlock);
    var fr = el("button", "btn", uiT("ed_find_replace", "Find & replace"));
    fr.type = "button";
    fr.addEventListener("click", function () { findReplacePanel(bar); });
    bar.appendChild(exp);
    bar.appendChild(fr);
    bar.appendChild(clear);
    return bar;
  }

  function b64ToBlob(b64, type) {
    var binary = atob(b64 || "");
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: type || "application/octet-stream" });
  }

  function rowLocales() {
    var primary = state.locale;
    if (!primary) return [];
    var frozen = (state.lite && state.lite.frozenLocales) || [];
    var extra = visibleLocales(state.lite).filter(function (loc) {
      return loc !== primary && frozen.indexOf(loc) < 0;
    });
    return [primary].concat(extra.slice(0, 2));
  }

  function paintPane(row) {
    var pane = document.getElementById("editor-pane");
    if (!pane) return;
    pane.replaceChildren();
    var status = (row.statuses && row.statuses[state.locale]) || "";
    var head = el("div", "editor-keyhead");
    var title = el("div", "editor-keytitle");
    title.appendChild(el("span", "editor-ns", (row.namespace || "") + " · "));
    title.appendChild(el("span", "row-key", row.key));
    head.appendChild(title);
    var headRight = el("div", "editor-keyhead-right");
    if (status) headRight.appendChild(el("span", "pill pill-" + status, statusLabel(status)));
    var closeBtn = el("button", "btn editor-expand-close", uiT("op_close", "Close"));
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", uiT("ed_aria_close_details", "Close details"));
    closeBtn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      closeExpand();
    });
    headRight.appendChild(closeBtn);
    head.appendChild(headRight);
    pane.appendChild(head);

    var scroll = el("div", "pane-scroll");
    var source = el("div", "source-card");
    var sourceLocale = (state.lite && state.lite.sourceLocale) || "en";
    var srcHead = el("div", "source-label");
    srcHead.appendChild(document.createTextNode(
      uiT("ed_source_locale", "Source ({locale})").replace("{locale}", sourceLocale),
    ));
    var srcText = row.source || "";
    var hasMarkdown = /[*_`#\[\]!]/.test(srcText);
    if (hasMarkdown) {
      var mdToggle = el("button", "btn source-md-toggle", uiT("ed_preview", "Preview"));
      mdToggle.type = "button";
      var mdActive = false;
      var srcRaw = el("div", "source-text");
      phText(srcRaw, srcText);
      var srcMd = el("div", "source-text source-md-preview");
      srcMd.hidden = true;
      srcMd.innerHTML = renderMarkdown(srcText);
      mdToggle.addEventListener("click", function () {
        mdActive = !mdActive;
        srcRaw.hidden = mdActive;
        srcMd.hidden = !mdActive;
        mdToggle.textContent = mdActive
          ? uiT("ed_source_word", "Source")
          : uiT("ed_preview", "Preview");
      });
      srcHead.appendChild(mdToggle);
      source.appendChild(srcHead);
      source.appendChild(srcRaw);
      source.appendChild(srcMd);
    } else {
      source.appendChild(srcHead);
      var plainSrc = el("div", "source-text");
      phText(plainSrc, srcText);
      source.appendChild(plainSrc);
    }
    if (row.note) source.appendChild(el("div", "source-note", row.note));
    var hits = row.glossaryHits || [];
    if (hits.length) {
      var gl = el("div", "glossary-hits");
      hits.forEach(function (hit) {
        var line = el("div", "glossary-hit");
        line.setAttribute("data-target", hit.target || "");
        if (hit.kind === "dnt") line.appendChild(el("span", "gloss-badge", uiT("ed_dnt", "DNT")));
        line.appendChild(el("span", "gloss-term", hit.term));
        if (hit.target) line.appendChild(el("span", "gloss-target", "→ " + hit.target));
        if (hit.forbidden && hit.forbidden.length) {
          line.appendChild(el(
            "span", "gloss-never",
            uiT("ed_never", "never: {list}").replace("{list}", hit.forbidden.join(", ")),
          ));
        }
        if (hit.note) line.appendChild(el("span", "gloss-note", "(" + hit.note + ")"));
        gl.appendChild(line);
      });
      source.appendChild(gl);
    }
    scroll.appendChild(source);

    var tabs = el("div", "tabs");
    [
      { id: "translation", key: "ed_tab_translation", label: "Translation" },
      { id: "tm", key: "ed_tab_tm", label: "TM matches" },
      { id: "history", key: "ed_tab_history", label: "History" },
      { id: "comments", key: "ed_tab_comments", label: "Comments" },
      { id: "diff", key: "ed_tab_diff", label: "Machine diff" },
      { id: "distance", key: "ed_tab_distance", label: "Edit distance" },
    ].forEach(function (item) {
      var button = el(
        "button",
        "tab-btn" + (state.tab === item.id ? " is-active" : ""),
        uiT(item.key, item.label),
      );
      button.type = "button";
      button.addEventListener("click", function () {
        state.tab = item.id;
        paintPane(row);
      });
      tabs.appendChild(button);
    });
    scroll.appendChild(tabs);

    var host = el("div", "tab-panel");
    scroll.appendChild(host);
    pane.appendChild(scroll);

    if (state.tab === "history") return paintHistory(host, row);
    if (state.tab === "distance") return paintDistance(host, row);
    if (state.tab === "diff") return paintDiff(host, row);
    if (state.tab === "tm") {
      paintTm(host, row);
      return;
    }
    if (state.tab === "comments") {
      paintComments(host, row);
      return;
    }
    paintTranslation(host, row);
  }

  function paintComments(pane, row) {
    var host = el("div", "");
    host.appendChild(el("p", "empty-state", uiT("ed_loading_tickets", "Loading tickets.")));
    pane.appendChild(host);
    apiGet("/api/review/tickets", {
      locale: state.locale,
      namespace: row.namespace,
      key: row.key,
    }).then(function (data) {
      host.replaceChildren();
      var tickets = data.tickets || [];
      if (!tickets.length) {
        host.appendChild(el("p", "empty-state", uiT("ed_no_tickets", "No review tickets for this key.")));
        return;
      }
      tickets.forEach(function (ticket) {
        host.appendChild(el("h3", "", (ticket.status || "") + " · " + (ticket.reason || "")));
        (ticket.comments || []).forEach(function (item) {
          var block = el("div", "comment");
          block.appendChild(el("div", "", (item.author || "") + " · " + (item.ts || "")));
          block.appendChild(el("div", "", item.body || ""));
          host.appendChild(block);
        });
        var author = document.createElement("input");
        author.type = "text";
        author.placeholder = uiT("ed_author_ph", "author");
        var body = document.createElement("textarea");
        body.placeholder = uiT("ed_comment_ph", "comment");
        var improve = el("label", "field", uiT("ed_also_improve", "Also improve via LLM"));
        var improveBox = document.createElement("input");
        improveBox.type = "checkbox";
        improve.appendChild(improveBox);
        function send(resolve) {
          if (!author.value.trim()) {
            showError(new Error(uiT("ed_author_required", "author is required")));
            return;
          }
          post("/api/review/tickets/" + ticket.id + "/comment", {
            locale: ticket.locale || state.locale,
            author: author.value.trim(),
            body: body.value,
            resolve: !!resolve,
          }).then(function (result) {
            if (!result.ok) throw new Error(result.error || uiT("ed_comment_failed", "Could not save the comment"));
            body.value = "";
            if (resolve && improveBox.checked) {
              var key = (row.namespace ? row.namespace + "." : "") + row.key;
              return post("/api/ops/improve", {
                locales: [state.locale],
                keys: [key],
                confirm: true,
              }).then(function () { paintPane(row); });
            }
            paintPane(row);
          }).catch(showError);
        }
        var actions = el("div", "ops-actions");
        actions.appendChild(action(uiT("ed_post", "Post"), function () { send(false); }));
        actions.appendChild(action(uiT("ed_post_resolve", "Post and resolve"), function () { send(true); }));
        host.appendChild(author);
        host.appendChild(body);
        host.appendChild(actions);
        host.appendChild(improve);
      });
    }).catch(function (err) {
      host.replaceChildren(el("p", "search-error", String(err.message || err)));
    });
  }

  function currentPayload(row) {
    var payload = { locale: state.locale, namespace: row.namespace, key: row.key };
    if (row.plural && row.plural.categories) {
      var branches = {};
      row.plural.categories.forEach(function (name) {
        var field = document.getElementById("plural-" + name);
        branches[name] = field ? field.value : (row.plural.branches[name] || "");
      });
      payload.pluralBranches = branches;
      payload.pluralVariable = row.plural.variable;
      payload.pluralPrefix = row.plural.prefix;
      payload.pluralSuffix = row.plural.suffix;
    } else {
      var field = document.getElementById("translation-field");
      var cell = document.getElementById("cell-" + rowId(row).replace(/\t/g, "__"));
      payload.value = field
        ? field.value
        : (cell ? cell.value : ((row.values && row.values[state.locale]) || ""));
    }
    return payload;
  }

  function pluralExamples(locale) {
    var lang = String(locale || "").toLowerCase().split("-")[0];
    if (lang === "pl" || lang === "cs" || lang === "ru") {
      return { one: "1", few: "2, 3, 4", many: "5", other: "1.5" };
    }
    if (lang === "ar") {
      return { zero: "0", one: "1", two: "2", few: "3–10", many: "11–99", other: "100" };
    }
    return { one: "1", other: "2, 5" };
  }

  // Whitespace tokens; scripts written without spaces (CJK, Thai) fall back to graphemes.
  function diffTokens(text) {
    var s = String(text || "");
    if (!/\s/.test(s) && s.length > 1 && window.Intl && Intl.Segmenter) {
      return Array.from(new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(s), function (p) { return p.segment; });
    }
    return s.split(/(\s+)/);
  }

  var DIFF_CELL_CAP = 160000;

  function wordDiff(a, b) {
    var x = diffTokens(a), y = diffTokens(b);
    if (x.length * y.length > DIFF_CELL_CAP) {
      return a === b ? [{ t: "=", v: String(a || "") }] : [{ t: "-", v: String(a || "") }, { t: "+", v: String(b || "") }];
    }
    var n = x.length, m = y.length, t = [], i, j;
    for (i = 0; i <= n; i++) { t.push(new Array(m + 1).fill(0)); }
    for (i = n - 1; i >= 0; i--) {
      for (j = m - 1; j >= 0; j--) {
        t[i][j] = x[i] === y[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
      }
    }
    var out = [];
    i = 0; j = 0;
    while (i < n && j < m) {
      if (x[i] === y[j]) { out.push({ t: "=", v: x[i] }); i++; j++; }
      else if (t[i + 1][j] >= t[i][j + 1]) { out.push({ t: "-", v: x[i] }); i++; }
      else { out.push({ t: "+", v: y[j] }); j++; }
    }
    while (i < n) out.push({ t: "-", v: x[i++] });
    while (j < m) out.push({ t: "+", v: y[j++] });
    return out;
  }

  function paintSourceBanner(pane, row, retranslate, keyId) {
    var change = row.sourceChange;
    if (!change || !change.prev_src) return;
    var box = el("div", "source-changed-banner");
    box.appendChild(el("strong", "", uiT("ed_english_changed", "English changed")));
    if (change.timestamp) {
      box.appendChild(document.createTextNode(
        " " + uiT("ed_on_date", "on {date}:").replace("{date}", String(change.timestamp).slice(0, 10)) + " ",
      ));
    } else {
      box.appendChild(document.createTextNode(": "));
    }
    wordDiff(change.prev_src, change.next_src).forEach(function (part) {
      if (part.t === "=") phText(box, part.v);
      else phText(box.appendChild(el("span", part.t === "-" ? "diff-del" : "diff-ins")), part.v);
    });
    box.appendChild(document.createTextNode(" "));
    box.appendChild(action(uiT("ed_retranslate", "Retranslate"), retranslate));
    if (keyId && row.values && row.values[state.locale]) {
      var out = el("div", "minimal-edit-result");
      box.appendChild(action(uiT("ed_draft_minimal", "Draft minimal edit"), function () {
        out.textContent = uiT("ed_drafting", "Drafting...");
        post("/api/ops/draft", {
          action: "create", mode: "minimal-edit", locale: state.locale, keys: [keyId],
        }).then(function (res) {
          out.textContent = "";
          var draft = res.data && res.data.drafts && res.data.drafts[0];
          if (!res.ok || !draft) {
            out.textContent = res.summary || res.error || uiT("ed_no_draft", "No draft.");
            return;
          }
          out.appendChild(el(
            "div", "source-label",
            uiT("ed_proposed_edit", "Proposed edit of the current translation"),
          ));
          var line = el("div", "");
          wordDiff(res.data.previous || "", draft.text).forEach(function (part) {
            if (part.t === "=") phText(line, part.v);
            else phText(line.appendChild(el("span", part.t === "-" ? "diff-del" : "diff-ins")), part.v);
          });
          out.appendChild(line);
          if (res.data.humanEdited) {
            out.appendChild(el(
              "div", "source-label",
              uiT(
                "ed_human_edited_draft",
                "This translation was edited by a person; check the draft before using it.",
              ),
            ));
          }
          out.appendChild(action(uiT("ed_use_draft", "Use draft"), function () {
            var field = document.getElementById("translation-field");
            if (field) { field.value = draft.text; field.dispatchEvent(new Event("input")); }
          }));
        });
      }));
      box.appendChild(out);
    }
    pane.appendChild(box);
  }

  function markGlossary() {
    var field = document.getElementById("translation-field");
    if (!field) return;
    var text = field.value.toLowerCase();
    Array.prototype.forEach.call(document.querySelectorAll(".glossary-hit"), function (node) {
      var target = (node.getAttribute("data-target") || "").toLowerCase();
      node.classList.toggle("gloss-missing", !!target && text.indexOf(target) < 0);
    });
  }

  function uiT(key, fallback) {
    var loc = window.uiLocale;
    var value = loc && loc.t ? loc.t(key) : key;
    return value && value !== key ? value : fallback;
  }

  function suggestWhy(why) {
    var d = el("details", "suggest-why");
    d.appendChild(el("summary", "", uiT("suggest_why", "Why this result")));
    function line(label, value) {
      if (!value) return;
      var r = el("div", "suggest-why-row");
      r.appendChild(el("span", "source-label", label));
      r.appendChild(document.createTextNode(" " + value));
      d.appendChild(r);
    }
    line(uiT("suggest_why_model", "Model"), why.model + " (" + why.provider + "), " + why.register);
    line(uiT("suggest_why_context", "Context"), why.context);
    line(uiT("suggest_why_note", "Note"), why.note || why.fileNote);
    line(uiT("suggest_why_glossary", "Glossary"), why.glossary);
    if (why.maxChars) line(uiT("suggest_why_max", "Max length"), String(why.maxChars));
    if (why.pivot) line(uiT("suggest_why_pivot", "Pivot") + " (" + why.pivot.locale + ")", why.pivot.text);
    (why.examples || []).forEach(function (p) { line(uiT("suggest_why_example", "Example"), p.source + " → " + p.target); });
    (why.siblings || []).forEach(function (p) { line(uiT("suggest_why_sibling", "Same screen"), p.source + " → " + p.target); });
    (why.missingContext || []).forEach(function (m) { line(uiT("suggest_why_missing", "Missing context"), m); });
    (why.trace || []).forEach(function (m) { line(uiT("suggest_why_trace", "Retrieval"), m); });
    return d;
  }

  function ambiguityOn() {
    try { return window.localStorage.getItem("llm-ambiguity") === "1"; } catch (e) { return false; }
  }

  function ambiguityBlock(notes) {
    var d = el("div", "ambiguity-notes");
    d.appendChild(el("div", "source-label", uiT("ambiguity_title", "Ambiguous in the source")));
    notes.forEach(function (n) {
      var senses = (n.senses || []).length ? " (" + n.senses.join(" / ") + ")" : "";
      d.appendChild(el("div", "", n.term + senses + " → " + n.chosen));
    });
    return d;
  }

  function paintSuggest(pane, row, keyId) {
    var box = el("div", "suggest-box");
    box.hidden = true;
    var ambLabel = el("label", "diff-toggle");
    var ambBox = el("input", "");
    ambBox.type = "checkbox";
    ambBox.checked = ambiguityOn();
    ambBox.addEventListener("change", function () {
      try { window.localStorage.setItem("llm-ambiguity", ambBox.checked ? "1" : "0"); } catch (e) { /* ignore */ }
    });
    ambLabel.appendChild(ambBox);
    ambLabel.appendChild(document.createTextNode(" " + uiT("ambiguity_flag", "Flag ambiguous terms")));
    var btn = action(uiT("ed_suggest", "Suggest"), function () {
      box.hidden = false;
      box.textContent = uiT("ed_asking_model", "Asking the model…");
      post("/api/ops/suggest", {
        locale: state.locale, namespace: row.namespace, key: row.key, explain: true,
        ambiguity: ambBox.checked,
      }).then(function (data) {
        var res = (data && data.data) || {};
        if (!data.ok || !res.text) throw new Error(data.error || data.summary || uiT("ed_no_suggestion", "No suggestion available"));
        box.textContent = "";
        box.appendChild(el("div", "", res.text));
        if (res.score != null) {
          box.appendChild(el(
            "div", "source-label",
            uiT("ed_score_pct", "score {n}%").replace("{n}", String(Math.round(Number(res.score) * 100))),
          ));
        }
        if (res.explain) box.appendChild(suggestWhy(res.explain));
        if (res.ambiguity && res.ambiguity.length) box.appendChild(ambiguityBlock(res.ambiguity));
        box.appendChild(action(uiT("ed_use_this", "Use this"), function () { useTranslation(res.text); markGlossary(); }));
        var more = action(uiT("ed_more_versions", "More versions"), function () {
          more.disabled = true;
          more.textContent = uiT("ed_asking_models", "Asking other models…");
          post("/api/ops/suggest", {
            locale: state.locale, namespace: row.namespace, key: row.key, alternatives: true,
          }).then(function (d2) {
            var alts = (d2 && d2.data && d2.data.alternatives) || [];
            more.remove();
            if (!alts.length) {
              box.appendChild(el(
                "div", "source-label",
                uiT("ed_no_other_model", "No other model gave a different version"),
              ));
              return;
            }
            showAlts(alts);
          }).catch(function (err) { more.textContent = String(err && err.message || err); });
        });
        box.appendChild(more);
        function showAlts(list) { list.forEach(function (alt) {
          var altBox = el("div", "suggest-alt");
          var scoreBit = alt.score != null
            ? " · " + Math.round(Number(alt.score) * 100) + "%"
            : "";
          altBox.appendChild(el(
            "div", "source-label",
            uiT("ed_alternative", "Alternative · {model}{score}")
              .replace("{model}", alt.model)
              .replace("{score}", scoreBit),
          ));
          var body = el("div", "");
          diffInto(body, res.text, alt.text, true);
          altBox.appendChild(body);
          altBox.appendChild(action(uiT("ed_use_this", "Use this"), function () { useTranslation(alt.text); markGlossary(); }));
          box.appendChild(altBox);
        }); }
      }).catch(function (err) { box.textContent = String(err && err.message || err); });
    });
    pane.appendChild(btn);
    pane.appendChild(ambLabel);
    pane.appendChild(box);
  }

  function paintNear(pane, row) {
    var current = row.values && row.values[state.locale];
    if (!current || current === row.source) return;
    var box = el("div", "near-box");
    box.hidden = true;
    var base = { project: state.project, locale: state.locale, namespace: row.namespace, key: row.key };
    var btn = action(uiT("ed_apply_similar", "Apply to similar keys"), function () {
      box.hidden = false;
      box.textContent = uiT("ed_looking_similar", "Looking for similar keys…");
      post("/api/ops/apply-near", base).then(function (data) {
        var found = (data && data.data && data.data.candidates) || [];
        box.textContent = "";
        if (!data.ok) throw new Error(data.error || data.summary || "failed");
        if (!found.length) {
          box.appendChild(el("div", "source-label", uiT("ed_no_similar", "No similar keys")));
          return;
        }
        box.appendChild(el("div", "source-label", uiT(
          "ed_apply_similar_help",
          "Copies the saved text of this key onto the keys you tick. Verified, locked and human-edited keys are skipped.",
        )));
        var picks = [];
        found.forEach(function (c) {
          var line = el("label", "near-row" + (c.skip ? " is-skipped" : ""));
          var cb = document.createElement("input");
          cb.type = "checkbox";
          cb.disabled = !!c.skip;
          line.appendChild(cb);
          line.appendChild(el("span", "row-key", Math.round(c.similarity * 100) + "% " + c.namespace + "." + c.key));
          line.appendChild(document.createTextNode(" "));
          diffInto(line, row.source, c.source, true);
          if (c.skip) line.appendChild(el("span", "source-label", " — " + c.skip));
          if (!c.skip) picks.push({ cb: cb, id: c.namespace + "." + c.key });
          box.appendChild(line);
        });
        box.appendChild(action(uiT("ed_apply_ticked", "Apply to ticked"), function () {
          var keys = picks.filter(function (p) { return p.cb.checked; }).map(function (p) { return p.id; });
          if (!keys.length) return;
          post("/api/ops/apply-near", Object.assign({ keys: keys, confirm: true }, base)).then(function (done) {
            box.appendChild(el("div", "", done.summary || done.error || "done"));
            refreshList();
          }).catch(showError);
        }));
      }).catch(function (err) { box.textContent = String(err && err.message || err); });
    });
    pane.appendChild(btn);
    pane.appendChild(box);
  }

  var DIM_LABELS = {
    placeholder_ok: ["ed_dim_placeholders", "Placeholders"],
    glossary_ok: ["ed_dim_glossary", "Glossary"],
    script_ok: ["ed_dim_script", "Script"],
    consistency: ["ed_dim_consistency", "Consistency"],
    info: ["ed_dim_info", "Information"],
    fluency: ["ed_dim_fluency", "Fluency"],
    terminology: ["ed_dim_terminology", "Terminology"],
    ui: ["ed_dim_ui", "UI fit"],
    placeholders: ["ed_dim_placeholders", "Placeholders"],
    html: ["ed_dim_markup", "Markup"],
    length: ["ed_dim_length", "Length band"],
    bt_overlap: ["ed_dim_bt", "Back-translation"],
  };
  function dimLabel(name) {
    var row = DIM_LABELS[name];
    if (row) return uiT(row[0], row[1]);
    return name.replace(/_ok$/, "").replace(/_/g, " ");
  }

  function paintQuality(pane, row) {
    var card = el("div", "quality-card");
    var head = el("div", "quality-head");
    head.appendChild(el("span", "source-label", uiT("ed_quality_score", "Quality score")));
    head.appendChild(el("span", "quality-value " + scoreClass(row.qualityScore), scoreText(row.qualityScore)));
    card.appendChild(head);
    var meter = el("div", "quality-meter");
    var fill = el("div", "quality-meter-fill " + scoreClass(row.qualityScore));
    var width = 0;
    if (row.qualityScore != null && isFinite(Number(row.qualityScore))) {
      width = Math.round(Math.max(0, Math.min(1, Number(row.qualityScore))) * 100);
    }
    fill.style.width = width + "%";
    meter.appendChild(fill);
    card.appendChild(meter);
    var signals = el("div", "quality-signals");
    (row.qualitySignals || []).forEach(function (sig) {
      signals.appendChild(el("span", "signal", sig));
    });
    card.appendChild(signals);
    var dims = row.qualityDimensions || {};
    var names = Object.keys(dims).filter(function (n) { return isFinite(Number(dims[n])); });
    if (names.length) {
      var dimBox = el("div", "quality-dims");
      names.forEach(function (name) {
        var value = Number(dims[name]);
        var ok = value >= 0.9;
        var label = dimLabel(name);
        var line = el("div", "quality-dim-row " + (ok ? "dim-ok" : "dim-bad"));
        line.appendChild(el("span", "dim-label", label));
        if (/_ok$/.test(name)) {
          line.appendChild(el("span", "dim-mark", ok ? "✓" : "✗"));
        } else {
          var bar = el("span", "dim-bar");
          var fillEl = el("span", "dim-bar-fill");
          fillEl.style.width = Math.round(Math.max(0, Math.min(1, value)) * 100) + "%";
          bar.appendChild(fillEl);
          line.appendChild(bar);
          line.appendChild(el("span", "dim-pct", Math.round(value * 100) + "%"));
        }
        dimBox.appendChild(line);
      });
      var weakest = names.filter(function (n) { return Number(dims[n]) < 0.9; })
        .sort(function (a, b) { return Number(dims[a]) - Number(dims[b]); })[0];
      if (weakest && Number(row.qualityScore) < 0.75) {
        card.appendChild(el("div", "quality-why",
          uiT("ed_weakest", "Weakest: {dim} ({pct}%)")
            .replace("{dim}", dimLabel(weakest))
            .replace("{pct}", String(Math.round(Number(dims[weakest]) * 100)))));
      }
      card.appendChild(dimBox);
    }
    pane.appendChild(card);
  }

  function paintCompare(pane, row) {
    var others = Object.keys(row.values || {}).filter(function (locale) {
      return locale !== state.locale;
    });
    if (!others.length) return;
    var card = el("div", "compare-card");
    card.appendChild(el("div", "source-label", uiT("ed_compare_locales", "Compare locales")));
    var grid = el("div", "compare-grid");
    others.forEach(function (locale) {
      var cell = el("div", "compare-cell");
      cell.appendChild(el("div", "compare-loc", locale));
      var value = (row.values && row.values[locale]) || "";
      cell.appendChild(el("div", "compare-value", value || uiT("missingPlaceholder", "— missing —")));
      var status = (row.statuses && row.statuses[locale]) || "";
      if (status) cell.appendChild(el("div", "compare-meta", status));
      grid.appendChild(cell);
    });
    card.appendChild(grid);
    pane.appendChild(card);
  }

  function paintTranslation(pane, row) {
    var qa = el("div", "qa");
    qa.id = "live-qa";
    qa.hidden = true;
    pane.appendChild(qa);

    var keyId = row.namespace ? row.namespace + "." + row.key : row.key;
    if (row.plural && row.plural.categories && row.plural.categories.length) {
      var pluralCard = el("div", "plural-card");
      pluralCard.appendChild(el(
        "div",
        "source-label",
        uiT("ed_plural_forms", "Plural forms — {locale} ({cats})")
          .replace("{locale}", state.locale)
          .replace("{cats}", row.plural.categories.join(" / ")),
      ));
      var examples = pluralExamples(state.locale);
      row.plural.categories.forEach(function (name) {
        var block = el("div", "plural-row");
        var heading = el("div", "plural-head");
        heading.appendChild(el("span", "plural-name", name));
        if (examples[name]) {
          heading.appendChild(el(
            "span", "plural-example",
            uiT("ed_example", "example: {text}").replace("{text}", examples[name]),
          ));
        }
        block.appendChild(heading);
        var area = document.createElement("textarea");
        area.id = "plural-" + name;
        area.dir = "auto";
        area.lang = state.locale;
        area.spellcheck = true;
        area.value = (row.plural.branches && row.plural.branches[name]) || "";
        block.appendChild(area);
        pluralCard.appendChild(block);
      });
      pane.appendChild(pluralCard);
      paintLivePreview(pane, row, function () {
        return composePluralIcu(row) || (row.values && row.values[state.locale]) || row.source || "";
      });
      pluralCard.querySelectorAll("textarea").forEach(function (area) {
        area.addEventListener("input", function () {
          var live = document.getElementById("live-preview");
          if (live && live._refresh) live._refresh();
        });
      });
    } else {
      if (row.fallbackValue && !(row.values && row.values[state.locale])) {
        pane.appendChild(el(
          "p",
          "fallback-hint",
          uiT("ed_fallback_from", "Fallback from {locale} (not saved): {value}")
            .replace("{locale}", row.fallbackLocale)
            .replace("{value}", row.fallbackValue),
        ));
      }
      if (rowStatus(row) === "stale") {
        paintSourceBanner(pane, row, function () {
          post("/api/ops/translate", translateBody(state.project, state.locale, [keyId]));
        }, keyId);
      }
      var labelRow = el("div", "tr-label");
      labelRow.appendChild(el("span", "source-label", state.locale + " translation"));
      if (row.propagatedFrom) {
        labelRow.appendChild(el(
          "span", "propagation-badge",
          uiT("ed_propagated", "↗ propagated from {locale}").replace("{locale}", row.propagatedFrom),
        ));
      }
      pane.appendChild(labelRow);
      var label = el("label", "field", "");
      var area = document.createElement("textarea");
      area.id = "translation-field";
      area.dir = "auto";
      area.lang = state.locale;
      area.spellcheck = true;
      area.value = (row.values && row.values[state.locale]) || "";
      label.appendChild(area);
      pane.appendChild(label);
      area.addEventListener("input", markGlossary);
      area.addEventListener("input", function () { paintPhPreview(area); });
      area.addEventListener("input", function () {
        var live = document.getElementById("live-preview");
        if (live && live._refresh) live._refresh();
      });
      setTimeout(markGlossary, 0);
      setTimeout(function () { paintPhPreview(area); }, 0);
      paintLivePreview(pane, row, function () {
        var field = document.getElementById("translation-field");
        return field ? field.value : ((row.values && row.values[state.locale]) || "");
      });
      paintSuggest(pane, row, keyId);
      paintNear(pane, row);
    }

    paintQuality(pane, row);
    paintCompare(pane, row);

    var actions = el("div", "actions");
    function doSave() {
      post("/api/save", currentPayload(row)).then(function (data) {
        if (!data.ok) throw new Error(data.error || uiT("ed_save_failed", "save failed"));
        state.editedSession[rowId(row)] = true;
        openRow(row);
        refreshList();
      }).catch(showError);
    }
    state._saveFn = doSave;
    state._revertFn = function () {
      var field = document.getElementById("translation-field");
      if (field) field.value = (row.values && row.values[state.locale]) || "";
    };
    state._copySourceFn = function () {
      useTranslation(row.source || "");
    };
    function queueOp(path, body) {
      post(path, body).then(function (data) {
        showError(data.summary || data.error || uiT("ed_queued", "queued"));
      }).catch(showError);
    }
    var saveBtn = action(uiT("wf_save", "Save"), doSave);
    saveBtn.classList.add("btn-primary");
    actions.appendChild(saveBtn);
    actions.appendChild(action(uiT("ed_improve", "Improve"), function () {
      queueOp("/api/ops/improve", { locales: [state.locale], keys: [keyId], confirm: true });
    }));
    actions.appendChild(action(uiT("ed_rescore", "Rescore"), function () {
      queueOp("/api/ops/rescore", { locales: [state.locale], namespace: row.namespace, confirm: true });
    }));
    actions.appendChild(action(uiT("ed_keep_asis", "Keep as-is"), function () {
      post("/api/mark-intentional", { locale: state.locale, namespace: row.namespace, key: row.key });
    }));
    actions.appendChild(el("span", "toolbar-spacer"));
    actions.appendChild(action(uiT("ed_translate_key", "Translate this key"), function () {
      var locale = state.locale;
      if ((state.lite.frozenLocales || []).indexOf(locale) >= 0) locale = activeLocales(state.lite)[0] || locale;
      post("/api/ops/translate", translateBody(state.project, locale, [keyId]));
    }));
    pane.appendChild(actions);

    var secondary = el("div", "actions");
    secondary.appendChild(action(uiT("ed_shortcuts", "Shortcuts (?)"), function () { toggleShortcutHelp(); }));
    secondary.appendChild(action(row.locked ? uiT("ed_unlock", "Unlock") : uiT("ed_lock", "Lock"), function () {
      post("/api/lock", {
        locale: state.locale,
        namespace: row.namespace,
        key: row.key,
        locked: !row.locked,
      }).then(function (data) {
        if (!data.ok) throw new Error(data.error || uiT("ed_lock_failed", "lock failed"));
        openRow(row);
      }).catch(showError);
    }));
    secondary.appendChild(action(uiT("ed_verify", "Verify"), function () {
      post("/api/verify", { locale: state.locale, namespace: row.namespace, key: row.key, verify: true })
        .then(function () { openRow(row); });
    }));
    secondary.appendChild(action(uiT("ed_flag_english", "Flag English"), function () {
      var note = window.prompt(uiT("ed_flag_english_prompt", "What is wrong with the English source?"), "");
      if (note === null) return;
      post("/api/ops/flag-source", { namespace: row.namespace, key: row.key, note: note })
        .then(function (data) { showError(data.summary || data.error || uiT("ed_flagged", "Flagged")); })
        .catch(showError);
    }));
    secondary.appendChild(action(uiT("ed_flag_improve", "Flag and improve"), function () {
      post("/api/flag", {
        locale: state.locale,
        namespace: row.namespace,
        key: row.key,
        reason: "flagged from editor",
      }).then(function () {
        return post("/api/ops/improve", {
          project: state.project,
          locales: [state.locale],
          keys: [keyId],
          flagged: true,
        });
      }).then(function (data) {
        showError(data.summary || data.error || uiT("ed_queued", "Queued"));
      }).catch(showError);
    }));
    secondary.appendChild(action(uiT("ed_mark_example", "Mark example"), function () {
      post("/api/mark-example", { locale: state.locale, namespace: row.namespace, key: row.key });
    }));
    pane.appendChild(secondary);

    var note = document.createElement("textarea");
    note.value = row.llmNote || row.note || "";
    note.setAttribute("aria-label", uiT("ed_context_note", "Context note"));
    var saveNote = action(uiT("ed_save_note", "Save note"), function () {
      post("/api/context", { namespace: row.namespace, key: row.key, llmNote: note.value });
    });
    pane.appendChild(el("label", "field", uiT("ed_context_note", "Context note"))).appendChild(note);
    if (row.scanHint) {
      pane.appendChild(el(
        "p", "field-hint",
        uiT("ed_from_last_scan", "From the last scan:") + " " + row.scanHint,
      ));
    }
    pane.appendChild(saveNote);

    var tagsInput = document.createElement("input");
    tagsInput.type = "text";
    tagsInput.value = (row.tags || []).join(", ");
    tagsInput.placeholder = uiT("tags_placeholder", "checkout, legal");
    tagsInput.setAttribute("aria-label", uiT("tags_label", "Tags"));
    pane.appendChild(el("label", "field", uiT("tags_label", "Tags"))).appendChild(tagsInput);
    pane.appendChild(el("p", "hint", uiT("tags_hint", "Run translate or improve on a tag with --tag.")));
    pane.appendChild(action(uiT("tags_save", "Save tags"), function () {
      post("/api/context", {
        namespace: row.namespace, key: row.key,
        tags: tagsInput.value.split(",").map(function (t) { return t.trim(); }).filter(Boolean),
      });
    }));

    var file = document.createElement("input");
    file.type = "file";
    file.accept = "image/png,image/jpeg";
    file.addEventListener("change", function () {
      var chosen = file.files && file.files[0];
      if (!chosen) return;
      var reader = new FileReader();
      reader.onload = function () {
        var text = String(reader.result || "");
        var comma = text.indexOf(",");
        post("/api/screenshot-upload", {
          namespace: row.namespace,
          key: row.key,
          screen: row.screen || row.key,
          data: comma >= 0 ? text.slice(comma + 1) : text,
        });
      };
      reader.readAsDataURL(chosen);
    });
    pane.appendChild(file);
    renderScreenshotLinks(pane, row);
    scheduleValidate(row);
    applyStoredInsert();
  }

  function applyStoredInsert(attempt) {
    var stored;
    try { stored = sessionStorage.getItem("llm_tm_insert"); } catch (err) { return; }
    if (!stored) return;
    var field = insertTarget();
    if (!field) {
      // Row / plural fields may paint after the TM "Use" click — retry briefly.
      if ((attempt || 0) < 8) {
        window.requestAnimationFrame(function () { applyStoredInsert((attempt || 0) + 1); });
      }
      return;
    }
    field.value = stored;
    try { sessionStorage.removeItem("llm_tm_insert"); } catch (err) { /* ignore */ }
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function insertTarget() {
    var active = document.activeElement;
    if (active && active.id && active.id.indexOf("plural-") === 0) return active;
    return document.getElementById("plural-other") || document.getElementById("translation-field");
  }

  function useTranslation(text) {
    var field = insertTarget();
    if (!field) return;
    field.value = text;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function paintTm(pane, row) {
    var box = el("div", "tm-panel");
    pane.appendChild(box);
    var search = { text: "", fuzzy: false, min: "0.55" };

    function controls() {
      var bar = el("div", "tm-search");
      var input = el("input", "");
      input.type = "search";
      input.placeholder = uiT("ed_search_memory", "Search the memory");
      input.setAttribute("aria-label", uiT("ed_search_memory", "Search the memory"));
      input.value = search.text;
      var mode = el("select", "pc-select");
      [
        ["substring", uiT("ed_mode_contains", "Contains")],
        ["fuzzy", uiT("ed_mode_overlap", "Word overlap")],
      ].forEach(function (m) {
        var o = el("option", "", m[1]);
        o.value = m[0];
        mode.appendChild(o);
      });
      mode.value = search.fuzzy ? "fuzzy" : "substring";
      mode.setAttribute("aria-label", uiT("ed_search_mode", "Search mode"));
      var min = el("input", "tm-min");
      min.type = "number";
      min.min = "0.1"; min.max = "1"; min.step = "0.05";
      min.value = search.min;
      min.disabled = !search.fuzzy;
      min.title = uiT("ed_min_overlap_title", "Minimum word overlap (0.1 to 1)");
      min.setAttribute("aria-label", uiT("ed_min_overlap_aria", "Minimum overlap"));
      mode.addEventListener("change", function () { min.disabled = mode.value !== "fuzzy"; });
      var go = el("button", "btn", uiT("ed_search_btn", "Search"));
      go.type = "button";
      function run() {
        search.text = input.value.trim();
        search.fuzzy = mode.value === "fuzzy";
        search.min = min.value || "0.55";
        load();
      }
      go.addEventListener("click", run);
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") run(); });
      [input, mode, min, go].forEach(function (n) { bar.appendChild(n); });
      return bar;
    }

    function load() {
      box.replaceChildren(el("p", "excerpt", uiT("ed_loading_matches", "Loading matches…")));
      var args = {
        locale: state.locale,
        query: search.text || row.source || "",
        namespace: row.namespace,
        key: row.key,
        limit: "20",
      };
      if (search.fuzzy) { args.mode = "fuzzy"; args.min_similarity = search.min; }
      apiGet("/api/tm/concordance", args).then(function (payload) { show(payload); }).catch(function (err) {
        box.replaceChildren(el("p", "search-error", String(err.message || err)));
      });
    }

    function show(payload) {
      box.replaceChildren();
      box.appendChild(controls());
      box.appendChild(el("h3", "", search.fuzzy
        ? uiT("ed_memory_fuzzy", "Memory (word overlap)")
        : uiT("ed_memory", "Memory")));
      var current = (row.values && row.values[state.locale]) || "";
      if (current) box.appendChild(diffToggle(function () { show(payload); }));
      (payload.data && payload.data.matches || []).forEach(function (hit) {
        box.appendChild(matchLine(hit.source, hit.translation, hit.superseded, hit.translation, current));
      });
      if (!(payload.data && payload.data.matches && payload.data.matches.length)) {
        box.appendChild(el("p", "excerpt", uiT("ed_no_memory", "No memory matches.")));
      }
      box.appendChild(el("h3", "", uiT("ed_same_source", "Same source")));
      var siblings = (payload.data && payload.data.siblings) || [];
      siblings.forEach(function (hit) {
        box.appendChild(matchLine(hit.namespace + "." + hit.key, hit.translation, false, hit.translation));
      });
      if (!siblings.length) box.appendChild(el("p", "excerpt", uiT("ed_no_other_keys", "No other keys.")));
    }
    load();
  }

  // Text with placeholders wrapped in .ph spans (placeholders.js); plain text if it did not load.
  function phText(parent, text) {
    if (window.LLMPlaceholders) window.LLMPlaceholders.render(parent, text || "");
    else parent.appendChild(document.createTextNode(text || ""));
    return parent;
  }

  // Read-only highlighted copy of the target under the textarea.
  function paintPhPreview(area) {
    var box = document.getElementById("ph-preview");
    if (!box) {
      box = el("div", "ph-preview");
      box.id = "ph-preview";
      box.dir = "auto";
      area.parentNode.parentNode.insertBefore(box, area.parentNode.nextSibling);
    }
    box.replaceChildren();
    var has = window.LLMPlaceholders && window.LLMPlaceholders.tokenize(area.value).some(function (t) { return t.kind !== "text"; });
    box.hidden = !has;
    if (has) phText(box, area.value);
  }

  function composePluralIcu(row) {
    if (!(row.plural && row.plural.categories && row.plural.categories.length)) return "";
    var variable = row.plural.variable || "count";
    var parts = row.plural.categories.map(function (name) {
      var field = document.getElementById("plural-" + name);
      var body = field ? field.value : ((row.plural.branches && row.plural.branches[name]) || "");
      return name + " {" + body + "}";
    });
    return (row.plural.prefix || "") +
      "{" + variable + ", plural, " + parts.join(" ") + "}" +
      (row.plural.suffix || "");
  }

  function defaultSampleValue(name) {
    var n = String(name || "").toLowerCase();
    if (/^(count|n|num|number|qty|quantity|total|size|len|length)$/.test(n)) return "1";
    if (/^(mean|avg|average|ms|p95|pct|percent|ratio|rate)$/.test(n)) return "12.4";
    if (n === "gender" || n === "form") return "other";
    return "Sample";
  }

  function previewStorageKey(row) {
    return "llm-preview-values:" + (row.namespace || "") + "\t" + (row.key || "");
  }

  function loadSampleValues(row, names) {
    var stored = {};
    try {
      stored = JSON.parse(sessionStorage.getItem(previewStorageKey(row)) || "{}") || {};
    } catch (e) { stored = {}; }
    var out = {};
    (names || []).forEach(function (name) {
      out[name] = stored[name] != null && stored[name] !== ""
        ? String(stored[name])
        : defaultSampleValue(name);
    });
    return out;
  }

  function saveSampleValues(row, values) {
    try { sessionStorage.setItem(previewStorageKey(row), JSON.stringify(values || {})); }
    catch (e) { /* ignore */ }
  }

  // Interactive ICU / markdown / HTML preview (trusted HTML from /api/preview only).
  function paintLivePreview(pane, row, getText, formatHint) {
    var box = el("div", "live-preview");
    box.id = "live-preview";
    box.appendChild(el("div", "source-label", uiT("ed_preview", "Preview")));
    var fields = el("div", "preview-fields");
    var out = el("div", "preview-html");
    out.setAttribute("aria-live", "polite");
    var samplesBtn = el("button", "btn preview-samples-btn", uiT("ed_all_plural_samples", "All plural samples"));
    samplesBtn.type = "button";
    samplesBtn.hidden = true;
    var mode = "filled";
    var timer = null;
    var knownNames = [];

    function collectValues() {
      var values = {};
      Array.prototype.forEach.call(fields.querySelectorAll("input[data-ph]"), function (input) {
        values[input.getAttribute("data-ph")] = input.value;
      });
      return values;
    }

    function ensureFields(names) {
      var same = names.length === knownNames.length &&
        names.every(function (n, i) { return n === knownNames[i]; });
      if (same) return false;
      knownNames = names.slice();
      fields.replaceChildren();
      if (!names.length) {
        fields.hidden = true;
        samplesBtn.hidden = true;
        return false;
      }
      fields.hidden = false;
      var values = loadSampleValues(row, names);
      names.forEach(function (name) {
        var label = el("label", "preview-field");
        label.appendChild(el("span", "", name));
        var input = document.createElement("input");
        input.type = "text";
        input.setAttribute("data-ph", name);
        input.value = values[name] != null ? values[name] : defaultSampleValue(name);
        input.addEventListener("input", function () {
          saveSampleValues(row, collectValues());
          schedule();
        });
        label.appendChild(input);
        fields.appendChild(label);
      });
      samplesBtn.hidden = !names.length;
      saveSampleValues(row, collectValues());
      return true;
    }

    function guessFormat(text) {
      if (formatHint) return formatHint;
      if (row._previewFormat) return row._previewFormat;
      if (/\{[\w]+\s*,\s*(plural|select|selectordinal)\s*,/.test(text) || /\{[A-Za-z_]\w*\}/.test(text)) {
        return "icu";
      }
      if (/^\s*</.test(text)) return "html";
      if (/[*_`#\[]/.test(text)) return "markdown";
      return "icu";
    }

    function refresh() {
      var text = getText ? getText() : "";
      var fmt = guessFormat(text);
      var values = collectValues();
      var body = {
        text: text,
        locale: state.locale,
        format: fmt,
        values: values,
        mode: mode,
      };
      post("/api/preview", body).then(function (data) {
        if (!data || !data.ok) {
          out.textContent = (data && data.error) || uiT("ed_preview_failed", "Preview failed");
          return;
        }
        if (fmt === "icu") {
          if (ensureFields(data.placeholders || [])) {
            schedule();
            return;
          }
        } else {
          knownNames = [];
          fields.replaceChildren();
          fields.hidden = true;
          samplesBtn.hidden = true;
        }
        // Sandboxed iframe for HTML (and any server-rendered markup) so a
        // catalogue XSS cannot reach window.__LLM_TOKEN on the parent page.
        out.replaceChildren();
        if (!data.html) {
          out.textContent = text ? uiT("ed_no_preview", "(no preview)") : "";
          return;
        }
        if (fmt === "html" || /<[a-z]/i.test(data.html)) {
          var frame = document.createElement("iframe");
          frame.setAttribute("sandbox", "");
          frame.setAttribute("title", "preview");
          frame.style.width = "100%";
          frame.style.border = "0";
          frame.style.minHeight = "4rem";
          frame.srcdoc = data.html;
          out.appendChild(frame);
        } else {
          // Never trust non-HTML preview markup in the parent document.
          out.textContent = data.html;
        }
      }).catch(function (err) {
        out.textContent = String(err.message || err);
      });
    }

    function schedule() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(refresh, 180);
    }

    samplesBtn.addEventListener("click", function () {
      mode = mode === "samples" ? "filled" : "samples";
      samplesBtn.textContent = mode === "samples"
        ? uiT("ed_single_sample", "Single sample")
        : uiT("ed_all_plural_samples", "All plural samples");
      refresh();
    });

    box.appendChild(fields);
    box.appendChild(samplesBtn);
    box.appendChild(out);
    box._refresh = schedule;
    pane.appendChild(box);
    refresh();
  }

  // "Highlight differences" is a per-viewer preference; storage may be blocked.
  function diffModeOn() {
    try { return window.localStorage.getItem("llm-diff-mode") !== "0"; } catch (e) { return true; }
  }

  function diffToggle(onChange) {
    var label = el("label", "diff-toggle");
    var box = el("input", "");
    box.type = "checkbox";
    box.checked = diffModeOn();
    box.addEventListener("change", function () {
      try { window.localStorage.setItem("llm-diff-mode", box.checked ? "1" : "0"); } catch (e) { /* ignore */ }
      onChange();
    });
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + uiT("ed_highlight_diff", "Highlight differences")));
    return label;
  }

  // Render `to` with the words that differ from `from` marked; `both` also shows removed words.
  function diffInto(parent, from, to, both) {
    wordDiff(from, to).forEach(function (part) {
      if (part.t === "=") phText(parent, part.v);
      else if (part.t === "+") phText(parent.appendChild(el("span", "diff-ins")), part.v);
      else if (both) phText(parent.appendChild(el("span", "diff-del")), part.v);
    });
    return parent;
  }

  function matchLine(title, body, superseded, useText, compareTo) {
    var line = el("p", superseded ? "tm-hit is-superseded" : "tm-hit");
    line.appendChild(el("span", "row-key", title));
    line.appendChild(document.createTextNode(" "));
    if (compareTo && body && diffModeOn()) diffInto(line, compareTo, body, false);
    else phText(line, body || "");
    if (superseded) line.appendChild(el("span", "", " " + uiT("ed_superseded", "(superseded)")));
    if (useText) {
      line.appendChild(document.createTextNode(" "));
      line.appendChild(action(uiT("ed_use", "Use"), function () { useTranslation(useText); }));
    }
    return line;
  }

  var validateTimer = 0;
  function scheduleValidate(row) {
    clearTimeout(validateTimer);
    validateTimer = setTimeout(function () {
      post("/api/validate-key", currentPayload(row)).then(function (data) {
        var qa = document.getElementById("live-qa");
        if (!qa) return;
        qa.replaceChildren();
        var findings = data.errors || [];
        if (!findings.length) {
          qa.hidden = true;
          return;
        }
        qa.hidden = false;
        findings.forEach(function (item) {
          var kind = item.id === "V04" ? "qa-error" : "qa-warn";
          var line = el("p", kind);
          var code = String(item.id || "");
          var anchor = "checks.md#" + code.toLowerCase();
          if (data.docsUrl && code) {
            var link = el("a", "qa-code", code);
            link.href = data.docsUrl + "/" + anchor;
            link.target = "_blank";
            link.rel = "noopener";
            line.appendChild(link);
          } else {
            var plain = el("span", "qa-code", code);
            plain.title = "docs/" + anchor;
            line.appendChild(plain);
          }
          line.appendChild(document.createTextNode(" " + (item.message || "")));
          qa.appendChild(line);
        });
      });
    }, 300);
  }

  function paintDistance(pane, row) {
    apiGet("/api/history", { locale: state.locale, namespace: row.namespace, key: row.key })
      .then(function (payload) {
        var events = payload.events || [];
        if (!events.length) {
          pane.appendChild(el("p", "empty-state", uiT("ed_no_history", "No history.")));
          return;
        }
        events.forEach(function (event) {
          var delta = "";
          if (typeof event.prev === "string" && typeof event.next === "string") {
            delta = String(fullEditDistance(event.prev, event.next));
          }
          pane.appendChild(el(
            "p",
            "",
            (event.ts || "") + " " + (event.editedByName || event.provider || "")
              + " " + (event.trigger || "") + " Δ " + delta,
          ));
        });
      });
  }

  function paintHistory(pane, row) {
    apiGet("/api/history", { locale: state.locale, namespace: row.namespace, key: row.key })
      .then(function (payload) {
        var current = (row.values && row.values[state.locale]) || "";
        var machine = "";
        (payload.events || []).forEach(function (event) {
          if (!machine && event.provider && event.provider !== "human" && event.provider !== "agent") {
            machine = event.next || "";
          }
        });
        if (!machine && (payload.events || []).length) {
          machine = (payload.events[0].next || payload.events[0].prev || "");
        }
        var dist = fullEditDistance(machine, current);
        var distLine = el(
          "p", "edit-distance",
          uiT("ed_edit_distance", "Edit distance (machine → current): {n}").replace("{n}", String(dist)),
        );
        distLine.dataset.editDistance = String(dist);
        pane.appendChild(distLine);
        var changed = payload.sourceChange && payload.sourceChange.prev_src
          ? { prevSource: payload.sourceChange.prev_src, nextSource: payload.sourceChange.next_src,
              ts: payload.sourceChange.timestamp }
          : (payload.events || []).filter(function (event) {
              return event.prevSource && event.nextSource;
            })[0];
        if (changed) {
          var why = el(
            "p",
            "source-changed",
            uiT(
              "ed_source_changed",
              "English changed from “{prev}” to “{next}” on {date}.",
            )
              .replace("{prev}", changed.prevSource)
              .replace("{next}", changed.nextSource)
              .replace("{date}", String(changed.ts || "").slice(0, 10)),
          );
          why.dataset.sourceChanged = "1";
          pane.appendChild(why);
        }
        if ((payload.events || []).length) pane.appendChild(diffToggle(function () {
          pane.replaceChildren();
          paintHistory(pane, row);
        }));
        (payload.events || []).forEach(function (event) {
          var line = el("p", "history-event");
          var who = event.editedByName || event.provider || "";
          var meta = String(event.ts || "").slice(0, 16).replace("T", " ")
            + " " + who + (event.trigger ? " (" + event.trigger + ")" : "") + " ";
          line.appendChild(el("span", "history-meta", meta));
          if (diffModeOn() && typeof event.prev === "string" && typeof event.next === "string") {
            diffInto(line.appendChild(el("span", "history-text")), event.prev, event.next, true);
          } else {
            phText(line.appendChild(el("span", "history-text")), event.next || "");
          }
          var restore = el("button", "btn", uiT("ed_restore", "Restore"));
          restore.type = "button";
          restore.addEventListener("click", function () {
            post("/api/revert", {
              locale: state.locale,
              namespace: row.namespace,
              key: row.key,
              value: event.next || event.prev || "",
            }).then(function () { openRow(row); });
          });
          line.appendChild(restore);
          pane.appendChild(line);
        });
      });
  }

  function paintDiff(pane, row) {
    apiGet("/api/history", { locale: state.locale, namespace: row.namespace, key: row.key })
      .then(function (payload) {
        var machine = "";
        (payload.events || []).forEach(function (event) {
          if (!machine && event.provider && event.provider !== "human") machine = event.next || "";
        });
        var current = (row.values && row.values[state.locale]) || "";
        var out = el("div", "diff-view");
        pane.appendChild(diffToggle(draw));
        pane.appendChild(out);
        function draw() {
          out.replaceChildren();
          if (!machine) {
            out.appendChild(el("p", "excerpt", uiT("ed_no_machine", "(no machine version)")));
          }
          if (machine && diffModeOn()) {
            diffInto(out.appendChild(el("p", "")), machine, current, true);
            return;
          }
          if (machine) phText(out.appendChild(el("p", "excerpt")), machine);
          phText(out.appendChild(el("p", "")), current);
        }
        draw();
      });
  }

  function loadCollection(name) {
    var list = document.getElementById("string-list");
    if (!list) return;
    state.collection = name;
    state.docPath = state.docPath || null;
    state.docSection = state.docSection != null ? state.docSection : null;
    apiGet("/api/collection-files", { collection: name, locale: state.locale })
      .then(function (payload) {
        list.replaceChildren();
        var wrap = el("div", "tbl-wrap");
        var table = el("table", "editor-table");
        var thead = el("thead", "");
        var hr = el("tr", "");
        [
          uiT("ed_col_path", "path"),
          state.locale || uiT("ed_col_locale", "locale"),
          uiT("ed_col_coverage", "coverage"),
        ].forEach(function (label) {
          hr.appendChild(el("th", "", label));
        });
        thead.appendChild(hr);
        table.appendChild(thead);
        var tbody = el("tbody", "");
        tbody.id = "editor-tbody";
        (payload.files || []).forEach(function (file) {
          var path = file.path || file;
          var tr = el("tr", "editor-row");
          if (state.docPath === path) tr.classList.add("is-active");
          tr.appendChild(el("td", "", path));
          tr.appendChild(el("td", "", state.locale || ""));
          tr.appendChild(el("td", "", file.coverage != null ? String(file.coverage) : ""));
          tr.addEventListener("click", function () {
            state.docPath = path;
            state.docSection = null;
            state.tab = "translation";
            openCollectionFile(name, path, list);
          });
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        list.appendChild(wrap);
        state.matchingTotal = (payload.files || []).length;
        updateStats();
        if (state.docPath) openCollectionFile(name, state.docPath, list);
      });
  }

  function openCollectionFile(collection, path, list) {
    apiGet("/api/collection-file", {
      collection: collection,
      locale: state.locale,
      path: path,
    }).then(function (doc) {
      var host = list || document.getElementById("string-list");
      if (!host) return;
      var existing = document.getElementById("collection-edit");
      if (existing) existing.remove();
      var panel = el("div", "pane editor-expand-pane collection-edit");
      panel.id = "collection-edit";

      var head = el("div", "editor-keyhead");
      head.appendChild(el("div", "editor-keytitle", doc.path || path));
      var back = el("button", "btn", uiT("ed_back_to_files", "Back to files"));
      back.type = "button";
      back.addEventListener("click", function () {
        state.docPath = null;
        state.docSection = null;
        loadCollection(collection);
      });
      head.appendChild(back);
      panel.appendChild(head);

      var sectionWrap = el("div", "tbl-wrap");
      var sectionTable = el("table", "editor-table collection-sections");
      var sh = el("tr", "");
      [
        uiT("ed_col_section", "section"),
        uiT("ed_col_heading", "heading"),
        state.locale || uiT("ed_col_locale", "locale"),
      ].forEach(function (label) {
        sh.appendChild(el("th", "", label));
      });
      var sectionHead = el("thead", "");
      sectionHead.appendChild(sh);
      sectionTable.appendChild(sectionHead);
      var sectionBody = el("tbody", "");
      (doc.sections || []).forEach(function (sec) {
        var tr = el("tr", "editor-row");
        if (state.docSection === sec.index) tr.classList.add("is-active");
        tr.appendChild(el("td", "", String(sec.index)));
        tr.appendChild(el("td", "", sec.heading || ("Section " + sec.index)));
        var snippet = (sec.target || sec.source || "").replace(/\s+/g, " ").trim();
        if (snippet.length > 80) snippet = snippet.slice(0, 80) + "…";
        tr.appendChild(el("td", "", snippet));
        tr.addEventListener("click", function () {
          state.docSection = sec.index;
          state.tab = "translation";
          paintDocSection(panel, doc, sec);
          Array.prototype.forEach.call(sectionBody.querySelectorAll("tr"), function (node) {
            node.classList.remove("is-active");
          });
          tr.classList.add("is-active");
        });
        sectionBody.appendChild(tr);
      });
      sectionTable.appendChild(sectionBody);
      sectionWrap.appendChild(sectionTable);
      panel.appendChild(sectionWrap);

      var detail = el("div", "");
      detail.id = "collection-section-detail";
      panel.appendChild(detail);
      host.appendChild(panel);

      if (state.docSection != null) {
        var match = (doc.sections || []).filter(function (s) { return s.index === state.docSection; })[0];
        if (match) paintDocSection(panel, doc, match);
      } else if ((doc.sections || []).length === 1) {
        state.docSection = doc.sections[0].index;
        paintDocSection(panel, doc, doc.sections[0]);
      }
    }).catch(showError);
  }

  function paintDocSection(panel, doc, sec) {
    var detail = document.getElementById("collection-section-detail");
    if (!detail) return;
    detail.replaceChildren();
    var row = {
      namespace: sec.namespace || doc.namespace,
      key: String(sec.key != null ? sec.key : sec.index),
      source: sec.source || "",
      values: {},
      statuses: {},
      _previewFormat: doc.format || "markdown",
      _collection: doc.collection,
      _path: doc.path,
      _section: sec.index,
    };
    row.values[state.locale] = sec.target || "";
    state.row = row;

    var pane = el("div", "pane editor-expand-pane");
    pane.id = "editor-pane";
    detail.appendChild(pane);

    var scroll = el("div", "pane-scroll");
    var source = el("div", "source-card");
    var sourceLocale = doc.sourceLocale || (state.lite && state.lite.sourceLocale) || "en";
    source.appendChild(el(
      "div", "source-label",
      uiT("ed_source_section", "Source ({locale}) · {heading}")
        .replace("{locale}", sourceLocale)
        .replace("{heading}", sec.heading || ""),
    ));
    var srcRaw = el("div", "source-text");
    phText(srcRaw, sec.source || "");
    source.appendChild(srcRaw);
    scroll.appendChild(source);

    var tabs = el("div", "tabs");
    [
      { id: "translation", key: "ed_tab_translation", label: "Translation" },
      { id: "history", key: "ed_tab_history", label: "History" },
      { id: "comments", key: "ed_tab_comments", label: "Comments" },
    ].forEach(function (item) {
      var button = el("button", "tab-btn" + (state.tab === item.id ? " is-active" : ""), uiT(item.key, item.label));
      button.type = "button";
      button.addEventListener("click", function () {
        state.tab = item.id;
        paintDocSection(panel, doc, sec);
      });
      tabs.appendChild(button);
    });
    scroll.appendChild(tabs);
    var host = el("div", "tab-panel");
    scroll.appendChild(host);
    pane.appendChild(scroll);

    if (state.tab === "history") return paintHistory(host, row);
    if (state.tab === "comments") return paintComments(host, row);

    var labelRow = el("div", "tr-label");
    labelRow.appendChild(el("span", "source-label", state.locale + " translation"));
    host.appendChild(labelRow);
    var label = el("label", "field field-tall", "");
    var area = document.createElement("textarea");
    area.id = "translation-field";
    area.className = "doc-section-textarea";
    area.dir = "auto";
    area.lang = state.locale;
    area.spellcheck = true;
    area.rows = 16;
    area.value = sec.target || "";
    label.appendChild(area);
    host.appendChild(label);

    paintLivePreview(host, row, function () {
      return area.value;
    }, doc.format || "markdown");
    area.addEventListener("input", function () {
      var live = document.getElementById("live-preview");
      if (live && live._refresh) live._refresh();
    });

    var actions = el("div", "actions");
    function doSave() {
      post("/api/collection-file", {
        collection: doc.collection,
        locale: state.locale,
        path: doc.path,
        section: sec.index,
        text: area.value,
      }).then(function (data) {
        if (!data.ok) throw new Error(data.error || uiT("ed_save_failed", "save failed"));
        sec.target = area.value;
        row.values[state.locale] = area.value;
        showError(uiT("ed_saved_section", "Saved {path}#{index}")
          .replace("{path}", doc.path)
          .replace("{index}", String(sec.index)));
        openCollectionFile(doc.collection, doc.path, document.getElementById("string-list"));
      }).catch(showError);
    }
    state._saveFn = doSave;
    var saveBtn = action(uiT("wf_save", "Save"), doSave);
    saveBtn.classList.add("btn-primary");
    actions.appendChild(saveBtn);
    host.appendChild(actions);
  }

  // C-012: screenshots linked to this key, with the tagged region outlined.
  function renderScreenshotLinks(pane, row) {
    var box = el("div", "shot-links");
    pane.appendChild(box);
    post("/api/ops/screenshot-link", { action: "list", namespace: row.namespace, key: row.key })
      .then(function (res) {
        var links = ((res && res.data) || {}).links || [];
        if (!links.length) return;
        box.appendChild(el("h4", "", uiT("shots_title", "Linked screenshots")));
        links.forEach(function (link) {
          var item = el("figure", "shot-link");
          var wrap = el("div", "shot-wrap");
          wrap.style.cssText = "position:relative;display:inline-block;max-width:100%;";
          var img = document.createElement("img");
          img.alt = link.note || link.file;
          img.style.cssText = "display:block;max-width:100%;";
          wrap.appendChild(img);
          if (link.region) {
            var mark = el("div", "shot-region");
            mark.style.cssText = "position:absolute;border:2px solid #e5484d;pointer-events:none;"
              + "left:" + link.region.x * 100 + "%;top:" + link.region.y * 100 + "%;"
              + "width:" + link.region.w * 100 + "%;height:" + link.region.h * 100 + "%;";
            wrap.appendChild(mark);
          }
          item.appendChild(wrap);
          item.appendChild(el("figcaption", "hint", link.note || link.file));
          item.appendChild(action(uiT("shots_unlink", "Unlink"), function () {
            post("/api/ops/screenshot-link", { action: "unlink", link: link.id }).then(function () {
              item.remove();
            });
          }));
          box.appendChild(item);
          (window.LLMApi && LLMApi.apiBlob
            ? LLMApi.apiBlob("/api/screenshot", { project: state.project, file: link.file })
            : fetch("/api/screenshot?" + params({ file: link.file }), { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.blob() : null; })
          ).then(function (blob) { if (blob) img.src = URL.createObjectURL(blob); })
            .catch(function () {});
        });
      });
  }

  function action(label, fn) {
    var button = el("button", "btn", label);
    button.type = "button";
    button.addEventListener("click", fn);
    return button;
  }

  function showError(err) {
    var pane = document.getElementById("editor-pane")
      || document.getElementById("string-list");
    if (pane) pane.appendChild(el("p", "search-error", String(err.message || err)));
  }

  var helpOpen = false;
  function toggleShortcutHelp(force) {
    helpOpen = force == null ? !helpOpen : !!force;
    var box = document.getElementById("shortcut-help");
    if (!box) {
      box = el("div", "shortcut-help");
      box.id = "shortcut-help";
      box.innerHTML = "<strong>" + uiT("ed_cat_shortcuts", "CAT shortcuts") + "</strong><ul>"
        + "<li>" + uiT("ed_sc_save", "Ctrl+Enter / Ctrl+S — Save") + "</li>"
        + "<li>" + uiT("ed_sc_revert", "Escape — Revert field") + "</li>"
        + "<li>" + uiT("ed_sc_nav", "Alt+↓ / Alt+↑ — Next / previous row") + "</li>"
        + "<li>" + uiT("ed_sc_copy", "Ctrl+Shift+I — Copy source") + "</li>"
        + "<li>" + uiT("ed_sc_help", "? — Toggle this help") + "</li>"
        + "</ul><p>" + uiT(
          "ed_sc_note",
          "Shortcuts (except Save) do not fire inside other fields. Enter in search does not save.",
        ) + "</p>";
      document.body.appendChild(box);
    }
    box.hidden = !helpOpen;
  }

  function moveRow(delta) {
    var list = document.getElementById("string-list");
    if (!list) return;
    var rows = Array.prototype.slice.call(list.querySelectorAll("tr.editor-row[data-llm-key]"));
    if (!rows.length) return;
    var idx = -1;
    if (state.row) {
      var want = rowId(state.row);
      rows.forEach(function (node, i) {
        if ((node.dataset.llmNs + "\t" + node.dataset.llmKey) === want) idx = i;
      });
    }
    var next = rows[Math.max(0, Math.min(rows.length - 1, idx + delta))];
    if (next) next.click();
  }

  var navGen = window.__LLM_NAV_GEN || 0;
  document.addEventListener("keydown", function (event) {
    if ((window.__LLM_NAV_GEN || 0) !== navGen) return;
    var target = event.target || {};
    var action = shortcutAction(event, {
      helpOpen: helpOpen,
      targetTag: target.tagName || "",
      targetId: target.id || "",
      targetType: target.type || "",
    });
    if (!action) return;
    if (action === "help") {
      event.preventDefault();
      toggleShortcutHelp();
      return;
    }
    if (helpOpen) return;
    if (action === "save") {
      event.preventDefault();
      if (typeof state._saveFn === "function") state._saveFn();
      return;
    }
    if (action === "revert") {
      event.preventDefault();
      if (typeof state._revertFn === "function") state._revertFn();
      return;
    }
    if (action === "copySource") {
      event.preventDefault();
      if (typeof state._copySourceFn === "function") state._copySourceFn();
      return;
    }
    if (action === "next") {
      event.preventDefault();
      moveRow(1);
      return;
    }
    if (action === "prev") {
      event.preventDefault();
      moveRow(-1);
    }
  });

  function openAddLocale() {
    var lite = state.lite || {};
    var taken = {};
    allLocales(lite).forEach(function (code) { taken[code] = true; });
    if (lite.sourceLocale) taken[lite.sourceLocale] = true;

    var names = null;
    try {
      if (typeof Intl !== "undefined" && typeof Intl.DisplayNames === "function") {
        names = new Intl.DisplayNames(["en"], { type: "language" });
      }
    } catch (err) { names = null; }
    function localeName(code) {
      if (!names) return code;
      try { return names.of(code) || code; } catch (err) { return code; }
    }
    var codes = {};
    var list = ["en", "de", "pl", "fr", "es", "it", "pt", "nl", "cs", "ru", "ja", "ko", "zh", "ar", "tr", "sv"];
    try {
      if (typeof Intl !== "undefined" && typeof Intl.supportedValuesOf === "function") {
        list = Intl.supportedValuesOf("language");
      }
    } catch (err) { /* keep the short list */ }
    list.forEach(function (code) { codes[code] = true; });
    ["pt-BR", "pt-PT", "zh-Hans", "zh-Hant", "en-GB", "en-US"].forEach(function (code) {
      codes[code] = true;
    });
    var catalog = Object.keys(codes).map(function (code) {
      return { code: code, name: localeName(code) };
    });
    catalog.sort(function (a, b) {
      var an = (a.name || a.code).toLowerCase();
      var bn = (b.name || b.code).toLowerCase();
      if (an < bn) return -1;
      if (an > bn) return 1;
      return a.code < b.code ? -1 : 1;
    });

    window.localePicker(catalog, taken, function (locale, done) {
      post("/api/add-locale", { locale: locale }).then(function (data) {
        if (!data.ok) throw new Error(data.error || uiT("ed_add_locale_failed", "Could not add the locale"));
        done(null);
        return loadLite();
      }).then(function (lt) {
        if (lt) render();
      }).catch(function (ex) { done(String(ex.message || ex)); });
    });
  }

  function boot() {
    state.project = select.value;
    state.selected = {};
    state.row = null;
    state.listGen = (state.listGen || 0) + 1;
    if (!state.project) {
      body.replaceChildren(el("p", "empty-state", uiT("ed_select_project", "Select a project…")));
      return;
    }
    body.replaceChildren(el("p", "empty-state", uiT("dash_loading", "Loading…")));
    whenMe().then(function (me) {
      state.me = me;
      return loadLite();
    }).then(render).catch(function (err) {
      body.replaceChildren(el("p", "search-error", String(err.message || err)));
    });
  }

  select.addEventListener("change", function () { state.wfSummary = null; boot(); });
  var ready = (window.uiLocale && typeof window.uiLocale.whenReady === "function")
    ? window.uiLocale.whenReady()
    : Promise.resolve();
  ready.then(function () {
    if (select.value) boot();
    else body.replaceChildren(el("p", "empty-state", uiT("ed_select_project", "Select a project…")));
  });
})(typeof window !== "undefined" ? window : globalThis);
