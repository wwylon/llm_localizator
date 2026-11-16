(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  var select = document.getElementById("project-select");
  if (!page || page.dataset.page !== "activity" || !root || !select) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  var state = {
    translators: [],
    timeline: [],
    userId: "",
    trigger: "",
    allowed: false,
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function project() {
    return select.value || "";
  }

  function relativeTime(iso) {
    if (!iso) return "—";
    var then = Date.parse(iso);
    if (!then) return iso;
    var sec = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (sec < 60) return uiT("time_just_now", "just now");
    if (sec < 3600) {
      return uiT("time_m_ago", "{n}m ago").replace("{n}", String(Math.floor(sec / 60)));
    }
    if (sec < 86400) {
      return uiT("time_h_ago", "{n}h ago").replace("{n}", String(Math.floor(sec / 3600)));
    }
    if (sec < 86400 * 14) {
      return uiT("time_d_ago", "{n}d ago").replace("{n}", String(Math.floor(sec / 86400)));
    }
    return new Date(then).toLocaleString();
  }

  function triggerSummary(byTrigger) {
    var parts = [];
    Object.keys(byTrigger || {}).sort().forEach(function (name) {
      parts.push(name + " " + byTrigger[name]);
    });
    return parts.length ? parts.join(" · ") : "—";
  }

  function triggersInData() {
    var seen = {};
    state.timeline.forEach(function (row) {
      if (row.trigger) seen[row.trigger] = true;
    });
    state.translators.forEach(function (row) {
      Object.keys(row.byTrigger || {}).forEach(function (name) {
        seen[name] = true;
      });
    });
    return Object.keys(seen).sort();
  }

  function filteredTimeline() {
    return state.timeline.filter(function (row) {
      if (state.userId && row.user_id !== state.userId) return false;
      if (state.trigger && row.trigger !== state.trigger) return false;
      return true;
    });
  }

  (function () {
    var host = document.getElementById("activity-head-actions");
    if (host && window.LLMHelp && !host.querySelector(".help-trigger")) host.appendChild(window.LLMHelp.helpBtn("activity:general"));
  })();
  function paint() {
    root.replaceChildren();
    if (!state.allowed) {
      root.appendChild(el("p", "empty-state", uiT("act_admin_required", "Admin or Supervisor required.")));
      return;
    }

    var filters = el("div", "activity-filters");
    var userLabel = el("label", "field", uiT("act_translator", "Translator"));
    var userSel = document.createElement("select");
    userSel.className = "activity-filter";
    var allUsers = document.createElement("option");
    allUsers.value = "";
    allUsers.textContent = uiT("act_all_translators", "All translators");
    userSel.appendChild(allUsers);
    state.translators.forEach(function (row) {
      var opt = document.createElement("option");
      opt.value = row.user_id;
      opt.textContent = row.username + " (" + row.total + ")";
      if (row.user_id === state.userId) opt.selected = true;
      userSel.appendChild(opt);
    });
    userSel.addEventListener("change", function () {
      state.userId = userSel.value;
      load();
    });
    userLabel.appendChild(userSel);
    filters.appendChild(userLabel);

    var trigLabel = el("label", "field", uiT("act_trigger", "Trigger"));
    var trigSel = document.createElement("select");
    trigSel.className = "activity-filter";
    var allTrig = document.createElement("option");
    allTrig.value = "";
    allTrig.textContent = uiT("act_all_triggers", "All triggers");
    trigSel.appendChild(allTrig);
    triggersInData().forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (name === state.trigger) opt.selected = true;
      trigSel.appendChild(opt);
    });
    trigSel.addEventListener("change", function () {
      state.trigger = trigSel.value;
      paint();
    });
    trigLabel.appendChild(trigSel);
    filters.appendChild(trigLabel);
    root.appendChild(filters);

    var exportRow = el("div", "activity-export");
    exportRow.appendChild(el("span", "field", uiT("act_export_csv", "Export CSV")));
    [
      ["user", "act_by_translator", "By translator"],
      ["locale", "act_by_locale", "By locale"],
      ["locale+user", "act_by_locale_user", "By locale and translator"],
    ].forEach(function (pair) {
      var a = el("a", "btn btn-small", uiT(pair[1], pair[2]));
      a.href = "/api/metrics?format=csv&by=" + encodeURIComponent(pair[0]) +
        "&project=" + encodeURIComponent(project());
      a.setAttribute("download", "");
      exportRow.appendChild(a);
    });
    root.appendChild(exportRow);

    var tableWrap = el("div", "users-section");
    tableWrap.appendChild(el(
      "div", "users-section-label",
      uiT("act_translators_count", "Translators — {n}").replace("{n}", String(state.translators.length)),
    ));
    var table = el("table", "users-table activity-table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    [
      ["act_col_translator", "Translator"],
      ["act_col_changes", "Changes"],
      ["act_col_by_trigger", "By trigger"],
      ["act_col_last", "Last activity"],
    ].forEach(function (row) {
      hr.appendChild(el("th", "", uiT(row[0], row[1])));
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    var rows = state.translators.filter(function (row) {
      return !state.userId || row.user_id === state.userId;
    });
    if (!rows.length) {
      var empty = document.createElement("tr");
      var td = document.createElement("td");
      td.colSpan = 4;
      td.appendChild(el("p", "empty-state", uiT("act_none", "No attributed edits yet for this project.")));
      empty.appendChild(td);
      tbody.appendChild(empty);
    } else {
      rows.forEach(function (row) {
        var tr = document.createElement("tr");
        tr.appendChild(el("td", "", row.username));
        tr.appendChild(el("td", "activity-num", String(row.total)));
        tr.appendChild(el("td", "activity-triggers", triggerSummary(row.byTrigger)));
        tr.appendChild(el("td", "users-muted", relativeTime(row.lastAt)));
        tr.addEventListener("click", function () {
          state.userId = row.user_id;
          load();
        });
        tr.style.cursor = "pointer";
        tbody.appendChild(tr);
      });
    }
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    root.appendChild(tableWrap);

    var timeline = el("div", "users-section");
    var events = filteredTimeline();
    timeline.appendChild(el(
      "div", "users-section-label",
      uiT("act_timeline_count", "Timeline — {n}").replace("{n}", String(events.length)),
    ));
    if (!events.length) {
      timeline.appendChild(el("p", "empty-state", uiT("act_no_match", "No events match the filter.")));
    } else {
      var list = el("div", "activity-timeline");
      events.forEach(function (ev) {
        var row = el("div", "activity-timeline-row");
        row.appendChild(el("span", "activity-ts", relativeTime(ev.ts)));
        row.appendChild(el("span", "activity-user", ev.username || ev.user_id));
        row.appendChild(el("span", "activity-trigger", ev.trigger || "—"));
        row.appendChild(el("span", "activity-locale", ev.locale || ""));
        var key = (ev.namespace ? ev.namespace + "/" : "") + (ev.key || "");
        row.appendChild(el("span", "activity-key", key));
        list.appendChild(row);
      });
      timeline.appendChild(list);
    }
    root.appendChild(timeline);
  }

  function load() {
    var name = project();
    if (!name) {
      root.replaceChildren(el("p", "empty-state", uiT("ed_select_project", "Select a project…")));
      return;
    }
    root.replaceChildren(el("p", "empty-state", uiT("dash_loading_activity", "Loading activity…")));
    var headers = {};
    if (window.__LLM_TOKEN) headers["X-LLM-Token"] = window.__LLM_TOKEN;
    fetch("/api/auth/me", { headers: headers, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (me) {
        var role = me && me.role;
        state.allowed = !!(me && me.authenticated && (
          role === "Admin" || role === "Supervisor"
        ));
        if (!state.allowed) {
          paint();
          return null;
        }
        var qs = "?project=" + encodeURIComponent(name) + "&limit=200";
        if (state.userId) qs += "&user_id=" + encodeURIComponent(state.userId);
        return fetch("/api/translator-activity" + qs, {
          headers: headers,
          credentials: "same-origin",
        }).then(function (r) { return r.json().then(function (data) {
          return { status: r.status, data: data };
        }); });
      })
      .then(function (res) {
        if (!res) return;
        if (res.status === 403 || (res.data && res.data.ok === false && res.status >= 400)) {
          state.allowed = false;
          paint();
          return;
        }
        state.translators = (res.data && res.data.translators) || [];
        state.timeline = (res.data && res.data.timeline) || [];
        paint();
      })
      .catch(function () {
        root.replaceChildren(el("p", "empty-state", uiT("setup_request_failed", "Request failed.")));
      });
  }

  function boot() {
    select.addEventListener("change", function () {
      if (select.value) load();
    });
    if (select.value) load();
  }
  var ready = (window.uiLocale && typeof window.uiLocale.whenReady === "function")
    ? window.uiLocale.whenReady()
    : Promise.resolve();
  ready.then(boot);
})();
