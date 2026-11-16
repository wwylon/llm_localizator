(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "project-config" || !root) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  var DOMAINS = [
    ["Gaming / entertainment", "pc_domain_gaming"],
    ["SaaS / developer tools", "pc_domain_saas"],
    ["E-commerce", "pc_domain_ecom"],
    ["Finance / fintech", "pc_domain_finance"],
    ["Healthcare", "pc_domain_health"],
    ["Legal / compliance", "pc_domain_legal"],
    ["Education", "pc_domain_edu"],
  ];

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
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

  function boot() {
    var TABS = [
      { id: "prompt", label: t("pc_tab_prompt", "Prompt templates") },
      { id: "bridge", label: t("pc_tab_bridge", "Bridge language") },
      { id: "glossary", label: t("pc_tab_glossary", "Glossary sharing") },
      { id: "identity", label: t("pc_tab_identity", "Project identity") },
      { id: "scan", label: t("pc_tab_scan", "Hardcoded scan") },
    ];
    var state = { tab: "prompt", data: null, form: null, base: "", error: "", saving: false };
    var loadToken = 0;

    var tabs = el("div", "tabs");
    var body = el("div", "pc-body tab-panel");
    var status = el("p", "pc-status");
    status.setAttribute("role", "status");
    root.replaceChildren(tabs, body, status);

    var actions = document.getElementById("pc-head-actions");
    var saveBtn = el("button", "btn btn-primary", t("pc_save_all", "Save all"));
    saveBtn.type = "button";
    saveBtn.addEventListener("click", save);
    if (actions) {
      actions.replaceChildren(saveBtn);
      if (window.LLMHelp) {
        var helpBtn = window.LLMHelp.helpBtn("project-config:general");
        var helpClone = helpBtn.cloneNode(true);
        helpClone.addEventListener("click", function (ev) {
          ev.stopPropagation();
          window.LLMHelp.showHelp("project-config:" + state.tab);
        });
        helpClone.setAttribute("aria-label", uiT("pc_help_tab", "Help for this tab"));
        helpClone.title = uiT("pc_help_tab", "Help for this tab");
        actions.insertBefore(helpClone, saveBtn);
        var generalHelp = window.LLMHelp.helpBtn("project-config:general");
        generalHelp.title = uiT("pc_about_page", "About this page");
        actions.insertBefore(generalHelp, helpClone);
      }
    }

    TABS.forEach(function (item) {
      var btn = el("button", "tab-btn", item.label);
      btn.type = "button";
      btn.dataset.tab = item.id;
      btn.addEventListener("click", function () {
        state.tab = item.id;
        paint();
      });
      tabs.appendChild(btn);
    });

    function names(code) {
      var map = (state.data && state.data.localeNames) || {};
      return map[code] ? code + " — " + map[code] : code;
    }

    // ----- form model ---------------------------------------------------
    function toForm(d) {
      var notes = Object.keys(d.localeNotes || {}).sort().map(function (loc) {
        return { loc: loc, text: d.localeNotes[loc] };
      });
      var models = Object.keys(d.models || {}).map(function (name) {
        return { name: name, text: d.models[name].text, localize: !!d.models[name].localize };
      });
      var mode = (d.bridge && d.bridge.mode) || "none";
      return {
        family: d.family, localeFamilies: Object.assign({}, d.localeFamilies || {}),
        glossary: d.glossary || "",
        domainsText: Object.keys(d.glossaryDomains || {}).sort().map(function (ns) {
          return ns + " = " + (d.glossaryDomains[ns] || []).join(", ");
        }).join("\n"),
        shared: (d.glossaryRows || []).filter(function (r) { return r.kind === "shared"; })
          .map(function (r) { return { name: r.name, path: r.path, terms: r.terms }; }),
        tmShared: d.tmShared || "", tmWrite: d.tmWrite || "", conflict: d.glossaryConflict || "own",
        displayName: d.displayName || "", description: d.description || "",
        audience: d.audience || "", tone: d.tone || "", severity: d.severity || {}, exclude: d.exclude || { keys: [], sourceRegex: [] }, domain: d.domain || "", localize: d.localize || "source",
        notes: notes, models: models, sourceLocale: d.sourceLocale,
        bridge: {
          mode: mode, locale: (d.bridge && d.bridge.locale) || "",
          model: (d.bridge && d.bridge.model) || "", store: !d.bridge || d.bridge.store !== false,
        },
        pivots: Object.keys(d.pivots || {}).map(function (loc) {
          return { loc: loc, ref: d.pivots[loc] };
        }),
        scan: (function (sc) {
          sc = sc || {};
          var lines = function (xs) { return (xs || []).join("\n"); };
          return {
            adapter: sc.adapter || "", srcDirs: lines(sc.srcDirs), exclude: lines(sc.exclude),
            unskip: lines(sc.unskip), tFunctions: lines(sc.tFunctions), contentGlobs: lines(sc.contentGlobs),
            unusedAllow: lines(sc.unusedAllow), directiveAliases: sc.directiveAliases !== false,
          };
        })(d.scan),
      };
    }

    function payload() {
      var f = state.form;
      var domains = {};
      f.domainsText.split("\n").forEach(function (line) {
        var parts = line.trim().split("=");
        if (parts.length < 2) return;
        var ns = parts[0].trim();
        var vals = parts.slice(1).join("=").split(",").map(function (s) { return s.trim(); })
          .filter(Boolean);
        if (ns) domains[ns] = vals;
      });
      var notes = {};
      f.notes.forEach(function (n) { if (n.loc && n.text.trim()) notes[n.loc] = n.text; });
      var models = {};
      f.models.forEach(function (m) {
        if (m.name.trim()) models[m.name.trim()] = { text: m.text, localize: m.localize };
      });
      var pivots = {};
      f.pivots.forEach(function (p) { if (p.loc && p.ref) pivots[p.loc] = p.ref; });
      var bridge = { mode: f.bridge.mode };
      if (f.bridge.mode !== "none") {
        bridge.locale = f.bridge.mode === "en" ? "en" : f.bridge.locale;
        bridge.model = f.bridge.model;
        bridge.store = f.bridge.store;
      }
      return {
        family: f.family, locale_families: f.localeFamilies, glossary: f.glossary,
        glossary_domains: domains,
        glossary_shared: f.shared.map(function (r) { return r.path; }),
        tm_shared: f.tmShared, tm_write: f.tmWrite, glossary_conflict: f.conflict,
        display_name: f.displayName, description: f.description, audience: f.audience, tone: f.tone,
        domain: f.domain, localize: f.localize, locale_notes: notes, models: models,
        bridge: bridge, pivots: pivots, source_locale: f.sourceLocale,
        scan: (function (sc) {
          var list = function (text) {
            return String(text || "").split("\n").map(function (x) { return x.trim(); }).filter(Boolean);
          };
          return {
            adapter: sc.adapter.trim(), srcDirs: list(sc.srcDirs), exclude: list(sc.exclude),
            unskip: list(sc.unskip), tFunctions: list(sc.tFunctions), contentGlobs: list(sc.contentGlobs),
            unusedAllow: list(sc.unusedAllow), directiveAliases: !!sc.directiveAliases,
          };
        })(f.scan),
      };
    }

    function isDirty() {
      return !!state.form && JSON.stringify(payload()) !== state.base;
    }

    function touch() {
      state.error = "";
      refreshChrome();
    }

    function refreshChrome() {
      var dirty = isDirty();
      saveBtn.disabled = !dirty || state.saving;
      status.className = "pc-status" + (state.error ? " is-error" : "");
      status.textContent = state.error ||
        (state.saving ? t("pc_saving", "Saving…") :
          dirty ? t("pc_unsaved", "Unsaved changes") : "");
      Array.prototype.forEach.call(tabs.querySelectorAll(".tab-btn"), function (btn) {
        btn.className = "tab-btn" + (btn.dataset.tab === state.tab ? " is-active" : "");
      });
    }

    // ----- building blocks ---------------------------------------------
    function card(title, hint) {
      var c = el("section", "pc-card");
      if (title) c.appendChild(el("h2", "pc-card-title", title));
      if (hint) c.appendChild(el("p", "pc-hint", hint));
      body.appendChild(c);
      return c;
    }

    function textarea(value, rows, max, onInput) {
      var ta = el("textarea", "pc-textarea");
      ta.rows = rows;
      ta.maxLength = max;
      ta.value = value;
      ta.addEventListener("input", function () { onInput(ta.value); touch(); });
      return ta;
    }

    function input(value, onInput, placeholder, list) {
      var inp = el("input", "pc-input");
      inp.type = "text";
      inp.value = value;
      if (placeholder) inp.placeholder = placeholder;
      if (list) inp.setAttribute("list", list);
      inp.addEventListener("input", function () { onInput(inp.value); touch(); });
      return inp;
    }

    function select(options, value, onChange) {
      var sel = el("select", "pc-select");
      options.forEach(function (o) {
        var opt = el("option", "", o.label);
        opt.value = o.value;
        if (o.value === value) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", function () { onChange(sel.value); touch(); });
      return sel;
    }

    function button(label, cls, onClick) {
      var b = el("button", cls, label);
      b.type = "button";
      b.addEventListener("click", onClick);
      return b;
    }

    function radioGroup(name, options, value, onChange) {
      var group = el("div", "pc-radios");
      group.setAttribute("role", "radiogroup");
      options.forEach(function (o) {
        var label = el("label", "pc-radio" + (o.value === value ? " is-active" : ""));
        var r = el("input", "");
        r.type = "radio";
        r.name = name;
        r.value = o.value;
        r.checked = o.value === value;
        r.addEventListener("change", function () {
          onChange(o.value);
          touch();
          paint();
        });
        var text = el("span", "pc-radio-text");
        text.appendChild(el("strong", "", o.label));
        if (o.desc) text.appendChild(el("span", "pc-hint", o.desc));
        label.appendChild(r);
        label.appendChild(text);
        group.appendChild(label);
      });
      return group;
    }

    function field(label, control, hint) {
      var wrap = el("div", "pc-field");
      wrap.appendChild(el("label", "pc-label", label));
      wrap.appendChild(control);
      if (hint) wrap.appendChild(el("p", "pc-hint", hint));
      return wrap;
    }

    function localeOptions(codes, blank) {
      var out = blank ? [{ value: "", label: blank }] : [];
      codes.forEach(function (c) { out.push({ value: c, label: names(c) }); });
      return out;
    }

    // ----- tabs ---------------------------------------------------------
    function paintPrompt() {
      var d = state.data;
      var f = state.form;

      var c = card(
        t("pc_desc_title", "Project description prompt"),
        t("pc_desc_hint", "This text is prepended to every translation prompt. Describe what the project does, its tone of voice, target audience, and domain."),
      );
      c.appendChild(textarea(f.description, 6, 2000, function (v) { f.description = v; }));
      c.appendChild(el("p", "pc-hint", t("pc_desc_note", "Used as the base context for all translation prompts in this project.")));

      c = card(
        t("pc_notes_title", "Per-language prompt additions"),
        t("pc_notes_hint", "Additional instructions appended to the base prompt for a specific target language (formality, script, cultural notes)."),
      );
      f.notes.forEach(function (n, i) {
        var row = el("div", "pc-row");
        var head = el("div", "pc-row-head");
        var free = d.targets.filter(function (loc) {
          return loc === n.loc || !f.notes.some(function (o) { return o.loc === loc; });
        });
        head.appendChild(select(localeOptions(free), n.loc, function (v) { n.loc = v; }));
        head.appendChild(button(t("pc_remove", "Remove"), "btn pc-remove", function () {
          f.notes.splice(i, 1);
          touch();
          paint();
        }));
        row.appendChild(head);
        row.appendChild(textarea(n.text, 3, 500, function (v) { n.text = v; }));
        c.appendChild(row);
      });
      var addNote = button(t("pc_add_lang", "+ Add language override"), "pc-add", function () {
        var used = f.notes.map(function (n) { return n.loc; });
        var next = d.targets.filter(function (loc) { return used.indexOf(loc) < 0; })[0];
        if (!next) return;
        f.notes.push({ loc: next, text: "" });
        touch();
        paint();
      });
      addNote.disabled = f.notes.length >= d.targets.length;
      c.appendChild(addNote);

      c = card(
        t("pc_models_title", "Per-model prompt variants"),
        t("pc_models_hint", "Different LLMs respond differently to instruction phrasing. Add guidance for a specific model — useful when a smaller model needs more explicit instructions."),
      );
      var list = el("datalist", "");
      list.id = "pc-model-list";
      (d.modelRoster || []).forEach(function (m) {
        var o = el("option", "");
        o.value = m;
        list.appendChild(o);
      });
      c.appendChild(list);
      f.models.forEach(function (m, i) {
        var row = el("div", "pc-row");
        var head = el("div", "pc-row-head");
        head.appendChild(input(m.name, function (v) { m.name = v; }, t("pc_model_ph", "model tag, e.g. llama3.2:latest"), "pc-model-list"));
        var lbl = el("label", "pc-check");
        var cb = el("input", "");
        cb.type = "checkbox";
        cb.checked = m.localize;
        cb.addEventListener("change", function () { m.localize = cb.checked; touch(); });
        lbl.appendChild(cb);
        lbl.appendChild(el("span", "", t("pc_model_localize", "Auto-localize prompt (translate prompt to target language)")));
        head.appendChild(lbl);
        head.appendChild(button(t("pc_remove", "Remove"), "btn pc-remove", function () {
          f.models.splice(i, 1);
          touch();
          paint();
        }));
        row.appendChild(head);
        row.appendChild(textarea(m.text, 3, 1000, function (v) { m.text = v; }));
        c.appendChild(row);
      });
      c.appendChild(button(t("pc_add_model", "+ Add model variant"), "pc-add", function () {
        f.models.push({ name: "", text: "", localize: false });
        touch();
        paint();
      }));

      c = card(
        t("pc_loc_title", "Automatic prompt localization"),
        t("pc_loc_hint", "When enabled, the project instruction text is translated into the target language before it is sent to the model. Some models perform better when prompted in the language they are translating into."),
      );
      c.appendChild(radioGroup("pc-localize", [
        { value: "source", label: t("pc_loc_source", "Keep prompt in source language"), desc: t("pc_loc_source_d", "default, works best for most models") },
        { value: "target", label: t("pc_loc_target", "Auto-translate prompt to target language"), desc: t("pc_loc_target_d", "may improve smaller models; the run's own model translates it once per language and the result is cached") },
        { value: "per-model", label: t("pc_loc_permodel", "Per-model setting"), desc: t("pc_loc_permodel_d", "configured on each model variant above") },
      ], f.localize, function (v) { f.localize = v; }));

      c = card(
        t("pc_adv_title", "Advanced"),
        t("pc_adv_hint", "Prompt family, per-locale family, project glossary path and glossary domains."),
      );
      c.appendChild(field(t("pc_family", "Prompt family"), select(
        d.families.map(function (n) { return { value: n, label: n }; }),
        f.family, function (v) { f.family = v; },
      )));
      var famBox = el("div", "pc-pairs");
      d.targets.forEach(function (loc) {
        var row = el("div", "pc-pair");
        row.appendChild(el("span", "pc-pair-key", loc));
        var opts = [{ value: "", label: t("pc_default", "(default)") }].concat(
          d.families.map(function (n) { return { value: n, label: n }; }));
        row.appendChild(select(opts, f.localeFamilies[loc] || "", function (v) {
          if (v) f.localeFamilies[loc] = v; else delete f.localeFamilies[loc];
        }));
        famBox.appendChild(row);
      });
      c.appendChild(field(t("pc_locale_family", "Per-locale family"), famBox));
      c.appendChild(field(t("pc_glossary_path", "Glossary path"), input(
        f.glossary, function (v) { f.glossary = v; }, t("pc_path_ph", "path relative to project root"))));
      c.appendChild(field(t("pc_domains", "Glossary domains"), textarea(
        f.domainsText, 4, 4000, function (v) { f.domainsText = v; }),
        t("pc_domains_hint", "One namespace per line: namespace = domain[, domain…]")));
    }

    function paintBridge() {
      var d = state.data;
      var f = state.form;
      var b = f.bridge;

      var c = card(
        t("pc_bridge_title", "Bridge language"),
        t("pc_bridge_hint", "Translate into an intermediate locale first, then from that locale into each target. This two-step approach can improve quality for language pairs where direct translation data is scarce in smaller models."),
      );
      c.appendChild(radioGroup("pc-bridge", [
        { value: "none", label: t("pc_bridge_none", "No bridge — direct translation"), desc: t("pc_bridge_none_d", "Source → target in one pass. Default for English-source projects.") },
        { value: "en", label: t("pc_bridge_en", "Translate via English"), desc: t("pc_bridge_en_d", "Source → English → target. Recommended when the source is not English.") },
        { value: "custom", label: t("pc_bridge_custom", "Custom bridge locale"), desc: t("pc_bridge_custom_d", "Choose any intermediate locale, e.g. pt-PT → pt-BR.") },
      ], b.mode, function (v) {
        b.mode = v;
        if (v === "custom" && !b.locale) b.locale = d.targets[0] || "";
      }));

      var src = [d.sourceLocale].concat(d.targets.filter(function (x) { return x !== d.sourceLocale; }));
      var all = src.slice();
      if (all.indexOf("en") < 0) all.push("en");
      c.appendChild(field(t("pc_source", "Source locale"), select(
        localeOptions(all.filter(function (x) { return d.targets.indexOf(x) < 0 || x === f.sourceLocale; })),
        f.sourceLocale, function (v) { f.sourceLocale = v; }),
        t("pc_source_hint", "The language strings are written in. Must not appear in targets.")));

      if (b.mode !== "none") {
        if (b.mode === "custom") {
          c.appendChild(field(t("pc_bridge_locale", "Bridge locale (intermediate)"), select(
            localeOptions(d.targets.concat(d.targets.indexOf(d.sourceLocale) < 0 ? [d.sourceLocale] : [])),
            b.locale, function (v) { b.locale = v; }),
            t("pc_bridge_locale_hint", "Translations are first generated in this locale, then forwarded.")));
        }
        var modelList = el("datalist", "");
        modelList.id = "pc-bridge-models";
        (d.modelRoster || []).forEach(function (m) {
          var o = el("option", "");
          o.value = m;
          modelList.appendChild(o);
        });
        c.appendChild(modelList);
        c.appendChild(field(t("pc_bridge_model", "Bridge model"), input(
          b.model, function (v) { b.model = v; },
          t("pc_bridge_model_ph", "(same as locale model)"), "pc-bridge-models"),
          t("pc_bridge_model_hint", "Model used for the source → bridge pass. A fast model is usually sufficient.")));
        c.appendChild(field(t("pc_bridge_store", "Store bridge translations"), select([
          { value: "yes", label: t("pc_store_yes", "Yes — save the bridge locale as a target locale too") },
          { value: "no", label: t("pc_store_no", "No — intermediate only (source locale only)") },
        ], b.store ? "yes" : "no", function (v) { b.store = v === "yes"; }),
          t("pc_bridge_store_hint", "A bridge locale that is a target is always stored.")));
      }

      c = card(
        t("pc_pivot_title", "Pivot locales"),
        t("pc_pivot_hint", "Some locale variants are better translated from a related locale than from the source — for example pt-BR from pt-PT. A pivot overrides the bridge for that locale."),
      );
      f.pivots.forEach(function (p, i) {
        var row = el("div", "pc-pair");
        row.appendChild(select(localeOptions(d.targets, t("pc_choose", "— choose —")), p.loc, function (v) { p.loc = v; }));
        row.appendChild(el("span", "pc-pair-key", "←"));
        row.appendChild(select(localeOptions(d.targets.concat([d.sourceLocale]), t("pc_choose", "— choose —")), p.ref, function (v) { p.ref = v; }));
        var rm = button("✕", "btn pc-remove", function () {
          f.pivots.splice(i, 1);
          touch();
          paint();
        });
        rm.setAttribute("aria-label", t("pc_remove", "Remove"));
        row.appendChild(rm);
        c.appendChild(row);
      });
      c.appendChild(button(t("pc_add_pivot", "+ Add pivot"), "pc-add", function () {
        f.pivots.push({ loc: "", ref: "" });
        touch();
        paint();
      }));
    }

    function badge(kind) {
      return el("span", "pc-badge is-" + kind, kind === "own" ? t("pc_own", "own") : t("pc_shared", "shared"));
    }

    function paintGlossary() {
      var d = state.data;
      var f = state.form;
      var c = card(
        t("pc_shared_title", "Shared glossaries"),
        t("pc_shared_hint", "A shared glossary is defined once and used by multiple projects — brand terms, product names and technical vocabulary that must stay consistent."),
      );
      c.appendChild(el("p", "pc-label", t("pc_uses", "This project currently uses:")));
      var own = (d.glossaryRows || []).filter(function (r) { return r.kind === "own"; })[0];
      if (own) {
        var row = el("div", "pc-glossrow");
        row.appendChild(badge("own"));
        row.appendChild(el("strong", "", own.name));
        row.appendChild(el("span", "pc-hint", t("pc_own_row", "— project-local glossary · {n} terms", { n: own.terms })));
        var edit = el("a", "pc-link", t("pc_edit", "Edit →"));
        edit.href = "/app/glossary";
        row.appendChild(edit);
        c.appendChild(row);
      }
      f.shared.forEach(function (r, i) {
        var row2 = el("div", "pc-glossrow");
        row2.appendChild(badge("shared"));
        row2.appendChild(el("strong", "", r.name));
        row2.appendChild(el("span", "pc-hint", "— " + r.path + " · " + t("pc_terms", "{n} terms", { n: r.terms })));
        row2.appendChild(button(t("pc_detach", "Detach"), "btn pc-remove", function () {
          f.shared.splice(i, 1);
          touch();
          paint();
        }));
        c.appendChild(row2);
      });

      var attachable = (d.attachable || []).filter(function (a) {
        return !f.shared.some(function (r) { return r.path === a.path; });
      });
      c.appendChild(el("p", "pc-label", t("pc_attach", "Attach a shared glossary from another project:")));
      var line = el("div", "pc-pair");
      var sel = select([{ value: "", label: t("pc_select_project", "— select a project —") }].concat(
        attachable.map(function (a) {
          return { value: a.path, label: a.name + " (" + t("pc_terms", "{n} terms", { n: a.terms }) + ")" };
        })), "", function () {});
      line.appendChild(sel);
      var attachBtn = button(t("pc_attach_btn", "Attach"), "btn", function () {
        var hit = attachable.filter(function (a) { return a.path === sel.value; })[0];
        if (!hit) return;
        f.shared.push({ name: hit.name, path: hit.path, terms: hit.terms });
        touch();
        paint();
      });
      line.appendChild(attachBtn);
      c.appendChild(line);
      c.appendChild(field(t("pc_tm_shared", "Shared translation memory"), input(
        f.tmShared, function (v) { f.tmShared = v; }, t("pc_path_ph", "path relative to project root")),
        t("pc_tm_hint", "Read-only, like shared glossaries. The project translation memory wins on the same key.")));
      c.appendChild(field(t("pc_tm_write", "Also write approved text to"), input(
        f.tmWrite, function (v) { f.tmWrite = v; }, t("pc_path_ph", "path relative to project root")),
        t("pc_tm_write_hint", "Optional. Separate several shared memories with commas; earlier ones win. Approved human text is also appended to this memory.")));
      c.appendChild(el("p", "pc-hint", t("pc_priority", "Priority order: when a term exists in both, the project definition wins unless you choose otherwise below. Shared glossaries are read-only from this project.")));

      c = card(t("pc_conflict_title", "Glossary merge conflicts"));
      c.appendChild(radioGroup("pc-conflict", [
        { value: "own", label: t("pc_conf_own", "Project glossary wins"), desc: t("pc_conf_own_d", "own definition overrides shared on conflict") },
        { value: "shared", label: t("pc_conf_shared", "Shared glossary wins"), desc: t("pc_conf_shared_d", "useful when the shared glossary is authoritative (e.g. brand terms)") },
        { value: "flag", label: t("pc_conf_flag", "Flag for review"), desc: t("pc_conf_flag_d", "project definition is used and every conflicting term is listed below for an admin to resolve") },
      ], f.conflict, function (v) { f.conflict = v; }));
      if (f.conflict === "flag") {
        var list = d.conflicts || [];
        c.appendChild(el("p", "pc-label", list.length
          ? t("pc_conflicts", "Conflicting terms ({n}):", { n: list.length })
          : t("pc_no_conflicts", "No conflicting terms.")));
        if (list.length) c.appendChild(el("p", "pc-hint", list.join(", ")));
      }
    }

    function paintIdentity() {
      var d = state.data;
      var f = state.form;
      var c = card(t("pc_id_title", "Project identity"));
      c.appendChild(field(t("pc_project_name", "Project name"), (function () {
        var inp = input(d.projectName || "", function () {});
        inp.readOnly = true;
        return inp;
      })()));
      c.appendChild(field(t("pc_display_name", "Display name"), input(f.displayName, function (v) { f.displayName = v; })));
      var domainValues = DOMAINS.map(function (row) { return row[0]; });
      var preset = domainValues.indexOf(f.domain) >= 0 ? f.domain : "__other";
      var opts = DOMAINS.map(function (row) {
        return { value: row[0], label: t(row[1], row[0]) };
      }).concat([{ value: "__other", label: t("pc_other", "Other") }]);
      var custom = input(preset === "__other" ? f.domain : "", function (v) { f.domain = v; }, t("pc_domain_ph", "Describe the domain"));
      custom.hidden = preset !== "__other";
      c.appendChild(field(t("pc_domain", "Domain / industry"), (function () {
        var wrap = el("div", "pc-stack");
        wrap.appendChild(select(opts, preset, function (v) {
          if (v === "__other") { f.domain = custom.value; custom.hidden = false; custom.focus(); }
          else { f.domain = v; custom.hidden = true; }
        }));
        wrap.appendChild(custom);
        return wrap;
      })(), t("pc_domain_hint", "Used to select domain-appropriate vocabulary and tone guidance in prompts.")));
      c.appendChild(field(t("pc_audience", "Target audience"), textarea(
        f.audience, 3, 300, function (v) { f.audience = v; }),
        t("pc_audience_hint", "Injected into the base prompt as context for tone and vocabulary choices.")));
      c.appendChild(field(t("pc_tone", "Tone of voice"), textarea(
        f.tone, 2, 300, function (v) { f.tone = v; }),
        t("pc_tone_hint", "Added to the prompt as a Tone line, for example friendly and direct.")));
      var ex = f.exclude || { keys: [], sourceRegex: [] };
      var exBox = el("div", "pc-stack");
      var exLines = ex.keys.map(function (k) { return t("pc_exclude_key", "key glob") + ": " + k; })
        .concat(ex.sourceRegex.map(function (r) { return t("pc_exclude_regex", "source regex") + ": " + r; }));
      Object.keys(f.severity || {}).forEach(function (code) {
        exLines.push(t("pc_severity", "severity") + " " + code + ": " + f.severity[code]);
      });
      exBox.appendChild(el("pre", "pc-readonly", exLines.length ? exLines.join("\n") : t("pc_exclude_none", "No exclusion rules.")));
      c.appendChild(field(t("pc_exclude", "Never translate (read-only)"), exBox,
        t("pc_exclude_hint", "Set in the [exclude] table of .llm-localize.toml. Matching strings are skipped by translate, improve, validate and export.")));
    }

    function paintScan() {
      var sc = state.form.scan;
      var c = card(t("pc_scan_title", "Hardcoded-string scan"),
        t("pc_scan_intro", "What agent-hardcoded and scan read. One entry per line. Saved to the [scan] table of .llm-localize.toml; run the scan again after saving."));
      c.appendChild(field(t("pc_scan_adapter", "Adapter"), input(sc.adapter, function (v) { sc.adapter = v; }, "source"),
        t("pc_scan_adapter_hint", "Leave empty for the default (source: every language the scanner knows).")));
      [
        ["srcDirs", t("pc_scan_src", "Source folders"), t("pc_scan_src_hint", "Folders to scan, relative to the project root.")],
        ["exclude", t("pc_scan_exclude", "Exclude"), t("pc_scan_exclude_hint", "Path segments or globs to skip, for example content/** in a theme.")],
        ["unskip", t("pc_scan_unskip", "Scan anyway"), t("pc_scan_unskip_hint", "Bring back a folder skipped by default (docs, scripts, migrations).")],
        ["tFunctions", t("pc_scan_tfn", "Translate functions"), t("pc_scan_tfn_hint", "Your own translate wrappers (myT, ui.say): their arguments count as routed.")],
        ["contentGlobs", t("pc_scan_content", "Content files"), t("pc_scan_content_hint", "Opt-in YAML, Markdown or TOML files whose text people read, for example api/openapi.yaml.")],
        ["unusedAllow", t("pc_scan_unused", "Keys never reported unused"), t("pc_scan_unused_hint", "Key globs built at run time (validate --unused).")],
      ].forEach(function (row) {
        c.appendChild(field(row[1], textarea(sc[row[0]], 3, 4000, function (v) { sc[row[0]] = v; }), row[2]));
      });
      var box = el("input");
      box.type = "checkbox";
      box.checked = !!sc.directiveAliases;
      box.addEventListener("change", function () { sc.directiveAliases = box.checked; touch(); });
      c.appendChild(field(t("pc_scan_aliases", "Accept other tools' ignore comments"), box,
        t("pc_scan_aliases_hint", "eslint-disable i18next/no-literal-string and similar comments also silence a hit.")));
    }

    function paint() {
      body.replaceChildren();
      if (!state.data) { refreshChrome(); return; }
      var title = document.getElementById("pc-title");
      if (title) {
        title.textContent = t("pc_title", "Project config — {name}", {
          name: state.form.displayName || state.data.projectName || project(),
        });
      }
      ({ prompt: paintPrompt, bridge: paintBridge, glossary: paintGlossary, identity: paintIdentity, scan: paintScan })[state.tab]();
      refreshChrome();
    }

    // ----- server -------------------------------------------------------
    function save() {
      if (!state.form || state.saving) return;
      var now = payload();
      var was = JSON.parse(state.base);
      var data = {};
      Object.keys(now).forEach(function (key) {
        if (JSON.stringify(now[key]) !== JSON.stringify(was[key])) data[key] = now[key];
      });
      data.project = project();
      state.saving = true;
      state.error = "";
      refreshChrome();
      fetch("/api/project-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }).then(function (r) { return r.json(); }).then(function (result) {
        state.saving = false;
        if (!result.ok) {
          state.error = result.error || t("pc_save_failed", "Save failed.");
          refreshChrome();
          return;
        }
        load();
      }).catch(function () {
        state.saving = false;
        state.error = t("pc_save_failed", "Save failed.");
        refreshChrome();
      });
    }

    function load() {
      var token = ++loadToken;
      var query = project() ? ("?project=" + encodeURIComponent(project())) : "";
      fetch("/api/project-config" + query).then(function (r) { return r.json(); }).then(function (data) {
        if (token !== loadToken) return;
        if (!data.ok) {
          body.replaceChildren(el("p", "empty-state", data.error || t("pc_load_failed", "Could not load project config.")));
          return;
        }
        state.data = data;
        state.form = toForm(data);
        state.base = JSON.stringify(payload());
        state.error = "";
        paint();
      }).catch(function () {
        if (token !== loadToken) return;
        body.replaceChildren(el("p", "empty-state", t("pc_load_failed", "Could not load project config.")));
      });
    }

    var projectSelect = document.getElementById("project-select");
    if (projectSelect) projectSelect.addEventListener("change", load);
    saveBtn.disabled = true;
    load();
  }

  var headers = {};
  if (window.__LLM_TOKEN) headers["X-LLM-Token"] = window.__LLM_TOKEN;
  fetch("/api/auth/me", { headers: headers, credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (me) {
      if (!me || !me.authenticated || me.role !== "Admin") {
        root.replaceChildren(el("p", "empty-state", uiT("set_admin_required", "Admin required.")));
        return;
      }
      boot();
    })
    .catch(function () {
      root.replaceChildren(el("p", "empty-state", uiT("set_admin_required", "Admin required.")));
    });
})();
