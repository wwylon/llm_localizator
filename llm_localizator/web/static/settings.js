(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "settings" || !root) return;

  var _dn = null;
  try { _dn = new Intl.DisplayNames(["en"], { type: "language" }); } catch (e) {}
  function localeLabel(code) {
    if (!_dn) return code;
    try { var n = _dn.of(code); return n && n !== code ? code + " – " + n : code; } catch (e) { return code; }
  }

  var state = null;
  var statusEl = null;
  var TAB_IDS = ["llm", "locales", "project", "web", "permissions"];

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

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
  }

  function switchTab(name) {
    if (TAB_IDS.indexOf(name) < 0) name = "llm";
    document.querySelectorAll(".settings-tab").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-tab") === name);
    });
    document.querySelectorAll(".settings-panel").forEach(function (panel) {
      panel.classList.toggle("is-active", panel.getAttribute("data-panel") === name);
    });
    if (history.replaceState) {
      history.replaceState(null, "", "#"+ name);
    } else {
      location.hash = name;
    }
  }

  function bindTabs() {
    var tabs = document.getElementById("settings-tabs");
    if (!tabs) return;
    tabs.addEventListener("click", function (ev) {
      var btn = ev.target.closest(".settings-tab");
      if (!btn) return;
      switchTab(btn.getAttribute("data-tab"));
    });
    var hash = (location.hash || "").replace(/^#/, "");
    if (hash === "perms") hash = "permissions";
    switchTab(hash || "llm");
  }

  var dirty = false;

  function markClean() { dirty = false; }
  function markDirty() { dirty = true; }
  function confirmLeaveIfDirty() {
    if (!dirty) return true;
    return window.confirm(uiT("set_unsaved_leave", "You have unsaved Settings changes. Leave without saving?"));
  }

  function post(body) {
    body.project = project();
    setStatus(uiT("pc_saving", "Saving…"));
    var send = (window.LLMApi && LLMApi.apiPost)
      ? LLMApi.apiPost("/api/settings", body)
      : fetch("/api/settings", {
          method: "POST",
          headers: (window.LLMApi && LLMApi.authHeaders) ? LLMApi.authHeaders() : { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }).then(function (r) { return r.json(); });
    return send.then(function (result) {
      if (!result.ok) {
        setStatus(result.error || uiT("set_save_failed", "Save failed."));
        return result;
      }
      setStatus(uiT("set_saved", "Saved."));
      markClean();
      // load() repaints the page and recreates the status line: say it again afterwards, or the confirmation
      // flashes for a few milliseconds.
      return load().then(function () { setStatus(uiT("set_saved", "Saved.")); return result; });
    });
  }

  function confirmModelWrite() {
    return window.confirm(uiT(
      "set_model_adr12_confirm",
      "Changing models or judge pins requires bakeoff evidence (ADR-12).\n\nContinue only if a Winner note exists in experiments/quality_bakeoff.",
    ));
  }

  function card(title, hint, helpKey) {
    var box = el("div", "settings-card");
    var head = el("div", "settings-card-head");
    var titleRow = el("div", "settings-card-title-row");
    titleRow.appendChild(el("div", "section-label", title));
    if (helpKey && window.LLMHelp) {
      titleRow.appendChild(window.LLMHelp.helpBtn(helpKey));
    }
    head.appendChild(titleRow);
    if (hint) head.appendChild(el("p", "field-hint", hint));
    box.appendChild(head);
    return box;
  }

  function actionsRow() {
    return el("div", "settings-actions");
  }

  // ---- Engine card (ADR-156): one switch for the provider + model of every pipeline role ----

  var STATUS_LABELS = {
    benchmarked: ["eng_status_benchmarked", "benchmarked"],
    waiver: ["eng_status_waiver", "approved waiver"],
    smoke: ["eng_status_smoke", "smoke test only"],
    unbenchmarked: ["eng_status_unbenchmarked", "not benchmarked"],
  };

  function opPost(command, body) {
    body.project = project();
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost("/api/ops/" + command, body);
    return fetch("/api/ops/" + command, {
      method: "POST",
      headers: (window.LLMApi && LLMApi.authHeaders) ? LLMApi.authHeaders() : { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function paintEngine(data) {
    var pipe = data.pipeline || {};
    var wrap = card(
      uiT("eng_title", "Engine"),
      uiT("eng_hint", "One switch for every model: translation, back-translation scoring and improve. Locale rows below can still override it."),
      "settings:engine"
    );
    var current = el("p", "eng-current");
    current.appendChild(el("span", "field-label", uiT("eng_current", "Current engine") + ": "));
    current.appendChild(el("span", "settings-strong", pipe.engine || uiT("eng_none", "none (models set by hand)")));
    wrap.appendChild(current);

    // Effective models per role, read from the loaded config.
    var roles = el("table", "settings-table eng-roles");
    roles.innerHTML = "<thead><tr><th>" + uiT("eng_col_role", "Role") + "</th><th>" + uiT("set_col_type", "Type") +
      "</th><th>" + uiT("eng_col_model", "Model") + "</th></tr></thead>";
    var rb = document.createElement("tbody");
    var roleNames = { translate: uiT("eng_role_translate", "Translate"), score: uiT("eng_role_score", "Score (back-translation)"),
      improve: uiT("eng_role_improve", "Improve"), judge: uiT("eng_role_judge", "Judge") };
    (pipe.roles || []).forEach(function (r) {
      var tr = document.createElement("tr");
      tr.appendChild(el("td", "", roleNames[r.role] || r.role));
      var kind = el("td", "");
      kind.appendChild(el("span", "settings-badge", r.provider || "—"));
      tr.appendChild(kind);
      tr.appendChild(el("td", "settings-mono", r.model || uiT("eng_off", "off")));
      rb.appendChild(tr);
    });
    (pipe.localeOverrides || []).forEach(function (o) {
      var tr = document.createElement("tr");
      tr.appendChild(el("td", "", uiT("eng_role_locale", "Translate") + " · " + o.locale));
      var kind = el("td", "");
      kind.appendChild(el("span", "settings-badge", o.provider || "—"));
      tr.appendChild(kind);
      tr.appendChild(el("td", "settings-mono", o.model || "—"));
      rb.appendChild(tr);
    });
    roles.appendChild(rb);
    wrap.appendChild(roles);

    // Cloud and budget belong to the operator (ADR-123): shown, never written here.
    var cloud = el("p", "field-hint eng-cloud");
    if (pipe.localOnly) {
      cloud.textContent = uiT("eng_local_only", "Local-only mode is on: cloud engines are blocked.");
    } else if (!pipe.allowCloud || !(pipe.budgetUsd > 0)) {
      cloud.textContent = uiT("eng_cloud_off", "Cloud is off. To use a cloud engine add to .llm-localize.toml: [privacy] allow_cloud = true and [budget] monthly_usd = <your cap>.");
    } else {
      cloud.textContent = uiT("eng_cloud_on", "Cloud is on") + ": $" + pipe.budgetUsd + "/" + uiT("eng_month", "month") +
        " (" + pipe.budgetMode + ").";
    }
    wrap.appendChild(cloud);

    var list = el("div", "eng-list");
    list.appendChild(el("p", "field-hint", uiT("eng_loading", "Loading engines…")));
    wrap.appendChild(list);
    var out = el("pre", "eng-out settings-mono");
    out.hidden = true;
    wrap.appendChild(out);

    opPost("engine", { action: "list" }).then(function (res) {
      var info = (res && res.data) || {};
      list.replaceChildren();
      var table = el("table", "settings-table");
      table.innerHTML = "<thead><tr><th>" + uiT("set_col_name", "Name") + "</th><th>" + uiT("eng_col_evidence", "Evidence") +
        "</th><th>" + uiT("eng_col_fit", "This machine") + "</th><th></th></tr></thead>";
      var tb = document.createElement("tbody");
      (info.engines || []).forEach(function (e) {
        var tr = document.createElement("tr");
        var name = el("td", "");
        name.appendChild(el("div", "settings-strong", e.name + (e.recommended ? " · " + uiT("eng_recommended", "recommended") : "")));
        if (e.summary) name.appendChild(el("div", "field-hint", e.summary));
        tr.appendChild(name);
        var st = STATUS_LABELS[e.status] || [e.status, e.status];
        var ev = el("td", "");
        var badge = el("span", "settings-badge eng-status-" + e.status, uiT(st[0], st[1]));
        if (e.evidence) badge.title = e.evidence;
        ev.appendChild(badge);
        tr.appendChild(ev);
        var fit = el("td", "");
        fit.appendChild(el("span", "status-dot " + (e.fits ? "status-online" : "status-offline")));
        fit.appendChild(document.createTextNode(" " + (e.fits ? uiT("eng_ready", "ready") : e.why)));
        tr.appendChild(fit);
        var act = el("td", "settings-row-actions");
        if (e.current) {
          act.appendChild(el("span", "field-hint", uiT("eng_in_use", "in use")));
        } else {
          var btn = el("button", "btn", uiT("eng_apply", "Use this engine"));
          btn.type = "button";
          btn.addEventListener("click", function () { applyEngine(e, out); });
          act.appendChild(btn);
        }
        tr.appendChild(act);
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      list.appendChild(table);
    }).catch(function () {
      list.replaceChildren(el("p", "field-hint", uiT("eng_load_failed", "Could not load the engine list.")));
    });
    return wrap;
  }

  function applyEngine(e, out) {
    var msg = uiT("eng_confirm", "Switch every model to") + " " + e.name + "?";
    if (e.requires && e.requires.cloud) msg += "\n" + uiT("eng_confirm_cloud", "Text will be sent to a paid cloud API.");
    if (!window.confirm(msg)) return;
    var accept = false;
    if (e.status === "unbenchmarked") {
      accept = window.confirm(uiT("eng_confirm_unbenchmarked",
        "This engine has no benchmark evidence (ADR-12). Translation quality is unknown. Switch anyway?"));
      if (!accept) return;
    }
    setStatus(uiT("pc_saving", "Saving…"));
    opPost("engine", { action: "apply", engine_id: e.id, accept_unbenchmarked: accept }).then(function (res) {
      out.hidden = false;
      out.textContent = [res.summary || ""].concat(res.lines || []).join("\n");
      if (!res.ok) { setStatus(res.summary || res.error || uiT("set_save_failed", "Save failed.")); return; }
      setStatus(uiT("set_saved", "Saved."));
      load();
    });
  }

  function paintProviders(data) {
    var wrap = card(
      uiT("set_providers_title", "LLM providers"),
      uiT("set_providers_hint", "Define endpoints available to the translation engine."),
      "settings:providers"
    );
    var add = el("button", "btn btn-primary", uiT("set_add_provider", "+ Add provider"));
    add.type = "button";
    add.addEventListener("click", function () { openProviderModal(null); });
    wrap.querySelector(".settings-card-head").appendChild(add);

    var table = el("table", "settings-table");
    table.innerHTML =
      "<thead><tr><th>" + uiT("set_col_name", "Name") + "</th><th>" + uiT("set_col_type", "Type") + "</th><th>" + uiT("set_col_endpoint", "Endpoint") + "</th>" +
      "<th>" + uiT("set_col_models", "Available models") + "</th><th>" + uiT("set_col_status", "Status") + "</th><th></th></tr></thead>";
    var tbody = document.createElement("tbody");
    (data.providersDetailed || []).forEach(function (p) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-provider-id", p.id);
      tr.appendChild(el("td", "settings-strong", p.name || p.id));
      var type = el("td", "");
      type.appendChild(el("span", "settings-badge", p.kind || "ollama"));
      tr.appendChild(type);
      tr.appendChild(el("td", "settings-mono", p.endpoint || p.url || "—"));
      var models = (p.models && p.models.length) ? p.models.join(", ") : "—";
      tr.appendChild(el("td", "prov-models", models));
      var st = el("td", "prov-status");
      paintStatusCell(st, p.status || "unknown", p.reason, p.envVar);
      tr.appendChild(st);
      var acts = el("td", "settings-row-actions");
      var edit = el("button", "btn", uiT("pc_edit", "Edit"));
      edit.type = "button";
      edit.addEventListener("click", function () { openProviderModal(p); });
      var del = el("button", "btn", "✕");
      del.type = "button";
      del.disabled = p.id === "default";
      del.title = p.id === "default" ? uiT("set_default_provider_locked", "Default provider cannot be removed") : uiT("pc_remove", "Remove");
      del.addEventListener("click", function () {
        if (p.id === "default") return;
        if (!window.confirm(uiT("set_remove_provider_prefix", "Remove provider") + " " + (p.name || p.id) + "?")) return;
        var next = (state.providersDetailed || []).filter(function (row) {
          return row.id !== p.id;
        });
        post({ providers: next.map(serializeProvider) });
      });
      acts.appendChild(edit);
      acts.appendChild(del);
      tr.appendChild(acts);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  var STATUS_REASONS = {
    cloud_off: ["set_status_cloud_off", "cloud is off ([privacy] allow_cloud)"],
    no_key: ["set_status_no_key", "API key not set"],
    unreachable: ["set_status_unreachable", "not reachable"],
    missing_path: ["set_status_missing_path", "model path not found"],
  };

  function paintStatusCell(cell, status, reason, envVar) {
    var text = " " + status;
    var why = STATUS_REASONS[reason || ""];
    if (why) text += " — " + uiT(why[0], why[1]) + (reason === "no_key" && envVar ? " (" + envVar + ")" : "");
    cell.replaceChildren(el("span", "status-dot status-" + status), document.createTextNode(text));
  }

  function serializeProvider(p) {
    return {
      id: p.id,
      name: p.name,
      kind: p.kind,
      url: p.url,
      modelPath: p.modelPath || "",
    };
  }

  function makeModelSel(providers, provSel, currentModel) {
    var modelSel = document.createElement("select");
    modelSel.className = "settings-mono";
    function repaint() {
      var pid = provSel.value;
      var prov = providers.filter(function (p) { return p.id === pid; })[0];
      var models = (prov && prov.models && prov.models.length) ? prov.models : [];
      modelSel.replaceChildren();
      if (!currentModel || models.indexOf(currentModel) < 0) {
        var blank = document.createElement("option");
        blank.value = currentModel || "";
        blank.textContent = currentModel || uiT("set_select_model", "(select model)");
        modelSel.appendChild(blank);
      }
      models.forEach(function (m) {
        var opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (m === currentModel) opt.selected = true;
        modelSel.appendChild(opt);
      });
      if (currentModel && models.indexOf(currentModel) >= 0) modelSel.value = currentModel;
    }
    repaint();
    provSel.addEventListener("change", function () { currentModel = modelSel.value; repaint(); });
    return modelSel;
  }

  function paintAssignments(data) {
    var wrap = card(
      uiT("set_assignments_title", "Locale → provider & model"),
      uiT("set_assignments_hint", "Assign a provider and model to each locale. Model changes need ADR-12 confirm."),
      "settings:llm"
    );
    var table = el("table", "settings-table");
    table.innerHTML =
      "<thead><tr><th>" + uiT("set_col_locale", "Locale") + "</th><th>" + uiT("set_col_provider", "Provider") + "</th><th>" + uiT("set_col_model", "Model") + "</th><th>" + uiT("set_col_role", "Role") + "</th></tr></thead>";
    var tbody = document.createElement("tbody");
    var providers = data.providersDetailed || [];

    // synthetic "default" row at the top
    var syntheticDefault = data.localeAssignments && data.localeAssignments.filter(function (r) { return r.locale === "default"; })[0];
    if (!syntheticDefault) {
      syntheticDefault = { locale: "default", providerId: (providers[0] && providers[0].id) || "", model: "", role: "both" };
    }
    var allRows = [syntheticDefault].concat((data.localeAssignments || []).filter(function (r) { return r.locale !== "default"; }));

    allRows.forEach(function (row) {
      var tr = document.createElement("tr");
      if (row.locale === "default") tr.className = "settings-default-row";
      else if ((data.frozen || []).indexOf(row.locale) >= 0) tr.className = "is-muted";
      var locLabel = row.locale === "default" ? uiT("set_default_fallback", "default (fallback)") : localeLabel(row.locale);
      var locCell = el("td", "settings-mono settings-accent", locLabel);
      if (row.locale !== "default" && (data.frozen || []).indexOf(row.locale) >= 0) {
        locCell.appendChild(document.createTextNode(" "));
        locCell.appendChild(el("span", "settings-muted", uiT("set_frozen_badge", "frozen")));
      }
      tr.appendChild(locCell);
      var provTd = el("td", "");
      var provSel = document.createElement("select");
      providers.forEach(function (p) {
        var opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name || p.id;
        if (p.id === row.providerId) opt.selected = true;
        provSel.appendChild(opt);
      });
      provTd.appendChild(provSel);
      tr.appendChild(provTd);
      var modelTd = el("td", "");
      var modelSel = makeModelSel(providers, provSel, row.model || "");
      modelTd.appendChild(modelSel);
      tr.appendChild(modelTd);
      var roleTd = el("td", "");
      var roleSel = document.createElement("select");
      ["translator", "judge", "both"].forEach(function (r) {
        var opt = document.createElement("option");
        opt.value = r;
        opt.textContent = r.charAt(0).toUpperCase() + r.slice(1);
        if (r === (row.role || "translator")) opt.selected = true;
        roleSel.appendChild(opt);
      });
      roleTd.appendChild(roleSel);
      tr.appendChild(roleTd);
      row._prov = provSel;
      row._model = modelSel;
      row._role = roleSel;
      tbody.appendChild(tr);
    });
    // keep allRows accessible for collectAssignments
    data._allAssignmentRows = allRows;
    // What the table shows right now: saves compare against this, so a select that merely displays a default (the
    // synthetic "default" row, a provider's first model) is not mistaken for a model change (ADR-12 confirm).
    data._assignBaseline = {};
    allRows.forEach(function (row) {
      data._assignBaseline[row.locale] = {
        model: row._model ? row._model.value : (row.model || ""),
        role: row._role ? row._role.value : (row.role || ""),
      };
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    wrap.appendChild(el(
      "p",
      "field-hint",
      uiT("set_role_hint", "Role: Translator = translation only; Judge = quality scoring only; Both = translator and judge.")
    ));
    return wrap;
  }

  function paintQuality(data) {
    var wrap = card(uiT("set_quality_title", "Quality scoring"), "", "settings:quality");
    var left = el("div", "");
    left.appendChild(el("label", "field-label", uiT("set_threshold_label", "Score threshold (flag below)")));
    var thr = document.createElement("input");
    thr.type = "number";
    thr.min = "0";
    thr.max = "1";
    thr.step = "0.05";
    thr.value = String((data.quality && data.quality.threshold) != null
      ? data.quality.threshold : 0.55);
    thr.id = "settings-threshold";
    left.appendChild(thr);
    left.appendChild(el("div", "field-hint", uiT("set_threshold_hint", "Strings scoring below this are flagged as low score.")));
    wrap.appendChild(left);
    return wrap;
  }

  function collectAssignments() {
    var rows = (state._allAssignmentRows || state.localeAssignments || []);
    return rows.map(function (row) {
      return {
        locale: row.locale,
        providerId: row._prov ? row._prov.value : row.providerId,
        model: row._model ? row._model.value : row.model,
        role: row._role ? row._role.value : row.role,
      };
    });
  }

  function paintLlm(data) {
    var panel = el("div", "settings-panel is-active");
    panel.setAttribute("data-panel", "llm");
    var col = el("div", "settings-col settings-col-wide");
    col.appendChild(paintEngine(data));
    col.appendChild(paintProviders(data));
    col.appendChild(paintAssignments(data));
    col.appendChild(paintQuality(data));
    var acts = actionsRow();
    var reset = el("button", "btn", uiT("set_reset_threshold", "Reset threshold"));
    reset.type = "button";
    reset.addEventListener("click", function () {
      post({ quality: { threshold: 0.55 } });
    });
    var save = el("button", "btn btn-primary", uiT("set_save_changes", "Save changes"));
    save.type = "button";
    save.addEventListener("click", function () {
      var body = {
        providers: (state.providersDetailed || []).map(serializeProvider),
        locale_assignments: collectAssignments(),
        quality: {
          threshold: Number(document.getElementById("settings-threshold").value),
        },
      };
      // Match rows by locale: the table prepends a synthetic "default" row, so indexes are shifted by one and the
      // ADR-12 confirm used to fire on almost every save.
      var prevByLocale = data._assignBaseline || {};
      var modelChanged = body.locale_assignments.some(function (row) {
        var prev = prevByLocale[row.locale];
        if (!prev) return !!row.model;
        return (row.model || "") !== (prev.model || "") || (row.role || "") !== (prev.role || "");
      });
      if (modelChanged && !confirmModelWrite()) return;
      if (modelChanged) body.allow_model_writes = true;
      post(body);
    });
    acts.appendChild(reset);
    acts.appendChild(save);
    col.appendChild(acts);
    panel.appendChild(col);
    return panel;
  }

  function priorityFor(loc, data) {
    if ((data.frozen || []).indexOf(loc) >= 0) return "frozen";
    if ((data.asap || []).indexOf(loc) >= 0) return "asap";
    return "normal";
  }

  function paintLocales(data) {
    var panel = el("div", "settings-panel");
    panel.setAttribute("data-panel", "locales");
    var col = el("div", "settings-col");
    var wrap = card(
      uiT("set_locales_title", "Target locales"),
      uiT("set_locales_hint", "ASAP locales are translated first. Frozen locales are excluded from automatic runs but stay editable in the editor."),
      "settings:locales"
    );
    var add = el("button", "btn btn-primary", uiT("dash_add_locale", "+ Add locale"));
    add.type = "button";
    add.addEventListener("click", openAddLocale);
    wrap.querySelector(".settings-card-head").appendChild(add);

    var table = el("table", "settings-table");
    table.innerHTML =
      "<thead><tr><th>" + uiT("set_col_locale", "Locale") + "</th><th>" + uiT("set_col_priority", "Priority") + "</th><th>" + uiT("set_col_coverage", "Coverage") + "</th>" +
      "<th>" + uiT("set_col_model_override", "Model override") + "</th><th>" + uiT("set_col_fallback", "Fallback") + "</th><th></th></tr></thead>";
    var tbody = document.createElement("tbody");
    var assignmentByLoc = {};
    (data.localeAssignments || []).forEach(function (row) {
      assignmentByLoc[row.locale] = row;
    });
    (data.targets || []).forEach(function (loc) {
      var tr = document.createElement("tr");
      var prio = priorityFor(loc, data);
      if (prio === "frozen") tr.className = "is-muted";
      tr.appendChild(el("td", "settings-mono settings-accent", localeLabel(loc)));
      var prioTd = el("td", "");
      var seg = el("div", "seg");
      ["asap", "normal", "frozen"].forEach(function (val) {
        var lab = el("label", "seg-opt");
        var radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "prio-" + loc;
        radio.value = val;
        if (val === prio) radio.checked = true;
        lab.appendChild(radio);
        lab.appendChild(el("span", "", val === "asap" ? "ASAP" : val.charAt(0).toUpperCase() + val.slice(1)));
        seg.appendChild(lab);
      });
      prioTd.appendChild(seg);
      tr.appendChild(prioTd);
      var cov = Number((data.coverage && data.coverage[loc]) || 0);
      var covTd = el("td", "");
      var barWrap = el("div", "cov-bar-wrap");
      var bar = el("div", "cov-bar");
      bar.style.width = Math.max(0, Math.min(100, cov)) + "%";
      barWrap.appendChild(bar);
      covTd.appendChild(barWrap);
      covTd.appendChild(el("span", "settings-mono", Math.round(cov) + "%"));
      tr.appendChild(covTd);
      var model = (assignmentByLoc[loc] && assignmentByLoc[loc].model) || "default";
      tr.appendChild(el("td", "settings-mono", model));
      var fbTd = el("td", "");
      var fb = document.createElement("select");
      var none = document.createElement("option");
      none.value = "";
      none.textContent = "—";
      fb.appendChild(none);
      (data.targets || []).forEach(function (other) {
        if (other === loc) return;
        fb.appendChild(el("option", "", other));
      });
      if (data.sourceLocale) fb.appendChild(el("option", "", data.sourceLocale));
      fb.value = (data.fallbacks && data.fallbacks[loc]) || "";
      fbTd.appendChild(fb);
      tr.appendChild(fbTd);
      var rm = el("button", "btn", "✕");
      rm.type = "button";
      rm.addEventListener("click", function () {
        if (!window.confirm(uiT("set_remove_locale_confirm", "Remove locale {loc} from targets? Catalogue files are kept.").replace("{loc}", loc))) return;
        var rmBody = { project: project(), locale: loc };
        var postRm = (window.LLMApi && LLMApi.apiPost)
          ? LLMApi.apiPost("/api/remove-locale", rmBody)
          : fetch("/api/remove-locale", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(rmBody),
            }).then(function (r) { return r.json(); });
        postRm.then(function (result) {
          if (!result.ok) {
            setStatus(result.error || uiT("set_remove_failed", "Remove failed."));
            return;
          }
          setStatus(uiT("set_removed_locale", "Removed {loc}.").replace("{loc}", loc));
          load();
        });
      });
      var act = el("td", "");
      act.appendChild(rm);
      tr.appendChild(act);
      tr._prio = seg;
      tr._fallback = fb;
      tr._locale = loc;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    var legend = el("div", "settings-legend");
    [
      ["asap", uiT("set_leg_asap", "ASAP — translated first")],
      ["normal", uiT("set_leg_normal", "Normal — standard runs")],
      ["frozen", uiT("set_leg_frozen", "Frozen — excluded from auto runs")],
    ].forEach(function (item) {
      var span = el("span", "");
      span.appendChild(el("i", "leg " + item[0]));
      span.appendChild(document.createTextNode(item[1]));
      legend.appendChild(span);
    });
    wrap.appendChild(legend);
    col.appendChild(wrap);
    var acts = actionsRow();
    var save = el("button", "btn btn-primary", uiT("set_save_locales", "Save locale settings"));
    save.type = "button";
    save.addEventListener("click", function () {
      var asap = [];
      var frozen = [];
      var fallbacks = {};
      Array.prototype.forEach.call(tbody.querySelectorAll("tr"), function (tr) {
        var loc = tr._locale;
        var checked = tr.querySelector("input[type=radio]:checked");
        var val = checked ? checked.value : "normal";
        if (val === "asap") asap.push(loc);
        if (val === "frozen") frozen.push(loc);
        if (tr._fallback && tr._fallback.value) fallbacks[loc] = tr._fallback.value;
      });
      post({ asap: asap, frozen: frozen, fallbacks: fallbacks });
    });
    acts.appendChild(save);
    col.appendChild(acts);
    panel.appendChild(col);
    return panel;
  }

  function openAddLocale() {
    var code = window.prompt(uiT("set_add_locale_prompt", "Locale code to add (e.g. de, pt-BR):"));
    if (!code) return;
    code = code.trim();
    var addBody = { project: project(), locale: code };
    var postAdd = (window.LLMApi && LLMApi.apiPost)
      ? LLMApi.apiPost("/api/add-locale", addBody)
      : fetch("/api/add-locale", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(addBody),
        }).then(function (r) { return r.json(); });
    postAdd.then(function (result) {
      if (!result.ok) {
        setStatus(result.error || uiT("set_add_locale_failed", "Add locale failed."));
        return;
      }
      setStatus(uiT("set_added_locale", "Added {code}.").replace("{code}", code));
      load();
    });
  }

  function paintProject(data) {
    var panel = el("div", "settings-panel");
    panel.setAttribute("data-panel", "project");
    var col = el("div", "settings-col settings-col-narrow");
    var idCard = card(uiT("set_project_identity", "Project identity"), "", "settings:project");
    idCard.appendChild(el("label", "field-label", uiT("pc_project_name", "Project name")));
    var nameIn = document.createElement("input");
    nameIn.type = "text";
    nameIn.className = "settings-mono";
    nameIn.value = (data.project && data.project.name) || data.name || "";
    idCard.appendChild(nameIn);
    idCard.appendChild(el("label", "field-label", uiT("pc_source", "Source locale")));
    var srcIn = document.createElement("input");
    srcIn.type = "text";
    srcIn.value = (data.project && data.project.sourceLocale) || data.sourceLocale || "en";
    idCard.appendChild(srcIn);
    idCard.appendChild(el(
      "div",
      "field-hint",
      uiT("set_source_hint", "The language your app is authored in. Must not appear in target locales.")
    ));
    col.appendChild(idCard);

    var catCard = card(uiT("set_catalogue", "Catalogue"));
    catCard.appendChild(el("label", "field-label", uiT("set_format", "Format")));
    var fmt = document.createElement("select");
    // Options come from the adapter registry (catalog._ADAPTERS); a configured alias such as
    // "gettext" stays selectable so saving the page does not change it.
    var current = (data.project && data.project.catalogFormat) || "";
    var formats = (data.catalogFormats || ["json-nested", "json-flat", "yaml", "po", "arb", "android-xml"]).slice();
    if (current && formats.indexOf(current) < 0) formats.unshift(current);
    formats.forEach(function (f) {
      var opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      if (f === current) opt.selected = true;
      fmt.appendChild(opt);
    });
    catCard.appendChild(fmt);
    catCard.appendChild(el("label", "field-label", uiT("set_path_template", "Path template")));
    var pathIn = document.createElement("input");
    pathIn.type = "text";
    pathIn.className = "settings-mono";
    pathIn.value = (data.project && data.project.catalogPath) || "";
    catCard.appendChild(pathIn);
    catCard.appendChild(el("label", "field-label", uiT("set_skip_keys", "Skip keys (comma-separated)")));
    var skipIn = document.createElement("input");
    skipIn.type = "text";
    skipIn.value = ((data.project && data.project.skipKeys) || []).join(", ");
    catCard.appendChild(skipIn);
    col.appendChild(catCard);

    var acts = actionsRow();
    var save = el("button", "btn btn-primary", uiT("set_save_project", "Save project settings"));
    save.type = "button";
    save.addEventListener("click", function () {
      post({
        project: {
          name: nameIn.value,
          sourceLocale: srcIn.value,
          catalogFormat: fmt.value,
          catalogPath: pathIn.value,
          skipKeys: skipIn.value,
        },
      });
    });
    acts.appendChild(save);
    col.appendChild(acts);
    col.appendChild(paintPlaces());
    panel.appendChild(col);
    return panel;
  }

  function placesOp(body) {
    body.project = project();
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost("/api/ops/places", body);
    var headers = { "Content-Type": "application/json" };
    if (window.__LLM_TOKEN) headers["X-LLM-Token"] = window.__LLM_TOKEN;
    return fetch("/api/ops/places", {
      method: "POST", headers: headers, body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function paintPlaces() {
    var wrap = card(
      uiT("set_places_title", "Places"),
      uiT("set_places_hint", "Per-namespace policy (ADR-104): auto / request / review / never."),
      "settings:places"
    );
    var meta = el("p", "settings-muted", "");
    wrap.appendChild(meta);
    var table = el("table", "settings-table");
    table.innerHTML =
      "<thead><tr><th>Place</th><th>Policy</th><th>Keys</th><th>Source</th><th></th></tr></thead>";
    var tbody = document.createElement("tbody");
    table.appendChild(tbody);
    wrap.appendChild(table);
    var addRow = el("div", "settings-row");
    var placeIn = document.createElement("input");
    placeIn.type = "text";
    placeIn.placeholder = uiT("set_ns_placeholder", "namespace or pattern");
    placeIn.className = "settings-input";
    var polIn = document.createElement("select");
    var POLICIES = ["auto", "request", "review", "never"];
    POLICIES.forEach(function (p) {
      var o = el("option", "", p);
      o.value = p;
      polIn.appendChild(o);
    });
    polIn.value = "request";
    var addBtn = el("button", "btn", uiT("set_add_set", "Add / set"));
    addBtn.type = "button";
    addBtn.addEventListener("click", function () {
      var place = (placeIn.value || "").trim();
      if (!place) return;
      placesOp({ action: "set", place: place, policy: polIn.value }).then(function (r) {
        setStatus(r.summary || "");
        placeIn.value = "";
        reload();
      });
    });
    addRow.appendChild(placeIn);
    addRow.appendChild(polIn);
    addRow.appendChild(addBtn);
    wrap.appendChild(addRow);
    var disc = el("details", "settings-details");
    disc.appendChild(el("summary", "", uiT("set_discover_title", "Discover unclaimed places")));
    var discBody = el("pre", "settings-mono settings-pre", "");
    disc.appendChild(discBody);
    var discBtn = el("button", "btn", uiT("set_run_discover", "Run discover"));
    discBtn.type = "button";
    discBtn.addEventListener("click", function () {
      var body = { project: project() };
      var run = window.LLMApi && LLMApi.apiPost
        ? LLMApi.apiPost("/api/ops/discover", body)
        : fetch("/api/ops/discover", {
            method: "POST",
            headers: Object.assign({ "Content-Type": "application/json" },
              window.__LLM_TOKEN ? { "X-LLM-Token": window.__LLM_TOKEN } : {}),
            body: JSON.stringify(body),
          }).then(function (r) { return r.json(); });
      run.then(function (res) {
        discBody.textContent = (res.data && res.data.places_snippet)
          || (res.lines || []).join("\n")
          || res.summary
          || "(none)";
        disc.open = true;
      });
    });
    disc.appendChild(discBtn);
    wrap.appendChild(disc);
    function reload() {
      return placesOp({ action: "list" }).then(function (res) {
        tbody.replaceChildren();
        var rows = (res.data && res.data.places) || [];
        var patterns = (res.data && res.data.patterns) || {};
        var def = (res.data && res.data.default) || "auto";
        meta.textContent = uiT("set_default_policy", "Default policy:") + " " + def + " " +
          uiT("set_default_policy_tail", "(namespaces without an explicit row inherit it).");
        rows.forEach(function (row) {
          var tr = document.createElement("tr");
          tr.appendChild(el("td", "settings-mono", row.place));
          var td = document.createElement("td");
          var sel = document.createElement("select");
          POLICIES.forEach(function (p) {
            var o = el("option", "", p);
            o.value = p;
            sel.appendChild(o);
          });
          sel.value = row.policy;
          sel.addEventListener("change", function () {
            placesOp({ action: "set", place: row.place, policy: sel.value }).then(function (r) {
              setStatus(r.summary || "");
              reload();
            });
          });
          td.appendChild(sel);
          tr.appendChild(td);
          tr.appendChild(el("td", "", String(row.keys)));
          var explicit = row.explicit || Object.prototype.hasOwnProperty.call(patterns, row.place);
          tr.appendChild(el("td", "", explicit ? "explicit" : "inherited"));
          if (row.policy === "never") tr.classList.add("settings-row-muted");
          var end = document.createElement("td");
          if (explicit) {
            var rm = el("button", "btn", uiT("pc_remove", "Remove"));
            rm.type = "button";
            rm.addEventListener("click", function () {
              placesOp({ action: "unset", place: row.place }).then(function (r) {
                setStatus(r.summary || "");
                reload();
              });
            });
            end.appendChild(rm);
          }
          tr.appendChild(end);
          tbody.appendChild(tr);
        });
      });
    }
    reload();
    return wrap;
  }

  function paintWeb(data) {
    var panel = el("div", "settings-panel");
    panel.setAttribute("data-panel", "web");
    var col = el("div", "settings-col settings-col-web");
    var wrap = card(uiT("set_web_title", "Web server"), "", "settings:web");
    var row = el("div", "settings-grid-bind");
    var bindBox = el("div", "");
    bindBox.appendChild(el("label", "field-label", uiT("set_bind", "Bind address")));
    var bind = document.createElement("input");
    bind.type = "text";
    bind.value = "127.0.0.1";
    bind.disabled = true;
    bind.className = "settings-mono";
    bindBox.appendChild(bind);
    bindBox.appendChild(el(
      "div",
      "field-hint",
      uiT("set_bind_hint", "Locked to 127.0.0.1 (ADR-33). The review server stays on loopback."),
    ));
    row.appendChild(bindBox);
    var portBox = el("div", "");
    portBox.appendChild(el("label", "field-label", uiT("set_port", "Port")));
    var port = document.createElement("input");
    port.type = "text";
    port.value = String((data.web && data.web.port) || data.port || "");
    port.disabled = true;
    port.className = "settings-mono";
    portBox.appendChild(port);
    row.appendChild(portBox);
    wrap.appendChild(row);

    wrap.appendChild(el("label", "field-label", uiT("set_session_token", "Session token")));
    var tokRow = el("div", "settings-token-row");
    var tok = document.createElement("input");
    tok.type = "text";
    tok.readOnly = true;
    tok.className = "settings-mono";
    tok.id = "token-once";
    tok.placeholder = uiT("set_regen_ph", "Regenerate to reveal once");
    tokRow.appendChild(tok);
    var regen = el("button", "btn", uiT("set_regen", "Regenerate"));
    regen.type = "button";
    regen.addEventListener("click", regenerate);
    tokRow.appendChild(regen);
    wrap.appendChild(tokRow);
    wrap.appendChild(el(
      "div",
      "field-hint",
      uiT("set_token_hint", "Required as X-LLM-Token header for all POST requests."),
    ));

    var overlayLab = el("label", "field-label settings-check");
    var check = document.createElement("input");
    check.type = "checkbox";
    check.checked = !!(data.web ? data.web.overlayEdit : data.overlayEdit);
    check.id = "settings-overlay";
    overlayLab.appendChild(check);
    overlayLab.appendChild(document.createTextNode(" " + uiT("set_overlay_edit", "Allow cross-origin overlay edits")));
    wrap.appendChild(overlayLab);
    wrap.appendChild(el(
      "div",
      "field-hint",
      uiT("set_overlay_hint", "Enable overlay_edit so the translator overlay can save edits back to this server."),
    ));
    col.appendChild(wrap);
    var acts = actionsRow();
    var save = el("button", "btn btn-primary", uiT("set_save_web", "Save web settings"));
    save.type = "button";
    save.addEventListener("click", function () {
      post({ overlay_edit: !!check.checked });
    });
    acts.appendChild(save);
    col.appendChild(acts);
    panel.appendChild(col);
    return panel;
  }

  function regenerate() {
    var tokBody = { project: project() };
    var postTok = (window.LLMApi && LLMApi.apiPost)
      ? LLMApi.apiPost("/api/web-token", tokBody)
      : fetch("/api/web-token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(tokBody),
        }).then(function (r) { return r.json(); });
    postTok.then(function (result) {
      if (!result.token) {
        setStatus(result.error || uiT("set_token_missing", "Token was not returned."));
        return;
      }
      window.__LLM_TOKEN = result.token;
      var node = document.getElementById("token-once");
      if (node) node.value = result.token;
      setStatus(uiT("set_token_regenerated", "Token regenerated — copy it now."));
    });
  }

  function paintPermissions(data) {
    var panel = el("div", "settings-panel");
    panel.setAttribute("data-panel", "permissions");
    var col = el("div", "settings-col settings-col-wide");
    var wrap = card(
      uiT("set_perms_title", "Operation permissions per role"),
      uiT("set_perms_hint", "Admin always has full access. Translator translate stays locked off."),
      "settings:permissions"
    );
    var perms = data.permissions || {};
    var ops = perms.operations || (data.permissionMeta && data.permissionMeta.operations) || [];
    var roles = perms.roles || ["Admin", "Supervisor", "Translator", "Developer"];
    var cats = (data.permissionMeta && data.permissionMeta.categories) || {};
    var matrix = perms.matrix || {};

    var table = el("table", "settings-table perm-table");
    table.id = "perm-table";
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    hr.appendChild(el("th", "", uiT("set_col_operation", "Operation")));
    hr.appendChild(el("th", "", uiT("set_col_category", "Category")));
    roles.forEach(function (role) {
      hr.appendChild(el("th", "perm-role", role));
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    var lastCat = null;
    ops.forEach(function (op) {
      var cat = cats[op] || "Other";
      if (cat !== lastCat) {
        var cr = document.createElement("tr");
        cr.className = "perm-cat";
        var cell = document.createElement("td");
        cell.colSpan = 2 + roles.length;
        cell.textContent = cat;
        cr.appendChild(cell);
        tbody.appendChild(cr);
        lastCat = cat;
      }
      var tr = document.createElement("tr");
      tr.appendChild(el("td", "settings-mono settings-accent", op));
      tr.appendChild(el("td", "", cat));
      var flags = matrix[op] || [true, false, false, false];
      roles.forEach(function (_role, idx) {
        var td = el("td", "perm-check");
        var box = document.createElement("input");
        box.type = "checkbox";
        box.checked = !!flags[idx];
        box.setAttribute("data-op", op);
        box.setAttribute("data-role", String(idx));
        var locked = idx === 0 || (op === "translate" && idx === 2);
        if (locked) {
          box.disabled = true;
          if (idx === 0) box.checked = true;
          if (op === "translate" && idx === 2) box.checked = false;
        }
        td.appendChild(box);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    wrap.appendChild(el(
      "p",
      "field-hint",
      uiT(
        "set_perms_locked_note",
        "Admin checkboxes are locked on. Translator access is further limited to assigned languages.",
      )
    ));
    col.appendChild(wrap);
    var acts = actionsRow();
    var reset = el("button", "btn", uiT("set_reset_defaults", "Reset to defaults"));
    reset.type = "button";
    reset.addEventListener("click", function () {
      post({ reset_permissions: true });
    });
    var save = el("button", "btn btn-primary", uiT("set_save_perms", "Save permissions"));
    save.type = "button";
    save.addEventListener("click", function () {
      var next = {};
      table.querySelectorAll("input[data-op]").forEach(function (box) {
        var op = box.getAttribute("data-op");
        var idx = Number(box.getAttribute("data-role"));
        if (!next[op]) next[op] = [false, false, false, false];
        next[op][idx] = !!box.checked;
      });
      post({ permission_matrix: next });
    });
    acts.appendChild(reset);
    acts.appendChild(save);
    col.appendChild(acts);
    panel.appendChild(col);
    return panel;
  }

  function openProviderModal(existing) {
    var overlay = el("div", "modal");
    overlay.setAttribute("role", "dialog");
    var form = el("div", "modal-body blueprint-card");
    form.appendChild(el(
      "h2",
      "",
      existing
        ? uiT("set_edit_provider", "Edit provider")
        : uiT("set_add_provider", "Add provider"),
    ));
    function field(label, input) {
      var wrap = el("label", "field");
      wrap.appendChild(document.createTextNode(label));
      wrap.appendChild(input);
      form.appendChild(wrap);
      return input;
    }
    var idIn = document.createElement("input");
    idIn.value = existing ? existing.id : "";
    idIn.disabled = !!existing;
    field(uiT("set_field_id", "Id"), idIn);
    var nameIn = document.createElement("input");
    nameIn.value = existing ? (existing.name || "") : "";
    field(uiT("set_col_name", "Name"), nameIn);
    var kindSel = document.createElement("select");
    ["ollama", "openai", "anthropic", "deepseek", "deepl", "ctranslate2"].forEach(function (k) {
      var opt = document.createElement("option");
      opt.value = k;
      opt.textContent = k;
      if (existing && existing.kind === k) opt.selected = true;
      kindSel.appendChild(opt);
    });
    field(uiT("set_col_type", "Type"), kindSel);
    var urlIn = document.createElement("input");
    urlIn.className = "settings-mono";
    urlIn.value = existing ? (existing.url || "") : "http://127.0.0.1:11434";
    field(uiT("set_field_url", "URL"), urlIn);
    var mpIn = document.createElement("input");
    mpIn.value = existing ? (existing.modelPath || "") : "";
    field(uiT("set_ct2_path", "Model path (CTranslate2)"), mpIn);
    form.appendChild(el(
      "p",
      "field-hint",
      uiT("set_api_keys_hint", "API keys stay in the environment (OPENAI_API_KEY, ANTHROPIC_API_KEY, …)."),
    ));
    var acts = el("div", "ops-actions");
    var cancel = el("button", "btn", uiT("wf_cancel", "Cancel"));
    cancel.type = "button";
    cancel.addEventListener("click", function () { overlay.remove(); });
    var save = el("button", "btn btn-primary", uiT("wf_save", "Save"));
    save.type = "button";
    save.addEventListener("click", function () {
      var id = (idIn.value || "").trim();
      if (!id) {
        setStatus(uiT("set_provider_id_required", "Provider id is required."));
        return;
      }
      var row = {
        id: id,
        name: (nameIn.value || id).trim(),
        kind: kindSel.value,
        url: urlIn.value.trim(),
        modelPath: mpIn.value.trim(),
        models: existing ? (existing.models || []) : [],
        status: existing ? existing.status : "unknown",
        endpoint: urlIn.value.trim(),
      };
      var list = (state.providersDetailed || []).slice();
      var found = false;
      list = list.map(function (p) {
        if (p.id === id) {
          found = true;
          return row;
        }
        return p;
      });
      if (!found) list.push(row);
      state.providersDetailed = list;
      overlay.remove();
      post({ providers: list.map(serializeProvider) });
    });
    acts.appendChild(cancel);
    acts.appendChild(save);
    form.appendChild(acts);
    overlay.appendChild(form);
    overlay.addEventListener("click", function (ev) {
      if (ev.target === overlay) overlay.remove();
    });
    document.body.appendChild(overlay);
  }

  function paint(data) {
    state = data;
    root.replaceChildren();
    statusEl = el("p", "settings-status", "");
    root.appendChild(statusEl);
    root.appendChild(paintLlm(data));
    root.appendChild(paintLocales(data));
    root.appendChild(paintProject(data));
    root.appendChild(paintWeb(data));
    root.appendChild(paintPermissions(data));
    var hash = (location.hash || "").replace(/^#/, "");
    if (hash === "perms") hash = "permissions";
    switchTab(hash || "llm");
    refreshStatus();
  }

  function refreshStatus() {
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/provider-status", project() ? { project: project() } : {})
      : fetch("/api/provider-status" + (project() ? ("?project=" + encodeURIComponent(project())) : ""))
          .then(function (r) { return r.json(); });
    get.then(function (payload) {
      if (!payload || !payload.statuses || !state) return;
      (state.providersDetailed || []).forEach(function (p) {
        var st = payload.statuses[p.id];
        if (!st) return;
        p.status = st.status || "unknown";
        p.reason = st.reason || "";
        p.envVar = st.envVar || "";
        if (st.models && st.models.length) p.models = st.models;
      });
      var llm = root.querySelector('[data-panel="llm"]');
      if (!llm) return;
      // Merge into the existing rows: replacing the panel would drop an open
      // modal's focus, a half-typed field and the scroll position.
      (state.providersDetailed || []).forEach(function (p) {
        var row = llm.querySelector('tr[data-provider-id="' + p.id + '"]');
        if (!row) return;
        var st = row.querySelector(".prov-status");
        if (st) paintStatusCell(st, p.status || "unknown", p.reason, p.envVar);
        var md = row.querySelector(".prov-models");
        if (md) md.textContent = (p.models && p.models.length) ? p.models.join(", ") : "—";
      });
      var note = llm.querySelector(".prov-health-note");
      if (!note) {
        note = document.createElement("p");
        note.className = "field-hint prov-health-note";
        llm.appendChild(note);
      }
      var parts = [];
      if (payload.residency && payload.residency.policy) {
        parts.push("residency=" + payload.residency.policy);
      }
      if (payload.breaker) {
        parts.push("icu_skips_abort=" + payload.breaker.icu_skips_abort);
        parts.push("max_rejects=" + payload.breaker.translate_max_consecutive_rejects);
      }
      note.textContent = parts.length ? ("Health: " + parts.join(" · ")) : "";
    }).catch(function () {});
  }

  function load() {
    var query = project() ? ("?project=" + encodeURIComponent(project())) : "";
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/settings", project() ? { project: project() } : {})
      : fetch("/api/settings" + query).then(function (r) { return r.json(); });
    return get.then(function (data) { paint(data); markClean(); });
  }

  bindTabs();

  if (root) {
    root.addEventListener("input", markDirty);
    root.addEventListener("change", markDirty);
  }
  window.addEventListener("beforeunload", function (ev) {
    if (!dirty) return;
    ev.preventDefault();
    ev.returnValue = "";
  });

  var projSel = document.getElementById("project-select");
  if (projSel) {
    projSel.addEventListener("change", function () {
      if (state === null) return;
      if (!confirmLeaveIfDirty()) {
        // Revert select to previous project when possible.
        try {
          if (state && state.project) projSel.value = state.project;
        } catch (err) { /* ignore */ }
        return;
      }
      load();
    });
  }

  var headers = (window.LLMApi && LLMApi.authHeaders) ? LLMApi.authHeaders() : {};
  if (window.__LLM_TOKEN && !headers["X-LLM-Token"]) headers["X-LLM-Token"] = window.__LLM_TOKEN;
  fetch("/api/auth/me", { headers: headers, credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (me) {
      if (!me || !me.authenticated || me.role !== "Admin") {
        root.replaceChildren(el("p", "empty-state", uiT("set_admin_required", "Admin required.")));
        return;
      }
      load();
    })
    .catch(function () {
      root.replaceChildren(el("p", "empty-state", uiT("set_admin_required", "Admin required.")));
    });
})();
