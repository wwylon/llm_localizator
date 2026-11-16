(function () {
  var root = document.getElementById("page-body");
  var _page = document.getElementById("page");
  if (!root || !_page || _page.dataset.page !== "operations") return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  var commands = {};
  var groups = ["Analysis", "LLM Pipeline", "Data", "Maintenance", "Other"];
  var groupOrder = {};
  var current = "";
  var abort = null;
  var projectLocales = [];
  var projectFrozen = [];
  var projectNamespaces = [];
  var displayNames = null;
  try {
    displayNames = new Intl.DisplayNames(["en"], { type: "language" });
  } catch (err) {
    displayNames = null;
  }

  function groupLabel(group) {
    var key = ({
      Analysis: "op_group_analysis",
      "LLM Pipeline": "op_group_llm",
      Data: "op_group_data",
      Maintenance: "op_group_maintenance",
      Other: "op_group_other",
    })[group];
    return key ? uiT(key, group) : group;
  }

  function commandDesc(name, fallback) {
    var slug = String(name || "").replace(/^run-/, "").replace(/-/g, "_");
    return uiT("op_cmd_" + slug + "_d", fallback || name || "");
  }

  function roleLabel(role) {
    var key = ({
      Admin: "role_admin",
      Supervisor: "role_supervisor",
      Translator: "role_translator",
      Developer: "role_developer",
    })[role];
    return key ? uiT(key, role) : role;
  }

  function friendlyLabel(name) {
    var map = {
      check_layout: uiT(
        "op_f_check_layout",
        "Check layout (V28) — screenshot QA where context notes reference PNGs",
      ),
      check_numbers: uiT(
        "op_f_check_numbers",
        "Check numbers (V38) — locale-aware number/date format checks",
      ),
      strict: uiT("op_f_strict", "--strict — exit non-zero if coverage < 100%"),
      check_expansion: uiT(
        "op_f_check_expansion",
        "Check expansion (V14) — expansion-band advisory",
      ),
      semantic: uiT(
        "op_f_semantic",
        "Semantic advisory checks (whitespace / punctuation)",
      ),
      write_flags: uiT("op_f_write_flags", "Write flags for improve"),
      quiet: uiT("op_f_quiet", "Quiet — print only the summary line"),
      force: uiT(
        "op_f_force",
        "Force retranslate — overwrite existing machine translations",
      ),
      missing: uiT("op_f_missing", "--missing — list each problem key with reason"),
      no_write: uiT("op_f_no_write", "Report only; write nothing"),
      fail_on_hardcoded: uiT(
        "op_f_fail_on_hardcoded",
        "Exit non-zero if any hardcoded string is found",
      ),
      diff_only: uiT(
        "op_f_diff_only",
        "Diff only — compare against previous release",
      ),
      unused: uiT(
        "op_f_unused",
        "Unused — report keys not referenced in source",
      ),
    };
    return map[name] || uiT("op_f_" + name, name);
  }

  var PRIMARY = {
    validate: ["check_layout", "check_numbers", "strict"],
    status: ["missing"],
    translate: ["force"],
    improve: ["limit"],
    scan: ["out_dir", "adapter", "no_write", "strict"],
    "estimate-cost": [],
    "agent-backlog": ["fmt", "format"],
    "ingest-visual": ["path"],
    export: ["format", "only", "screenshots"],
    import: [],
    documents: ["doc", "doc_dir"],
    init: ["taskqueue"],
    draft: ["action", "locale", "key", "mode"],
    task: ["action", "id", "name", "keys", "assign", "assignee"],
    discuss: ["action", "key", "text"],
    "screenshot-link": ["action", "file", "key", "region", "link"],
    "source-diff": ["locale", "key"],
    "open-pr": ["action", "pr_branch", "yes"],
  };

  var ROLE_CLASS = {
    Admin: "role-badge role-admin",
    Supervisor: "role-badge role-supervisor",
    Translator: "role-badge role-translator",
    Developer: "role-badge role-developer",
  };

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

  function localeName(code) {
    if (!code) return "";
    if (!displayNames) return code;
    try {
      return displayNames.of(code) || code;
    } catch (err) {
      return code;
    }
  }

  function myRole() {
    var me = window.__LLM_ME;
    return me && me.authenticated ? (me.role || "") : "";
  }

  function roleAllowed(spec) {
    var role = myRole();
    if (!role) return true;
    if (role === "Admin") return true;
    var roles = (spec && spec.roles) || [];
    return roles.indexOf(role) >= 0;
  }

  function requiresLlm(spec) {
    if (!spec) return false;
    if (typeof spec.requires_llm === "boolean") return spec.requires_llm;
    if (typeof spec.llm === "boolean") return spec.llm;
    var g = spec.group || "";
    // ``LLM`` is the pre-rename group name (stale server / cached manifest).
    if (g === "LLM Pipeline" || g === "LLM") return true;
    var name = current || "";
    return /^run-(translate|improve|review|rescore|documents)$/.test(name);
  }

  var layout = el("div", "op-layout");
  var carousel = el("div", "op-carousel");
  var prevBtn = el("button", "op-carousel-arrow", "▲");
  prevBtn.type = "button";
  prevBtn.setAttribute("aria-label", uiT("op_scroll_up", "Scroll commands up"));
  var track = el("div", "op-carousel-track");
  track.id = "op-carousel-track";
  var nextBtn = el("button", "op-carousel-arrow", "▼");
  nextBtn.type = "button";
  nextBtn.setAttribute("aria-label", uiT("op_scroll_down", "Scroll commands down"));
  carousel.appendChild(prevBtn);
  carousel.appendChild(track);
  carousel.appendChild(nextBtn);
  var main = el("div", "op-main");

  var head = el("div", "op-cmd-head");
  var headLeft = el("div", "op-cmd-head-text");
  var titleRow = el("div", "op-cmd-title-row");
  var title = el("h2", "op-cmd-title", "…");
  title.id = "op-cmd-title";
  var llmBadge = el("span", "op-llm-badge", "");
  llmBadge.id = "op-llm-badge";
  var roleBadges = el("div", "op-role-badges");
  roleBadges.id = "op-role-badges";
  titleRow.appendChild(title);
  titleRow.appendChild(llmBadge);
  titleRow.appendChild(roleBadges);
  var desc = el("p", "op-cmd-desc", uiT("op_loading_commands", "Loading commands."));
  desc.id = "op-cmd-desc";
  headLeft.appendChild(titleRow);
  headLeft.appendChild(desc);
  var headRight = el("div", "op-head-right");
  var wfPageLink = el("a", "btn op-wf-link", uiT("op_workflows", "Workflows"));
  wfPageLink.href = "/app/workflow";
  wfPageLink.title = uiT(
    "op_workflows_tip",
    "Edit and run locale workflows on the Workflow page",
  );
  var permLink = el("a", "btn op-perm-link", uiT("op_permissions", "⚙ Permissions"));
  permLink.href = "/app/settings#permissions";
  headRight.appendChild(wfPageLink);
  headRight.appendChild(permLink);
  head.appendChild(headLeft);
  head.appendChild(headRight);
  if (window.LLMHelp) {
    var pageHead = document.querySelector("#page .page-head");
    if (pageHead) pageHead.appendChild(window.LLMHelp.helpBtn("operations:general"));
  }

  var scroll = el("div", "op-scroll");
  var formCard = el("div", "op-form-card");
  var optionsLabel = el("div", "op-form-label", uiT("op_options", "Options"));
  formCard.appendChild(optionsLabel);
  var form = el("div", "");
  form.id = "op-form";
  formCard.appendChild(form);

  var dryCheckLabel = el("label", "op-check");
  var dryCheck = document.createElement("input");
  dryCheck.type = "checkbox";
  dryCheck.id = "op-dry-check";
  dryCheckLabel.appendChild(dryCheck);
  var dryCheckText = document.createTextNode(
    " " + uiT("op_dry_check", "Dry run — print what would happen, write nothing"),
  );
  dryCheckLabel.appendChild(dryCheckText);
  formCard.appendChild(dryCheckLabel);

  var actions = el("div", "op-actions");
  var runBtn = el("button", "btn btn-primary", uiT("op_run", "▶ Run"));
  runBtn.type = "button";
  var submitBtn = el("button", "btn", uiT("op_submit_tq", "Submit to taskqueue"));
  submitBtn.type = "button";
  submitBtn.hidden = true;
  var dryBtn = el("button", "btn", uiT("wf_run_dry", "Dry run"));
  dryBtn.type = "button";
  var stopBtn = el("button", "btn", uiT("wf_blk_stop", "Stop"));
  stopBtn.type = "button";
  stopBtn.hidden = true;
  actions.appendChild(runBtn);
  actions.appendChild(submitBtn);
  actions.appendChild(dryBtn);
  actions.appendChild(stopBtn);
  formCard.appendChild(actions);

  var models = el("p", "op-models", uiT("op_models_ellipsis", "Installed models: …"));

  var logWrap = el("div", "op-log-wrap");
  logWrap.id = "op-log-wrap";
  var logHead = el("div", "op-log-head");
  var logStatus = el("span", "op-log-status", uiT("op_output", "Output"));
  logStatus.id = "op-log-status";
  var clearBtn = el("button", "btn op-log-clear", uiT("ed_clear", "Clear"));
  clearBtn.type = "button";
  logHead.appendChild(logStatus);
  logHead.appendChild(clearBtn);
  var logBody = el("div", "op-log-body");
  logBody.id = "op-log";
  var logEmpty = el(
    "div", "log-line-dim",
    uiT("op_output_empty", "Output appears here after you run an operation."),
  );
  logBody.appendChild(logEmpty);
  logWrap.appendChild(logHead);
  logWrap.appendChild(logBody);

  // Per-command output — switching commands must not wipe another op's log.
  var logsByCmd = {};
  var serverCounts = {};
  var USAGE_KEY = "llm_op_usage";

  var pane = el("div", "op-pane");
  pane.appendChild(formCard);
  pane.appendChild(models);
  pane.appendChild(logWrap);
  scroll.appendChild(pane);
  main.appendChild(head);
  main.appendChild(scroll);
  layout.appendChild(carousel);
  layout.appendChild(main);
  root.replaceChildren(layout);

  prevBtn.addEventListener("click", function () {
    track.scrollBy({ top: -180, behavior: "smooth" });
  });
  nextBtn.addEventListener("click", function () {
    track.scrollBy({ top: 180, behavior: "smooth" });
  });

  function loadUsage() {
    try {
      return JSON.parse(localStorage.getItem(USAGE_KEY) || "{}") || {};
    } catch (err) {
      return {};
    }
  }

  function bumpUsage(name) {
    if (!name) return;
    var usage = loadUsage();
    usage[name] = (usage[name] || 0) + 1;
    try {
      localStorage.setItem(USAGE_KEY, JSON.stringify(usage));
    } catch (err) { /* ignore quota */ }
  }

  function usageScore(name) {
    return (loadUsage()[name] || 0) + (serverCounts[name] || 0);
  }

  function curatedPriority() {
    var out = [];
    groups.forEach(function (group) {
      (groupOrder[group] || []).forEach(function (name) {
        if (out.indexOf(name) < 0) out.push(name);
      });
    });
    return out;
  }

  function orderedCommands() {
    var priority = curatedPriority();
    return Object.keys(commands).sort(function (a, b) {
      var ua = usageScore(a);
      var ub = usageScore(b);
      if (ub !== ua) return ub - ua;
      var ia = priority.indexOf(a);
      var ib = priority.indexOf(b);
      if (ia < 0) ia = 10000;
      if (ib < 0) ib = 10000;
      if (ia !== ib) return ia - ib;
      return a < b ? -1 : (a > b ? 1 : 0);
    });
  }

  function ensureLog(name) {
    if (!name) name = current;
    if (!logsByCmd[name]) {
      logsByCmd[name] = { lines: [], status: uiT("op_output", "Output"), visible: false };
    }
    return logsByCmd[name];
  }

  clearBtn.addEventListener("click", function () {
    var store = ensureLog(current);
    store.lines = [];
    store.visible = false;
    store.status = uiT("op_output", "Output");
    logBody.replaceChildren(
      el("div", "log-line-dim", uiT("op_output_empty", "Output appears here after you run an operation."))
    );
    logStatus.textContent = uiT("op_output", "Output");
  });

  function classifyLine(line) {
    var t = String(line || "");
    if (/^\$/.test(t) || /^\s*llm-localizator\b/.test(t) || /^\s*tq\s+/.test(t)) return "log-line-cmd";
    if (/⚠|warn/i.test(t)) return "log-line-warn";
    if (/✗|Error\b|failed|refused/i.test(t)) return "log-line-err";
    if (/[✓✔]|queued:|complete\.|written:|stamped /i.test(t)) return "log-line-ok";
    if (/^#|^\.\.\.|^\s*$/.test(t)) return "log-line-dim";
    return "log-line-info";
  }

  function showLogFor(name) {
    var store = ensureLog(name);
    logBody.replaceChildren();
    if (!store.lines.length) {
      logBody.appendChild(
        el("div", "log-line-dim", uiT("op_output_empty", "Output appears here after you run an operation."))
      );
    } else {
      store.lines.forEach(function (row) {
        logBody.appendChild(el("div", row.cls, row.text));
      });
    }
    logStatus.textContent = store.status || uiT("op_output", "Output");
    logBody.scrollTop = logBody.scrollHeight;
  }

  function clearLog(cmdName) {
    var name = cmdName || current;
    var store = ensureLog(name);
    store.lines = [];
    store.visible = false;
    if (name === current) {
      logBody.replaceChildren();
    }
  }

  function appendLog(text, cmdName) {
    var name = cmdName || current;
    var store = ensureLog(name);
    store.visible = true;
    if (name === current && store.lines.length === 0) {
      logBody.replaceChildren();
    }
    String(text == null ? "" : text).split("\n").forEach(function (line) {
      var cls = classifyLine(line);
      store.lines.push({ cls: cls, text: line });
      if (name === current) {
        logBody.appendChild(el("div", cls, line));
      }
    });
    if (name === current) logBody.scrollTop = logBody.scrollHeight;
  }

  function setLogStatus(text, cmdName) {
    var name = cmdName || current;
    var store = ensureLog(name);
    store.status = text || uiT("op_output", "Output");
    if (name === current) logStatus.textContent = store.status;
  }

  function paintCarousel() {
    track.replaceChildren();
    orderedCommands().forEach(function (name) {
      var spec = commands[name] || {};
      var allowed = roleAllowed(spec);
      var cls = "cmd-btn";
      if (name === current) cls += " active";
      if (!allowed) cls += " locked";
      var item = el("button", cls, name);
      item.type = "button";
      item.disabled = !allowed;
      item.title = groupLabel(spec.group || "Other")
        + (usageScore(name)
          ? " · " + uiT("op_used_n", "used {n}×").replace("{n}", String(usageScore(name)))
          : "");
      item.dataset.command = name;
      item.addEventListener("click", function () {
        if (!allowed) return;
        current = name;
        paintCarousel();
        paintForm();
        var active = track.querySelector(".cmd-btn.active");
        if (active && active.scrollIntoView) {
          active.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
        }
      });
      track.appendChild(item);
    });
  }

  function commandHelpKey() {
    var H = window.LLMHelp;
    if (!H || !current) return null;
    var key = "operations:" + current;
    if (H.has(key)) return key;
    var base = "operations:" + current.replace(/^run-/, "");
    return H.has(base) ? base : null;
  }

  function paintCommandHelp() {
    var old = title.parentNode && title.parentNode.querySelector(".op-cmd-help");
    if (old) old.remove();
    var key = commandHelpKey();
    if (!key) return;
    var btn = window.LLMHelp.helpBtn(key);
    btn.classList.add("op-cmd-help");
    title.parentNode.insertBefore(btn, title.nextSibling);
  }

  function paintHeader() {
    var spec = commands[current] || {};
    var needsLlm = requiresLlm(spec);
    title.textContent = current || "…";
    paintCommandHelp();
    llmBadge.textContent = needsLlm
      ? uiT("op_llm_required", "LLM required")
      : uiT("op_no_llm", "no LLM needed");
    llmBadge.className = "op-llm-badge" + (needsLlm ? " is-llm" : "");
    desc.textContent = commandDesc(current, spec.description || current || "");
    roleBadges.replaceChildren();
    (spec.roles || []).forEach(function (role) {
      roleBadges.appendChild(el(
        "span",
        ROLE_CLASS[role] || "role-badge",
        roleLabel(role),
      ));
    });
    submitBtn.hidden = !spec.submit;
  }

  function fieldByName(fields, name) {
    for (var i = 0; i < fields.length; i += 1) {
      if (fields[i].name === name) return fields[i];
    }
    return null;
  }

  function paintLocaleChips(selected) {
    var wrap = el("div", "op-field");
    wrap.appendChild(el("span", "field-label", uiT("set_tab_locales", "Locales")));
    var chips = el("div", "op-locale-chips");
    chips.id = "op-locale-chips";
    var wanted = selected || [];
    var params = new URLSearchParams(window.location.search);
    var fromUrl = params.get("locales");
    if (fromUrl && !wanted.length) {
      wanted = fromUrl.split(",").map(function (p) { return p.trim(); }).filter(Boolean);
    }
    var list = projectLocales.length ? projectLocales : wanted;
    if (!list.length) {
      var fallback = document.createElement("input");
      fallback.type = "text";
      fallback.dataset.field = "locales";
      fallback.dataset.type = "str";
      fallback.placeholder = uiT("op_locales_ph", "de, pl");
      if (wanted.length) fallback.value = wanted.join(", ");
      wrap.appendChild(fallback);
      form.appendChild(wrap);
      return;
    }

    var allLab = el("label", "op-locale-chip op-locale-all");
    var allBox = document.createElement("input");
    allBox.type = "checkbox";
    allBox.id = "op-locale-all";
    allLab.appendChild(allBox);
    allLab.appendChild(el("span", "op-locale-code", uiT("pageSizeAll", "all")));
    chips.appendChild(allLab);

    function localeBoxes() {
      return chips.querySelectorAll("[data-locale-chip]");
    }

    function syncAll() {
      var boxes = localeBoxes();
      var checked = 0;
      boxes.forEach(function (box) { if (box.checked) checked += 1; });
      allBox.checked = boxes.length > 0 && checked === boxes.length;
      allBox.indeterminate = checked > 0 && checked < boxes.length;
    }

    allBox.addEventListener("change", function () {
      var on = allBox.checked;
      localeBoxes().forEach(function (box) { box.checked = on; });
      allBox.indeterminate = false;
    });

    // An LLM run leaves frozen locales out by default (the server does the same); ticking one is explicit.
    var llmRun = requiresLlm(commands[current] || {});
    list.forEach(function (code) {
      var isFrozen = projectFrozen.indexOf(code) >= 0;
      var lab = el("label", "op-locale-chip" + (isFrozen ? " is-frozen" : ""));
      var box = document.createElement("input");
      box.type = "checkbox";
      box.value = code;
      box.dataset.localeChip = "1";
      box.checked = wanted.length ? wanted.indexOf(code) >= 0 : !(llmRun && isFrozen);
      box.addEventListener("change", syncAll);
      lab.appendChild(box);
      var codeEl = el("span", "op-locale-code", code);
      lab.appendChild(codeEl);
      lab.appendChild(document.createTextNode(" " + localeName(code)));
      if (isFrozen) lab.appendChild(el("span", "an-tag", uiT("an_frozen", "frozen")));
      chips.appendChild(lab);
    });
    syncAll();
    wrap.appendChild(chips);
    form.appendChild(wrap);
  }

  function paintNamespaceSelect(field) {
    var wrap = el("div", "op-field");
    wrap.appendChild(el("span", "field-label", uiT("an_ns_label", "Namespace")));
    var select = document.createElement("select");
    select.dataset.field = "namespace";
    select.dataset.type = "str";
    select.appendChild(el("option", "", uiT("nsAll", "(all namespaces)")));
    select.options[0].value = "";
    projectNamespaces.forEach(function (name) {
      select.appendChild(el("option", "", name));
    });
    if (field && field.default != null && field.default !== false) {
      select.value = String(field.default);
    }
    wrap.appendChild(select);
    form.appendChild(wrap);
  }

  function makeInput(field) {
    var input;
    if (field.type === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!field.default;
    } else if (field.choices && field.choices.length) {
      input = document.createElement("select");
      field.choices.forEach(function (choice) {
        // The value stays the CLI id; only the caption is localised (``op_c_<choice>``).
        var option = el("option", "", uiT("op_c_" + slugOf(choice), String(choice)));
        option.value = String(choice);
        input.appendChild(option);
      });
      if (field.default != null) input.value = String(field.default);
    } else {
      input = document.createElement("input");
      input.type = field.type === "int" || field.type === "float" ? "number" : "text";
      if (field.type === "float") input.step = "any";
      if (field.default != null && field.default !== false) input.value = String(field.default);
    }
    input.dataset.field = field.name;
    input.dataset.type = field.type || "str";
    return input;
  }

  function paintBoolField(field, labelText) {
    var lab = el("label", "op-check");
    var input = makeInput(field);
    lab.appendChild(input);
    lab.appendChild(document.createTextNode(
      " " + (labelText || friendlyLabel(field.name)),
    ));
    form.appendChild(lab);
  }

  function slugOf(text) {
    return String(text || "").replace(/^run-/, "").replace(/[^A-Za-z0-9]+/g, "_");
  }

  /** Argument help from the CLI parser, localised per command (``op_h_<cmd>_<field>``). */
  function fieldHint(field) {
    return uiT("op_h_" + slugOf(current) + "_" + slugOf(field.name), field.help);
  }

  function paintLabeledField(field, labelText) {
    var wrap = el("div", "op-field");
    wrap.appendChild(el(
      "span", "field-label", labelText || friendlyLabel(field.name),
    ));
    wrap.appendChild(makeInput(field));
    if (field.help) wrap.appendChild(el("div", "field-hint", fieldHint(field)));
    form.appendChild(wrap);
  }

  function paintExport() {
    var format = document.createElement("select");
    format.id = "op-format";
    ["csv", "xliff", "json", "xlsx"].forEach(function (name) {
      format.appendChild(el("option", "", name));
    });
    var layoutSelect = document.createElement("select");
    layoutSelect.id = "op-layout";
    ["single", "per-locale", "per-namespace"].forEach(function (name) {
      layoutSelect.appendChild(el("option", "", name));
    });
    var onlySelect = document.createElement("select");
    onlySelect.id = "op-only";
    ["all", "missing", "stale", "machine", "low_score"].forEach(function (name) {
      onlySelect.appendChild(el("option", "", name));
    });
    var row = el("div", "op-field-row");
    var f1 = el("div", "op-field");
    f1.appendChild(el("span", "field-label", uiT("set_format", "Format")));
    f1.appendChild(format);
    var f2 = el("div", "op-field");
    f2.appendChild(el("span", "field-label", uiT("op_layout", "Layout")));
    f2.appendChild(layoutSelect);
    row.appendChild(f1);
    row.appendChild(f2);
    form.appendChild(row);
    var f3 = el("div", "op-field");
    f3.appendChild(el("span", "field-label", uiT("op_only", "Only")));
    f3.appendChild(onlySelect);
    form.appendChild(f3);
    var shots = el("label", "op-check");
    var shotBox = document.createElement("input");
    shotBox.type = "checkbox";
    shotBox.id = "op-screenshots";
    shots.appendChild(shotBox);
    shots.appendChild(document.createTextNode(
      " " + uiT("op_include_screenshots", "Include screenshots (forces zip)"),
    ));
    form.appendChild(shots);
    var appr = el("label", "op-check");
    var apprBox = document.createElement("input");
    apprBox.type = "checkbox";
    apprBox.id = "op-approved-only";
    appr.appendChild(apprBox);
    appr.appendChild(document.createTextNode(
      " " + uiT(
        "op_approved_only",
        "Approved translations only (others are left blank)",
      ),
    ));
    form.appendChild(appr);
  }

  function paintImport() {
    var files = document.createElement("input");
    files.id = "op-import-files";
    files.type = "file";
    files.multiple = true;
    files.accept = ".csv,.xlsx,.xlf,.xliff,.json,.zip";
    var who = document.createElement("input");
    who.id = "op-localized-by";
    who.type = "text";
    who.placeholder = uiT("op_localized_by_ph", "e.g. deepseek, external-agency");
    var f1 = el("div", "op-field");
    f1.appendChild(el("span", "field-label", uiT("op_file", "File")));
    f1.appendChild(files);
    f1.appendChild(el(
      "div", "field-hint",
      uiT("op_import_hint", "Accepted: CSV, XLIFF 1.2, XLIFF 2.0, JSON handoff, ZIP"),
    ));
    var f2 = el("div", "op-field");
    f2.appendChild(el("span", "field-label", uiT("op_localized_by", "Localized by")));
    f2.appendChild(who);
    form.appendChild(f1);
    form.appendChild(f2);
  }

  // W4: one-run engine for the LLM ops dispatch_op reloads the config for (ADR-156). The list comes from the engine
  // op, which is Admin-only: anyone else gets no select and the project's engine runs.
  var ENGINE_CMDS = { translate: true, improve: true, review: true, rescore: true, documents: true };
  var enginesPromise = null;

  function loadEngines() {
    if (!enginesPromise) {
      var body = { project: project(), action: "list" };
      var req = (window.LLMApi && LLMApi.apiPost)
        ? LLMApi.apiPost("/api/ops/engine", body)
        : fetch("/api/ops/engine", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }).then(function (r) { return r.ok ? r.json() : null; });
      enginesPromise = req.then(function (res) {
        return res && res.ok !== false && res.data ? res.data : null;
      }).catch(function () { return null; });
    }
    return enginesPromise;
  }

  function paintEngineSelect() {
    var wrap = el("div", "op-field op-engine-field");
    wrap.hidden = true;
    var label = el("label", "field-label", uiT("op_engine_label", "Engine (this run only)"));
    var select = document.createElement("select");
    select.id = "op-engine";
    select.dataset.field = "engine";
    label.htmlFor = "op-engine";
    wrap.appendChild(label);
    wrap.appendChild(select);
    wrap.appendChild(el("span", "field-hint", uiT(
      "op_engine_hint", "Overrides the project's engine for this run; the config is not changed.")));
    form.appendChild(wrap);
    loadEngines().then(function (info) {
      if (!info || !wrap.isConnected) return;
      var def = el("option", "", uiT("op_engine_default", "Project engine") +
        (info.current ? " (" + info.current + ")" : ""));
      def.value = "";
      select.appendChild(def);
      (info.engines || []).forEach(function (engine) {
        if (engine.current) return;
        var opt = el("option", "", engine.id + " · " + (engine.name || "") + (engine.fits ? "" : " (" + engine.why + ")"));
        opt.value = engine.id;
        select.appendChild(opt);
      });
      wrap.hidden = false;
    });
  }

  function costModal(est, runCmd, engine) {
    // In-page confirm (shared .modal / .blueprint-card pattern) instead of window.confirm.
    return new Promise(function (resolve) {
      var overlay = el("div", "modal op-cost-modal");
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.setAttribute("aria-labelledby", "op-cost-title");
      var box = el("div", "modal-body blueprint-card");
      var title = el("h2", "", uiT("ops_cost_title", "This run calls a paid cloud model"));
      title.id = "op-cost-title";
      box.appendChild(title);
      var table = el("table", "settings-table op-cost-table");
      var body = document.createElement("tbody");
      function row(label, value) {
        var tr = document.createElement("tr");
        tr.appendChild(el("th", "", label));
        tr.appendChild(el("td", "settings-mono", value));
        body.appendChild(tr);
      }
      row(uiT("ops_cost_engine", "Engine"), (engine || uiT("op_engine_default", "Project engine")) +
        (est.model ? " · " + (est.provider ? est.provider + " / " : "") + est.model : ""));
      row(uiT("ops_cost_estimate", "Estimated"), "$" + est.batch_usd + " (" + uiT("ops_cost_max", "at most") +
        " $" + est.max_usd + ")");
      var perLocale = est.per_locale || est.locales_usd || null;
      if (perLocale && typeof perLocale === "object") {
        Object.keys(perLocale).forEach(function (loc) {
          var v = perLocale[loc];
          row("  " + loc, "$" + (v && typeof v === "object" ? (v.batch_usd != null ? v.batch_usd : v.max_usd) : v));
        });
      }
      if (est.keys != null) row(uiT("ops_cost_keys", "Strings"), String(est.keys));
      row(uiT("ops_cost_remaining", "budget left"), "$" + est.remaining_usd);
      table.appendChild(body);
      box.appendChild(table);
      var actions = el("div", "settings-actions");
      var cancel = el("button", "btn", uiT("btn_cancel", "Cancel"));
      cancel.type = "button";
      var go = el("button", "btn btn-primary", uiT("ops_cost_run", "Run"));
      go.type = "button";
      actions.appendChild(cancel);
      actions.appendChild(go);
      box.appendChild(actions);
      overlay.appendChild(box);
      function close(ok) {
        document.removeEventListener("keydown", onKey);
        overlay.remove();
        resolve(ok);
      }
      function onKey(e) { if (e.key === "Escape") close(false); }
      cancel.addEventListener("click", function () { close(false); });
      go.addEventListener("click", function () { close(true); });
      overlay.addEventListener("click", function (e) { if (e.target === overlay) close(false); });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(overlay);
      go.focus();
    });
  }

  function paintForm() {
    var spec = commands[current] || { fields: [] };
    paintHeader();
    form.replaceChildren();
    dryCheck.checked = false;

    if (spec.kind === "file-export") {
      paintLocaleChips([]);
      paintExport();
      showLogFor(current);
      return;
    }
    if (spec.kind === "file-import") {
      paintLocaleChips([]);
      paintImport();
      showLogFor(current);
      return;
    }

    var fields = (spec.fields || []).filter(function (field) {
      return field.name !== "project" && field.name !== "config";
    });
    var byName = {};
    fields.forEach(function (field) { byName[field.name] = field; });

    var hasLocales = !!byName.locales;
    var hasNamespace = !!byName.namespace;
    if (hasLocales) paintLocaleChips([]);
    if (hasNamespace) paintNamespaceSelect(byName.namespace);

    var primaryNames = PRIMARY[current] || [];
    var used = { locales: true, namespace: true, namespaces: true, dry_run: true };
    if (ENGINE_CMDS[String(current).replace(/^run-/, "")]) {
      // The run-only engine is a select fed by the engine op, not the free-text argparse field.
      used.engine = true;
      paintEngineSelect();
    }
    primaryNames.forEach(function (name) {
      var field = byName[name];
      if (!field) return;
      used[name] = true;
      if (field.type === "bool") paintBoolField(field);
      else paintLabeledField(field);
    });

    var advanced = fields.filter(function (field) {
      return !used[field.name];
    });
    if (advanced.length) {
      var details = document.createElement("details");
      details.className = "op-advanced";
      details.appendChild(el("summary", "", uiT("pc_adv_title", "Advanced")));
      var advBody = el("div", "op-advanced-body");
      advanced.forEach(function (field) {
        if (field.type === "bool") {
          var lab = el("label", "op-check");
          lab.appendChild(makeInput(field));
          lab.appendChild(document.createTextNode(" " + friendlyLabel(field.name)));
          advBody.appendChild(lab);
        } else {
          var wrap = el("div", "op-field");
          wrap.appendChild(el("span", "field-label", friendlyLabel(field.name)));
          wrap.appendChild(makeInput(field));
          advBody.appendChild(wrap);
        }
      });
      details.appendChild(advBody);
      form.appendChild(details);
    }
    showLogFor(current);
  }

  function readLocales() {
    var chips = form.querySelectorAll("[data-locale-chip]");
    if (chips.length) {
      var out = [];
      chips.forEach(function (box) {
        if (box.checked) out.push(box.value);
      });
      return out;
    }
    return null;
  }

  function readBody() {
    var payload = { project: project() };
    var spec = commands[current] || {};
    if (spec.kind === "file-export") {
      payload.format = document.getElementById("op-format").value;
      payload.layout = document.getElementById("op-layout").value;
      var onlyEl = document.getElementById("op-only");
      if (onlyEl) payload.only = onlyEl.value;
      var shotEl = document.getElementById("op-screenshots");
      if (shotEl) payload.screenshots = !!shotEl.checked;
      var apprEl = document.getElementById("op-approved-only");
      if (apprEl) payload.approved_only = !!apprEl.checked;
      var locs = readLocales();
      if (locs && locs.length) payload.locales = locs;
      return payload;
    }
    form.querySelectorAll("[data-field]").forEach(function (input) {
      var name = input.dataset.field;
      if (input.dataset.type === "bool") payload[name] = input.checked;
      else if (input.value !== "") payload[name] = input.value;
    });
    var chipLocales = readLocales();
    if (chipLocales) {
      if (chipLocales.length) payload.locales = chipLocales;
      else delete payload.locales;
    } else if (payload.locales && typeof payload.locales === "string") {
      payload.locales = payload.locales.split(",").map(function (part) { return part.trim(); }).filter(Boolean);
    }
    if (payload.keys && typeof payload.keys === "string") {
      payload.keys = payload.keys.split(",").map(function (part) { return part.trim(); }).filter(Boolean);
    }
    if (payload.namespace === "") delete payload.namespace;
    return payload;
  }

  function readStream(response, cmdName) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var pending = "";
    function pump() {
      return reader.read().then(function (chunk) {
        if (chunk.done) return;
        pending += decoder.decode(chunk.value, { stream: true });
        var parts = pending.split("\n\n");
        pending = parts.pop();
        parts.forEach(function (part) {
          var line = part.replace(/^data: /, "");
          if (!line) return;
          try {
            var event = JSON.parse(line);
            if (event.line) appendLog(event.line, cmdName);
            if (event.summary) appendLog(event.summary, cmdName);
          } catch (err) {
            appendLog(line, cmdName);
          }
        });
        return pump();
      });
    }
    return pump();
  }

  function modeNote(mode) {
    var map = {
      manual: uiT(
        "op_mode_manual",
        "manual mode: accepting records your choice; run apply to write the keys.",
      ),
      request: uiT(
        "op_mode_request",
        "request mode: accepting opens a review ticket; closing it adds the key.",
      ),
      auto: uiT(
        "op_mode_auto",
        "auto mode: accepting adds the key and queues translation now.",
      ),
    };
    return map[mode] || "";
  }

  function decide(payload) {
    var body = Object.assign({ project: project() }, payload || {});
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost("/api/ops/scan-decide", body);
    return fetch("/api/ops/scan-decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (response) { return response.json(); });
  }

  function hitsPanel(hits, mode) {
    var panel = el("div", "hits-panel");
    var bar = el("div", "hits-filter");
    var table = el("div", "hits-table");
    var level = "high";
    var canDecide = roleAllowed(commands["scan-decide"]);
    var note = el("div", "log-line-dim", modeNote(mode));
    var status = el("div", "hits-status");

    function apply(action, chosen) {
      var ids = chosen.map(function (h) { return h.id; });
      if (!ids.length) return;
      decide({ action: action, ids: ids }).then(function (data) {
        status.textContent = data.summary || data.error || "";
        if (!data.ok) return;
        var applied = data.data && data.data.applied ? "applied" : "accepted";
        chosen.forEach(function (h) {
          h.decision = action === "reset" ? null : (action === "accept" ? applied : "ignored");
        });
        paint();
      }).catch(function (err) { status.textContent = String(err); });
    }

    function button(label, handler) {
      var btn = el("button", "btn hit-btn", label);
      btn.type = "button";
      btn.addEventListener("click", handler);
      return btn;
    }

    function paint() {
      table.replaceChildren();
      var shown = hits.filter(function (h) { return (h.confidence || "medium") === level; });
      var pending = shown.filter(function (h) { return !h.decision; });
      if (canDecide && pending.length) {
        var bulk = el("div", "hits-bulk");
        bulk.appendChild(button(
          uiT("op_accept_n_shown", "Accept {n} shown").replace("{n}", String(pending.length)),
          function () { apply("accept", pending); },
        ));
        bulk.appendChild(button(
          uiT("op_ignore_n_shown", "Ignore {n} shown").replace("{n}", String(pending.length)),
          function () { apply("ignore", pending); },
        ));
        table.appendChild(bulk);
      }
      if (!shown.length) {
        table.appendChild(el(
          "div", "log-line-dim",
          uiT("op_no_confidence", "No {level} confidence findings.")
            .replace("{level}", level),
        ));
      }
      shown.slice(0, 200).forEach(function (h) {
        var row = el("div", "hit-row" + (h.decision === "ignored" ? " hit-ignored" : ""));
        row.appendChild(el("span", "hit-loc", h.file + ":" + h.line));
        row.appendChild(el("span", "hit-text", JSON.stringify(h.text)));
        if (h.existing_key) {
          row.appendChild(el(
            "span", "hit-reuse",
            uiT("op_reuse_key", "reuse {key}").replace("{key}", h.existing_key),
          ));
        }
        if (h.decision) row.appendChild(el("span", "hit-badge hit-" + h.decision, h.decision));
        if (canDecide && h.id) {
          if (!h.decision || h.decision === "ignored") {
            row.appendChild(button(uiT("op_accept", "Accept"), function () { apply("accept", [h]); }));
          }
          if (!h.decision) {
            row.appendChild(button(uiT("op_ignore", "Ignore"), function () { apply("ignore", [h]); }));
          }
          if (h.decision === "accepted" || h.decision === "ignored") {
            row.appendChild(button(uiT("op_undo", "Undo"), function () { apply("reset", [h]); }));
          }
        }
        table.appendChild(row);
      });
    }
    ["high", "medium", "low"].forEach(function (name) {
      var count = hits.filter(function (h) { return (h.confidence || "medium") === name; }).length;
      var btn = el("button", "btn", name + " (" + count + ")");
      btn.type = "button";
      btn.addEventListener("click", function () { level = name; paint(); });
      bar.appendChild(btn);
    });
    if (canDecide) {
      var toggle = button(uiT("op_show_ignored", "Show ignored"), function () {
        fetch("/api/ops/agent-hardcoded", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ format: "json", show_ignored: true, catalogue_audit: false }),
        }).then(function (r) { return r.json(); }).then(function (data) {
          var next = data.data && data.data.hits;
          if (!next) return;
          hits.length = 0;
          next.forEach(function (h) { hits.push(h); });
          toggle.hidden = true;
          paint();
        });
      });
      bar.appendChild(toggle);
    }
    panel.appendChild(bar);
    if (canDecide && note.textContent) panel.appendChild(note);
    panel.appendChild(status);
    panel.appendChild(table);
    paint();
    return panel;
  }

  function postJson(url, payload, cmdName) {
    var name = cmdName || current;
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(payload),
      signal: abort ? abort.signal : undefined,
    }).then(function (response) {
      var type = response.headers.get("Content-Type") || "";
      if (type.indexOf("text/event-stream") >= 0 && response.body) {
        return readStream(response, name);
      }
      return response.json().then(function (data) {
        appendLog(data.summary || data.error || JSON.stringify(data), name);
        if (data.data && data.data.hits && data.data.hits.length && name === current) {
          logBody.appendChild(hitsPanel(data.data.hits, data.data.applyMode));
          logBody.scrollTop = logBody.scrollHeight;
        }
        if (data.file_base64) download(data);
      });
    });
  }

  function download(data) {
    var binary = atob(data.file_base64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    var link = el("a", "", data.filename || "export");
    link.href = URL.createObjectURL(new Blob([bytes], { type: data.content_type }));
    link.download = data.filename || "export";
    link.click();
  }

  function runNow(dry, submit) {
    var runCmd = current;
    var spec = commands[runCmd] || {};
    var payload = readBody();
    var wantDry = !!dry || (!!dryCheck.checked && !submit);
    payload.dry_run = wantDry;
    payload.submit = !!submit && !wantDry;
    // Align with apply/bulk-clear: inline LLM runs need an explicit confirm.
    if (!wantDry && !payload.submit) payload.confirm = true;
    if (runCmd === "sync" && payload.submit) {
      payload.submit_translate = true;
    }
    clearLog(runCmd);
    setLogStatus(
      wantDry
        ? uiT("op_dry_output", "Dry run output")
        : (submit ? uiT("op_tq_output", "Taskqueue output") : uiT("op_output", "Output")),
      runCmd,
    );
    ensureLog(runCmd).visible = true;
    bumpUsage(runCmd);
    paintCarousel();
    stopBtn.hidden = false;
    abort = new AbortController();
    stopBtn.onclick = function () { if (abort) abort.abort(); };
    var done = function () { stopBtn.hidden = true; };
    if (spec.kind === "file-export") {
      return postJson("/api/export", payload, runCmd).catch(function (err) {
        showErr(err, runCmd);
      }).then(done);
    }
    if (spec.kind === "file-import") return runImport(payload, runCmd).then(done);
    if (spec.stream) payload.stream = true;
    return postJson("/api/ops/" + runCmd, payload, runCmd).catch(function (err) {
      showErr(err, runCmd);
    }).then(done);
  }

  function showErr(err, cmdName) {
    appendLog(String(err && err.message ? err.message : err), cmdName);
  }

  function runImport(payload, cmdName) {
    var name = cmdName || current;
    var files = document.getElementById("op-import-files").files;
    if (!files || !files.length) {
      appendLog(uiT("op_select_locale_file", "Select at least one locale file."), name);
      return Promise.resolve();
    }
    return new Promise(function (resolve) {
      var reader = new FileReader();
      reader.onload = function () {
        var fname = files[0].name || "";
        var fmt = fname.endsWith(".json") ? "json" : (fname.endsWith(".xliff") || fname.endsWith(".xlf") ? "xliff" : "csv");
        var body = {
          project: project(),
          format: fmt,
          dry_run: payload.dry_run,
          model: (document.getElementById("op-localized-by") || {}).value || "import",
        };
        if (/\.xlsx$/i.test(fname)) {
          var bytes = new Uint8Array(reader.result), bin = "";
          for (var i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
          body = { project: project(), format: "csv", dry_run: payload.dry_run, filename: fname, xlsx_base64: btoa(bin),
            model: body.model };
        } else {
          body[fmt === "xliff" ? "xliff" : fmt] = String(reader.result || "");
        }
        postJson("/api/import", body, name).catch(function (err) {
          showErr(err, name);
        }).then(resolve);
      };
      if (/\.xlsx$/i.test(files[0].name || "")) reader.readAsArrayBuffer(files[0]);
      else reader.readAsText(files[0]);
    });
  }

  function guarded(dry, submit) {
    var spec = commands[current] || {};
    if (dry || !requiresLlm(spec)) return runNow(dry, submit);
    var payload = readBody();
    var runCmd = current;
    var estimateBody = {
      project: project(),
      locales: payload.locales,
      keys: payload.keys,
      namespace: payload.namespace,
      namespaces: payload.namespaces,
      // Review and rescore are priced as judge/BT calls, not as translation (ops.js does the same).
      purpose: (runCmd === "review" || runCmd === "rescore") ? runCmd : "translate",
    };
    // The estimate prices the engine picked for this run (dispatch_op reloads the config with it).
    if (payload.engine) estimateBody.engine = payload.engine;
    var estimateP = (window.LLMApi && LLMApi.apiPost)
      ? LLMApi.apiPost("/api/ops/estimate-cost", estimateBody)
      : fetch("/api/ops/estimate-cost", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(estimateBody),
        }).then(function (response) { return response.json(); });
    return estimateP.then(function (data) {
      if (!data || data.ok === false) {
        showErr((data && (data.error || data.summary)) || "cost estimate failed", runCmd);
        return;
      }
      var est = (data && data.data) || {};
      if (est.local !== false) return runNow(dry, submit);
      var line = uiT("ops_cost_confirm", "This run calls a paid cloud model.") + " " +
        uiT("ops_cost_estimate", "Estimated") + ": $" + est.batch_usd + " (" + uiT("ops_cost_max", "at most") + " $" +
        est.max_usd + "), " + uiT("ops_cost_remaining", "budget left") + ": $" + est.remaining_usd + ". " +
        uiT("ops_cost_continue", "Continue?");
      appendLog(line, runCmd);
      return costModal(est, runCmd, payload.engine).then(function (ok) {
        if (!ok) {
          appendLog(uiT("ops_cost_cancelled", "Cancelled."), runCmd);
          return;
        }
        return runNow(dry, submit);
      });
    }).catch(function (err) { showErr(err, runCmd); });
  }

  dryBtn.addEventListener("click", function () { guarded(true, false); });
  runBtn.addEventListener("click", function () { guarded(false, false); });
  submitBtn.addEventListener("click", function () { guarded(false, true); });

  function loadProjectMeta() {
    var name = project();
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/overview-lite", { project: name })
      : Promise.reject(new Error("LLMApi missing"));
    return get.then(function (data) {
      var active = (data && data.activeLocales) || [];
      var frozen = (data && data.frozenLocales) || [];
      projectLocales = active.concat(frozen.filter(function (code) {
        return active.indexOf(code) < 0;
      }));
      projectFrozen = frozen.slice();
      projectNamespaces = ((data && data.namespaces) || []).map(function (row) {
        return typeof row === "string" ? row : row.name;
      }).filter(Boolean);
    }).catch(function () {
      projectLocales = [];
      projectFrozen = [];
      projectNamespaces = [];
    });
  }

  function loadModels() {
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/models", { project: project() })
      : Promise.reject(new Error("LLMApi missing"));
    return get.then(function (data) {
      var names = (data && data.models) || [];
      models.textContent = names.length
        ? (uiT("op_models_prefix", "Installed models:") + " " + names.join(", "))
        : (uiT("op_models_prefix", "Installed models:") + " " + ((data && data.error) || uiT("op_models_none", "none")));
    }).catch(function () {
      models.textContent = uiT("op_models_unavailable", "Installed models: unavailable");
    });
  }

  function loadUsageCounts() {
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/usage", { runs_only: "1", project: project() })
      : Promise.reject(new Error("LLMApi missing"));
    return get.then(function (data) {
      serverCounts = {};
      ((data && data.runs) || []).forEach(function (run) {
        var cmd = run && run.command;
        if (!cmd) return;
        // Inline run-* variants count toward the queued sibling when present.
        var key = cmd;
        if (key.indexOf("run-") === 0 && commands[key.slice(4)]) key = key.slice(4);
        serverCounts[key] = (serverCounts[key] || 0) + 1;
        if (key !== cmd) serverCounts[cmd] = (serverCounts[cmd] || 0) + 1;
      });
    }).catch(function () {
      serverCounts = {};
    });
  }

  function applyCommands(payload) {
    payload = payload || {};
    commands = payload.commands || {};
    Object.keys(commands).forEach(function (name) {
      // Stale servers still emit the pre-rename group label.
      if (commands[name].group === "LLM") commands[name].group = "LLM Pipeline";
    });
    if (payload.groups && payload.groups.length) {
      groups = payload.groups.map(function (g) {
        return g === "LLM" ? "LLM Pipeline" : g;
      });
    }
    if (payload.group_order && payload.group_order.LLM && !payload.group_order["LLM Pipeline"]) {
      payload.group_order["LLM Pipeline"] = payload.group_order.LLM;
    }
    groupOrder = payload.group_order || {};
    var params = new URLSearchParams(window.location.search);
    var wanted = params.get("command");
    if (wanted && commands[wanted]) current = wanted;
    else if (commands.validate) current = "validate";
    else current = orderedCommands()[0] || "";
    paintCarousel();
    paintForm();
  }

  function refreshProjectExtras() {
    return loadProjectMeta().then(function () {
      return loadUsageCounts();
    }).then(function () {
      paintCarousel();
      paintForm();
    });
  }

  function relabelChrome() {
    optionsLabel.textContent = uiT("op_options", "Options");
    dryCheckText.textContent = " " + uiT(
      "op_dry_check",
      "Dry run — print what would happen, write nothing",
    );
    runBtn.textContent = uiT("op_run", "▶ Run");
    submitBtn.textContent = uiT("op_submit_tq", "Submit to taskqueue");
    dryBtn.textContent = uiT("wf_run_dry", "Dry run");
    stopBtn.textContent = uiT("wf_blk_stop", "Stop");
    prevBtn.setAttribute("aria-label", uiT("op_scroll_up", "Scroll commands up"));
    nextBtn.setAttribute("aria-label", uiT("op_scroll_down", "Scroll commands down"));
    wfPageLink.textContent = uiT("op_workflows", "Workflows");
    wfPageLink.title = uiT(
      "op_workflows_tip",
      "Edit and run locale workflows on the Workflow page",
    );
    permLink.textContent = uiT("op_permissions", "⚙ Permissions");
    clearBtn.textContent = uiT("ed_clear", "Clear");
    if (!current) {
      desc.textContent = uiT("op_loading_commands", "Loading commands.");
    }
    if (logEmpty.parentNode === logBody && logBody.childNodes.length === 1) {
      logEmpty.textContent = uiT(
        "op_output_empty",
        "Output appears here after you run an operation.",
      );
    }
    if (!logsByCmd[current] || !(logsByCmd[current].lines || []).length) {
      logStatus.textContent = uiT("op_output", "Output");
    }
  }

  // Interactive after /api/commands only; usage/models/meta fill in after.
  function boot() {
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/commands", {})
      : Promise.reject(new Error("LLMApi missing"));
    return get
      .then(applyCommands)
      .then(function () {
        if (window.LLMApi && LLMApi.onProjectReady) {
          LLMApi.onProjectReady(function () {
            refreshProjectExtras();
            loadModels();
          });
        } else if (project()) {
          refreshProjectExtras();
          loadModels();
        }
      });
  }

  var ready = (window.uiLocale && typeof window.uiLocale.whenReady === "function")
    ? window.uiLocale.whenReady()
    : Promise.resolve();
  ready.then(function () {
    relabelChrome();
    boot();
  });
})();
