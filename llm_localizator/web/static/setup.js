(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "setup" || !root) return;

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

  function headers() {
    var out = { "Content-Type": "application/json" };
    if (window.__LLM_TOKEN) out["X-LLM-Token"] = window.__LLM_TOKEN;
    return out;
  }

  function getJson(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); });
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: headers(),
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); });
  }

  function stepTitles() {
    return [
      uiT("setup_step_engine", "Engine"),
      uiT("setup_step_project", "Your project"),
      uiT("setup_step_languages", "Languages"),
      uiT("setup_step_model", "Model"),
      uiT("setup_step_product", "About your product"),
      uiT("setup_step_approach", "How to translate"),
      uiT("setup_step_finish", "Finish"),
    ];
  }
  var state = {
    sourceLocale: "en",
    targets: [],
    model: "",
    domain: "",
    providerKind: "ollama",
    catalogFormat: "",
    catalogFormats: ["json-nested", "json-flat", "yaml", "po", "arb", "android-xml"],
    catalogPath: "",
    engine: "",
    approach: "",
    approaches: [],
  };
  var known = [];
  var models = { list: [], error: "", loaded: false };
  var projectSummary = "";
  var testResult = null;
  var index = 0;

  var progress = el("ol", "wizard-steps");
  var body = el("div", "wizard-body");
  var status = el("p", "empty-state wizard-status", "");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  var actions = el("div", "ops-actions");
  var prev = el("button", "btn", uiT("setup_back", "Back"));
  var next = el("button", "btn btn-primary", uiT("setup_next", "Next"));
  prev.type = "button";
  next.type = "button";
  actions.appendChild(prev);
  actions.appendChild(next);
  root.appendChild(progress);
  root.appendChild(body);
  root.appendChild(status);
  root.appendChild(actions);

  function nameOf(code) {
    for (var i = 0; i < known.length; i += 1) {
      if (known[i].code === code) return known[i].name;
    }
    return code;
  }

  function labelOf(code) {
    var name = nameOf(code);
    return name === code ? code : name + " (" + code + ")";
  }

  function paintProgress() {
    progress.replaceChildren();
    stepTitles().forEach(function (title, i) {
      var item = el("li", "wizard-step" + (i === index ? " is-current" : i < index ? " is-done" : ""), title);
      if (i === index) item.setAttribute("aria-current", "step");
      progress.appendChild(item);
    });
  }

  function field(label, control, hint) {
    var wrap = el("label", "field", label);
    wrap.appendChild(control);
    if (hint) wrap.appendChild(el("span", "field-hint", hint));
    return wrap;
  }

  // ---- step 0: engine (W6) --------------------------------------------------
  // One switch for every model (ADR-156) through the engine op: recommend + list, apply on click (Admin). Cloud
  // engines never turn cloud on; the lines the user still has to add are shown as returned.

  var STATUS_LABELS = {
    benchmarked: ["eng_status_benchmarked", "benchmarked"],
    waiver: ["eng_status_waiver", "approved waiver"],
    smoke: ["eng_status_smoke", "smoke test only"],
    unbenchmarked: ["eng_status_unbenchmarked", "not benchmarked"],
  };
  var engineInfo = null;

  function paintEngine() {
    body.appendChild(el("h2", "wizard-title", uiT("setup_engine_title", "Choose an engine")));
    body.appendChild(el("p", "wizard-help", uiT(
      "setup_engine_help",
      "An engine sets the provider and model for every step: translation, scoring and improve. You can change it later in Settings.")));
    var host = el("div", "setup-engine");
    host.appendChild(el("p", "field-hint", uiT("eng_loading", "Loading engines…")));
    body.appendChild(host);
    var out = el("pre", "settings-mono setup-engine-out");
    out.hidden = true;
    body.appendChild(out);

    function render(info) {
      host.replaceChildren();
      if (info.recommended) {
        var rec = el("p", "wizard-help setup-engine-rec");
        rec.appendChild(el("strong", "", uiT("setup_engine_rec", "Recommended here") + ": " + info.recommended));
        rec.appendChild(document.createTextNode(" (" + (info.reason || "") + ")"));
        host.appendChild(rec);
      } else if (info.reason) {
        host.appendChild(el("p", "wizard-warning", info.reason));
      }
      var table = el("table", "settings-table setup-engine-table");
      var tb = document.createElement("tbody");
      (info.engines || []).forEach(function (engine) {
        var tr = document.createElement("tr");
        tr.dataset.engine = engine.id;
        var name = el("td", "");
        name.appendChild(el("div", "settings-strong", engine.name || engine.id));
        if (engine.summary) name.appendChild(el("div", "field-hint", engine.summary));
        tr.appendChild(name);
        var badges = el("td", "");
        var label = STATUS_LABELS[engine.status] || [engine.status, engine.status];
        badges.appendChild(el("span", "settings-badge", uiT(label[0], label[1])));
        badges.appendChild(el("span", "settings-badge", engine.cloud ? uiT("eng_cloud", "cloud") : uiT("eng_local", "local")));
        tr.appendChild(badges);
        var fit = el("td", "");
        fit.appendChild(el("span", "status-dot " + (engine.fits ? "status-online" : "status-offline")));
        fit.appendChild(el("span", "field-hint", " " + engine.why));
        tr.appendChild(fit);
        var act = el("td", "");
        if (engine.current || engine.id === state.engine) {
          act.appendChild(el("span", "settings-badge", uiT("eng_in_use", "in use")));
        } else {
          var accept = null;
          if (engine.status === "unbenchmarked") {
            // ADR-12: no evidence, so the switch needs an explicit tick.
            var lab = el("label", "field-hint setup-engine-accept");
            accept = el("input", "");
            accept.type = "checkbox";
            lab.appendChild(accept);
            lab.appendChild(document.createTextNode(" " + uiT("setup_engine_accept", "Use without benchmark")));
            act.appendChild(lab);
          }
          var use = el("button", "btn" + (engine.recommended ? " btn-primary" : ""), uiT("eng_use", "Use this engine"));
          use.type = "button";
          if (accept) {
            use.disabled = true;
            accept.addEventListener("change", function () { use.disabled = !accept.checked; });
          }
          use.addEventListener("click", function () {
            use.disabled = true;
            postJson("/api/ops/engine", {
              project: project(), action: "apply", engine_id: engine.id, accept_unbenchmarked: !!(accept && accept.checked),
            }).then(function (res) {
              out.hidden = false;
              out.textContent = [res.summary || res.error || ""].concat(res.lines || []).join("\n");
              if (res.ok) {
                state.engine = engine.id;
                state.model = "";
                engineInfo = null;
                load();
              } else {
                use.disabled = false;
              }
            }).catch(function () {
              out.hidden = false;
              out.textContent = uiT("setup_request_failed", "Request failed.");
              use.disabled = false;
            });
          });
          act.appendChild(use);
        }
        tr.appendChild(act);
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      host.appendChild(table);
    }

    function load() {
      postJson("/api/ops/engine", { project: project(), action: "list" }).then(function (res) {
        if (!res || res.ok === false || !res.data) {
          host.replaceChildren(el("p", "wizard-warning", uiT(
            "setup_engine_admin", "Only an admin can choose the engine. Continue to set up the rest.")));
          return;
        }
        engineInfo = res.data;
        if (engineInfo.current && !state.engine) state.engine = engineInfo.current;
        render(engineInfo);
      }).catch(function () {
        host.replaceChildren(el("p", "wizard-warning", uiT("setup_request_failed", "Request failed.")));
      });
    }
    if (engineInfo) render(engineInfo); else load();
  }

  // ---- step 1: project ------------------------------------------------------

  function paintProject() {
    body.appendChild(el("h2", "wizard-title", uiT("setup_step_project", "Your project")));
    body.appendChild(el(
      "p", "wizard-help",
      projectSummary || uiT("setup_checking_files", "Checking your message files…"),
    ));

    var sourceSelect = document.createElement("select");
    sourceSelect.id = "setup-source";
    var codes = known.map(function (k) { return k.code; });
    if (codes.indexOf(state.sourceLocale) < 0) codes.unshift(state.sourceLocale);
    codes.forEach(function (code) {
      var option = el("option", "", nameOf(code) + " (" + code + ")");
      option.value = code;
      if (code === state.sourceLocale) option.selected = true;
      sourceSelect.appendChild(option);
    });
    sourceSelect.addEventListener("change", function () {
      state.sourceLocale = sourceSelect.value;
      state.targets = state.targets.filter(function (t) { return t !== state.sourceLocale; });
    });
    body.appendChild(field(
      uiT("setup_source_label", "Language your strings are written in"), sourceSelect,
      uiT("setup_source_hint", "Changing this only tells the tool how to read your files."),
    ));

    var details = el("details", "wizard-advanced");
    details.appendChild(el("summary", "", uiT("setup_files_where", "Where are my message files?")));
    var format = document.createElement("select");
    format.id = "setup-format";
    var choices = [""].concat(state.catalogFormats);
    if (state.catalogFormat && choices.indexOf(state.catalogFormat) < 0) choices.push(state.catalogFormat);
    choices.forEach(function (f) {
      var option = el("option", "", f || uiT("setup_format_detect", "Detect from my files"));
      option.value = f;
      if (f === state.catalogFormat) option.selected = true;
      format.appendChild(option);
    });
    format.addEventListener("change", function () { state.catalogFormat = format.value; });
    var path = document.createElement("input");
    path.type = "text";
    path.id = "setup-path";
    path.value = state.catalogPath;
    path.addEventListener("input", function () { state.catalogPath = path.value.trim(); });
    details.appendChild(field(
      uiT("set_format", "Format"), format,
      uiT("setup_format_hint", "json-nested, json-flat, yaml, po, arb or android-xml"),
    ));
    details.appendChild(field(
      uiT("set_path_template", "Path template"), path,
      uiT("setup_path_hint", "For example messages/{locale}/{namespace}.json"),
    ));
    body.appendChild(details);
  }

  // ---- step 2: languages ----------------------------------------------------

  function toggleTarget(code, on) {
    var at = state.targets.indexOf(code);
    if (on && at < 0) state.targets.push(code);
    if (!on && at >= 0) state.targets.splice(at, 1);
  }

  function paintLanguages() {
    body.appendChild(el("h2", "wizard-title", uiT("setup_languages_title", "Languages to translate into")));
    body.appendChild(el(
      "p", "wizard-help",
      uiT("setup_languages_help", "Pick one or more. You can add more later from Settings."),
    ));

    var chosen = el("div", "wizard-chosen");
    chosen.id = "setup-chosen";
    function paintChosen() {
      chosen.replaceChildren();
      if (!state.targets.length) {
        chosen.appendChild(el("span", "empty-state", uiT("setup_nothing_selected", "Nothing selected yet.")));
        return;
      }
      state.targets.forEach(function (code) {
        chosen.appendChild(el("span", "wizard-chip", labelOf(code)));
      });
    }

    var search = document.createElement("input");
    search.type = "search";
    search.id = "setup-language-search";
    search.placeholder = uiT("setup_search_languages", "Search languages…");
    search.setAttribute("aria-label", uiT("setup_search_languages_aria", "Search languages"));

    var list = el("div", "locale-picker");
    list.setAttribute("role", "group");
    list.setAttribute("aria-label", uiT("setup_step_languages", "Languages"));
    function paintList() {
      var needle = search.value.trim().toLowerCase();
      list.replaceChildren();
      known.forEach(function (item) {
        if (item.code === state.sourceLocale) return;
        var hay = (item.name + " " + item.code).toLowerCase();
        if (needle && hay.indexOf(needle) < 0) return;
        var row = el("label", "locale-option");
        var box = document.createElement("input");
        box.type = "checkbox";
        box.value = item.code;
        box.checked = state.targets.indexOf(item.code) >= 0;
        box.setAttribute("aria-label", item.name + " (" + item.code + ")");
        box.addEventListener("change", function () {
          toggleTarget(item.code, box.checked);
          paintChosen();
        });
        row.appendChild(box);
        row.appendChild(el("span", "locale-option-name", item.name));
        row.appendChild(el("code", "locale-option-code", item.code));
        if (item.direction === "rtl") {
          row.appendChild(el("span", "locale-option-tag", uiT("setup_rtl", "right-to-left")));
        }
        list.appendChild(row);
      });
      if (!list.childNodes.length) {
        list.appendChild(el("p", "empty-state", uiT("setup_no_match", "No match. Add it by code below.")));
      }
    }
    search.addEventListener("input", paintList);

    var custom = document.createElement("input");
    custom.type = "text";
    custom.id = "setup-custom-code";
    custom.placeholder = uiT("setup_custom_code_ph", "e.g. sw or pt-AO");
    custom.setAttribute("aria-label", uiT("setup_custom_code_aria", "Add a language by code"));
    var addCustom = el("button", "btn", uiT("wf_add", "Add"));
    addCustom.type = "button";
    addCustom.addEventListener("click", function () {
      var code = custom.value.trim();
      if (!code) return;
      if (!/^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$/.test(code)) {
        status.textContent = uiT("setup_bad_code", "'{code}' does not look like a language code.").replace("{code}", code);
        return;
      }
      status.textContent = "";
      if (code === state.sourceLocale) {
        status.textContent = uiT("setup_is_source", "That is your source language.");
        return;
      }
      toggleTarget(code, true);
      custom.value = "";
      paintChosen();
      paintList();
    });

    body.appendChild(chosen);
    body.appendChild(search);
    body.appendChild(list);
    var customRow = el("div", "wizard-inline");
    customRow.appendChild(custom);
    customRow.appendChild(addCustom);
    body.appendChild(el("p", "wizard-help", uiT("setup_any_code", "Not listed? Any language code works:")));
    body.appendChild(customRow);
    paintChosen();
    paintList();
  }

  // ---- step 3: model --------------------------------------------------------

  function paintModel() {
    body.appendChild(el("h2", "wizard-title", uiT("setup_model_title", "Model that translates")));
    body.appendChild(el(
      "p", "wizard-help",
      state.providerKind === "ollama"
        ? uiT("setup_model_ollama_help", "The model runs on your machine through Ollama; your text does not leave it.")
        : uiT("setup_model_provider_help", "Provider: {kind}. Type the model name your provider expects.").replace("{kind}", state.providerKind),
    ));

    if (state.engine) {
      // The engine already sets every model; a model typed here would override it for all locales.
      body.appendChild(el("p", "wizard-help setup-engine-note", uiT(
        "setup_model_engine_note", "Engine {id} sets the models. Leave this empty to keep them.").replace("{id}", state.engine)));
    }
    var control;
    if (state.providerKind === "ollama" && models.list.length) {
      control = document.createElement("select");
      var names = models.list.slice();
      if (state.model && names.indexOf(state.model) < 0) names.unshift(state.model);
      names.forEach(function (name) {
        var option = el("option", "", name);
        option.value = name;
        if (name === state.model) option.selected = true;
        control.appendChild(option);
      });
      if (state.engine) {
        var keep = el("option", "", uiT("setup_model_keep_engine", "(set by the engine)"));
        keep.value = "";
        control.insertBefore(keep, control.firstChild);
        if (!state.model) keep.selected = true;
      } else if (!state.model) {
        state.model = control.value;
      }
      control.addEventListener("change", function () {
        state.model = control.value;
        testResult = null;
        paintTest();
      });
    } else {
      control = document.createElement("input");
      control.type = "text";
      control.value = state.model;
      control.placeholder = uiT("setup_model_ph", "llama3.2");
      control.addEventListener("input", function () {
        state.model = control.value.trim();
        testResult = null;
        paintTest();
      });
      if (state.providerKind === "ollama") {
        body.appendChild(el(
          "p", "wizard-warning",
          models.error
            ? uiT("setup_ollama_down", "Ollama is not reachable, so installed models cannot be listed. Start it with `ollama serve`, then reload.")
            : uiT("setup_no_models", "No models are installed yet. Download one with `ollama pull llama3.2`."),
        ));
      }
    }
    control.id = "setup-model";
    body.appendChild(field(uiT("set_col_model", "Model"), control));

    var testRow = el("div", "wizard-inline");
    var test = el("button", "btn", uiT("setup_test_it", "Test it"));
    test.type = "button";
    test.id = "setup-test";
    var testOut = el("span", "wizard-test-result", "");
    testOut.id = "setup-test-result";
    testOut.setAttribute("role", "status");
    testRow.appendChild(test);
    testRow.appendChild(testOut);
    body.appendChild(testRow);
    body.appendChild(el(
      "p", "wizard-help",
      uiT("setup_test_help", "Sends one short string to the model to confirm it answers."),
    ));

    function paintTest() {
      testOut.textContent = testResult ? testResult.message : "";
      testOut.className = "wizard-test-result" + (testResult ? (testResult.ok ? " is-ok" : " is-bad") : "");
    }
    test.addEventListener("click", function () {
      if (!state.model) {
        testResult = { ok: false, message: uiT("setup_choose_model", "Choose a model first.") };
        paintTest();
        return;
      }
      var confirm = true;
      if (state.providerKind !== "ollama" && state.providerKind !== "null") {
        confirm = window.confirm(
          uiT("setup_paid_confirm", "'{kind}' is a paid provider. Send one short test string to it?").replace("{kind}", state.providerKind),
        );
      }
      if (!confirm) return;
      test.disabled = true;
      testOut.textContent = uiT("setup_testing", "Testing…");
      postJson("/api/setup/smoke-test", {
        project: project(), model: state.model, confirm: true,
      }).then(function (result) {
        testResult = { ok: !!result.ok, message: result.message || result.error || uiT("setup_no_answer", "No answer.") };
      }).catch(function () {
        testResult = { ok: false, message: uiT("setup_test_failed", "The test request failed.") };
      }).then(function () {
        test.disabled = false;
        paintTest();
      });
    });
    paintTest();
  }

  // ---- step 4: domain -------------------------------------------------------

  function paintDomain() {
    body.appendChild(el("h2", "wizard-title", uiT("setup_step_product", "About your product")));
    body.appendChild(el(
      "p", "wizard-help",
      uiT("setup_domain_help", "One sentence. It goes into every translation prompt and is the biggest lever on terminology."),
    ));
    var area = document.createElement("textarea");
    area.id = "setup-domain";
    area.rows = 3;
    area.placeholder = uiT("setup_domain_ph", "a hotel booking app for business travellers");
    area.value = state.domain;
    area.addEventListener("input", function () { state.domain = area.value.trim(); });
    body.appendChild(field(uiT("setup_what_is_it", "What is it?"), area));
  }

  // ---- step: approach (ADR-123 / plan D4) ------------------------------------

  function paintApproach() {
    body.appendChild(el("h2", "wizard-title", uiT("setup_approach_title", "How should strings get translated?")));
    body.appendChild(el(
      "p", "wizard-help",
      uiT("setup_approach_help", "This records [translate] approach in the project config. You can change it later with llm-localizator approach --set."),
    ));
    var list = el("div", "setup-approach-list");
    (state.approaches || []).forEach(function (a) {
      var row = el("label", "op-check setup-approach-row");
      var radio = el("input", "");
      radio.type = "radio";
      radio.name = "setup-approach";
      radio.value = a.id;
      if (state.approach === a.id) radio.checked = true;
      radio.addEventListener("change", function () {
        if (radio.checked) state.approach = a.id;
      });
      row.appendChild(radio);
      var text = el("span", "");
      text.appendChild(el("strong", "", a.title || a.id));
      text.appendChild(document.createTextNode(" — " + (a.words || "")));
      if (a.when) text.appendChild(el("div", "field-hint", a.when));
      row.appendChild(text);
      list.appendChild(row);
    });
    if (!(state.approaches || []).length) {
      list.appendChild(el("p", "wizard-warning", uiT("setup_approach_missing", "Approach list did not load.")));
    }
    body.appendChild(list);
  }

  // ---- step: finish -------------------------------------------------------

  function summaryRow(list, label, value) {
    list.appendChild(el("dt", "", label));
    list.appendChild(el("dd", "", value));
  }

  function paintFinish() {
    body.appendChild(el("h2", "wizard-title", uiT("setup_ready_title", "Ready to save")));
    var list = el("dl", "wizard-summary");
    summaryRow(list, uiT("setup_sum_source", "Source language"), labelOf(state.sourceLocale));
    summaryRow(
      list, uiT("setup_sum_targets", "Translating into"),
      state.targets.length
        ? state.targets.map(labelOf).join(", ")
        : uiT("setup_sum_nothing", "nothing yet"),
    );
    summaryRow(list, uiT("set_col_model", "Model"), state.model || uiT("setup_sum_not_chosen", "not chosen"));
    summaryRow(list, uiT("setup_sum_product", "Product"), state.domain || uiT("setup_sum_not_described", "not described"));
    summaryRow(list, uiT("setup_sum_approach", "Approach"), state.approach || uiT("setup_sum_not_chosen", "not chosen"));
    body.appendChild(list);
    if (!state.targets.length) {
      body.appendChild(el(
        "p", "wizard-warning",
        uiT("setup_no_langs_warn", "No languages selected, so there is nothing to translate yet. Go back to add one."),
      ));
    }
  }

  function paintDone(nextStep) {
    body.replaceChildren();
    progress.hidden = true;
    body.appendChild(el("h2", "wizard-title", uiT("setup_saved", "Saved")));
    body.appendChild(el(
      "p", "wizard-help",
      nextStep
        ? uiT("setup_next_step", "Next step: {step}").replace("{step}", nextStep)
        : uiT("setup_all_set", "Everything is set up."),
    ));
    var buttons = el("div", "ops-actions");
    if (state.targets.length) {
      var run = el("button", "btn btn-primary", uiT("setup_run_first", "Run first translation"));
      run.type = "button";
      run.addEventListener("click", function () {
        run.disabled = true;
        status.textContent = uiT("setup_translating", "Translating… this can take a while.");
        postJson("/api/ops/run-translate", { project: project(), locales: state.targets })
          .then(function (result) {
            status.textContent = result.ok
              ? uiT("setup_translate_done", "Done. Open the editor to review the translations.")
              : (result.error || result.summary || uiT("setup_translate_fail", "Could not translate."));
          })
          .catch(function () { status.textContent = uiT("setup_request_failed", "Request failed."); })
          .then(function () { run.disabled = false; });
      });
      buttons.appendChild(run);
    }
    var editor = el("a", "btn", uiT("dash_open_the_editor", "Open the editor"));
    editor.href = "/app/editor";
    var dash = el("a", "btn", uiT("setup_go_dashboard", "Go to the dashboard"));
    dash.href = "/app";
    buttons.appendChild(editor);
    buttons.appendChild(dash);
    body.appendChild(buttons);
    actions.hidden = true;
  }

  function save() {
    status.textContent = uiT("pc_saving", "Saving…");
    next.disabled = true;
    var payload = {
      project: project(),
      source_locale: state.sourceLocale || undefined,
      targets: state.targets,
      model: state.model || undefined,
      domain: state.domain || undefined,
      approach: state.approach || undefined,
    };
    if (state.catalogFormat) payload.catalog_format = state.catalogFormat;
    if (state.catalogPath) payload.catalog_path = state.catalogPath;
    postJson("/api/setup", payload).then(function (result) {
      if (!result.ok) {
        status.textContent = result.error || uiT("setup_failed", "Setup failed.");
        next.disabled = false;
        return;
      }
      status.textContent = "";
      return postJson("/api/ops/guide", { project: project(), skip_provider: true })
        .then(function (guide) {
          var data = guide && guide.data;
          var steps = (data && data.steps) || [];
          var pending = null;
          steps.forEach(function (s) {
            if (!pending && data.next === s.id) pending = s;
          });
          paintDone(pending ? pending.title + (pending.cli ? " (" + pending.cli + ")" : "") : "");
        });
    }).catch(function () {
      status.textContent = uiT("setup_request_failed", "Request failed.");
      next.disabled = false;
    });
  }

  var painters = [paintEngine, paintProject, paintLanguages, paintModel, paintDomain, paintApproach, paintFinish];

  function paint() {
    body.replaceChildren();
    status.textContent = "";
    paintProgress();
    painters[index]();
    var wizardTitle = body.querySelector(".wizard-title");
    if (wizardTitle && window.LLMHelp) {
      wizardTitle.appendChild(window.LLMHelp.helpBtn(
        ["settings:engine", "setup:project", "setup:languages", "setup:model", "setup:product", "setup:approach", "setup:finish"][index],
      ));
    }
    prev.disabled = index === 0;
    next.textContent = index === painters.length - 1
      ? uiT("wf_save", "Save")
      : uiT("setup_next", "Next");
    next.disabled = false;
  }

  prev.addEventListener("click", function () {
    if (index > 0) {
      index -= 1;
      paint();
    }
  });
  next.addEventListener("click", function () {
    if (index < painters.length - 1) {
      index += 1;
      paint();
      return;
    }
    save();
  });

  var query = "project=" + encodeURIComponent(project());
  Promise.all([
    getJson("/api/setup-state?" + query).catch(function () { return {}; }),
    getJson("/api/locales").catch(function () { return { locales: [] }; }),
    getJson("/api/models?" + query).catch(function () { return {}; }),
    postJson("/api/ops/guide", { project: project(), skip_provider: true }).catch(function () { return {}; }),
  ]).then(function (results) {
    var current = results[0] || {};
    state.sourceLocale = current.sourceLocale || state.sourceLocale;
    state.targets = (current.targets || []).slice();
    state.model = current.model || "";
    state.domain = current.domain && current.domain !== "a software application" ? current.domain : "";
    state.providerKind = current.providerKind || state.providerKind;
    state.catalogFormat = current.catalogFormat || "";
    if (current.catalogFormats && current.catalogFormats.length) state.catalogFormats = current.catalogFormats;
    state.catalogPath = current.catalogPath || "";
    state.approach = current.approach || "";
    state.approaches = current.approaches || [];
    known = (results[1] && results[1].locales) || [];
    var modelInfo = results[2] || {};
    models.list = modelInfo.models || [];
    models.error = modelInfo.error || "";
    var steps = (results[3] && results[3].data && results[3].data.steps) || [];
    steps.forEach(function (s) {
      if (s.id === "project") projectSummary = s.detail;
    });
    paint();
  });
})();
