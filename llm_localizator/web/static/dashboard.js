(function () {
  var body = document.getElementById("page-body");
  var select = document.getElementById("project-select");
  if (!body || !select) return;

  var displayNames = null;
  try {
    displayNames = new Intl.DisplayNames(["en"], { type: "language" });
  } catch (err) {
    displayNames = null;
  }

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function headers() {
    if (window.LLMApi && LLMApi.authHeaders) return LLMApi.authHeaders();
    var out = { "Content-Type": "application/json" };
    if (window.__LLM_TOKEN) out["X-LLM-Token"] = window.__LLM_TOKEN;
    return out;
  }

  function post(url, payload) {
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost(url, payload);
    return fetch(url, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(payload),
    }).then(function (response) { return response.json(); });
  }

  function apiGet(path, query) {
    if (window.LLMApi && LLMApi.apiGet) {
      return LLMApi.apiGet(path, Object.assign({ project: select.value }, query || {}));
    }
    var q = Object.assign({ project: select.value }, query || {});
    var qs = Object.keys(q).filter(function (k) { return q[k] != null && q[k] !== ""; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(q[k]); })
      .join("&");
    return fetch(path + (qs ? "?" + qs : ""), { headers: headers() })
      .then(function (response) { return response.json(); });
  }

  var dashScope = window.LLMApi && LLMApi.requestScope
    ? LLMApi.requestScope()
    : null;

  function localeName(code) {
    if (!code) return "";
    if (!displayNames) return code;
    try {
      return displayNames.of(code) || code;
    } catch (err) {
      return code;
    }
  }

  function relativeTime(iso) {
    if (!iso) return uiT("time_never", "never");
    var then = Date.parse(iso);
    if (!isFinite(then)) return iso;
    var sec = Math.round((Date.now() - then) / 1000);
    if (sec < 0) sec = 0;
    if (sec < 60) {
      return uiT("time_s_ago", "{n}s ago").replace("{n}", String(sec));
    }
    if (sec < 3600) {
      return uiT("time_m_ago", "{n}m ago").replace("{n}", String(Math.floor(sec / 60)));
    }
    if (sec < 86400) {
      return uiT("time_h_ago", "{n}h ago").replace("{n}", String(Math.floor(sec / 3600)));
    }
    return uiT("time_d_ago", "{n}d ago").replace("{n}", String(Math.floor(sec / 86400)));
  }

  function activityLabel(run) {
    var cmd = (run.command || "").toLowerCase();
    var keys = run.keys != null ? run.keys : 0;
    if (cmd === "translate") {
      return uiT("dash_act_translate", "Translated {n} keys").replace("{n}", String(keys));
    }
    if (cmd === "improve") {
      return uiT("dash_act_improve", "Improved {n} keys").replace("{n}", String(keys));
    }
    if (cmd === "review") {
      return uiT("dash_act_review", "Review pass: {n} keys scored").replace("{n}", String(keys));
    }
    if (cmd === "rescore") {
      return uiT("dash_act_rescore", "Rescored {n} keys").replace("{n}", String(keys));
    }
    if (cmd === "import") {
      return uiT("dash_act_import", "Import: {n} strings").replace("{n}", String(keys));
    }
    if (cmd === "validate") return uiT("dash_act_validate", "Validated catalogues");
    if (cmd === "export") return uiT("dash_act_export", "Exported handoff");
    return (run.command || uiT("dash_act_run", "run")) + (keys ? " (" + keys + ")" : "");
  }

  function setReviewBadge(count) {
    var badge = document.getElementById("review-badge");
    if (!badge) return;
    if (count > 0) {
      badge.hidden = false;
      badge.textContent = String(count);
    } else {
      badge.hidden = true;
      badge.textContent = "";
    }
  }

  var loadGen = 0;

  function setText(id, text) {
    var node = document.getElementById(id);
    if (node) node.textContent = text;
  }

  function guideAction(step, project) {
    if (step.id === "languages" || step.id === "model") {
      var setup = el("a", "btn btn-primary", step.id === "languages"
        ? uiT("dash_choose_languages", "Choose languages")
        : uiT("dash_pick_model", "Pick a model"));
      setup.href = "/setup";
      return setup;
    }
    if (step.id === "translate") {
      var run = el("button", "btn btn-primary", uiT("dash_run_translation", "Run translation"));
      run.type = "button";
      run.addEventListener("click", function () {
        run.disabled = true;
        run.textContent = uiT("dash_starting", "Starting…");
        post("/api/ops/run-translate", { project: project })
          .then(function (data) {
            if (!data.ok) {
              run.textContent = data.error || data.summary || uiT("dash_could_not_start", "Could not start");
              return;
            }
            var queued = data.submitted || data.queued
              || (data.summary && /queue|submitted|enqueued/i.test(String(data.summary)));
            run.textContent = queued
              ? uiT("dash_queued_ops", "Queued — watch Ops / taskqueue")
              : (data.summary || uiT("dash_started", "Started"));
            load(project);
          })
          .catch(function () { run.textContent = uiT("dash_request_failed", "Request failed"); })
          .finally(function () { run.disabled = false; });
      });
      return run;
    }
    if (step.id === "approach" && step.status !== "done") {
      // W6: record the choice here (approach op, Admin) instead of printing the CLI line.
      var vars = step.detail_vars || {};
      var ids = String(vars.approaches || "local,cloud,agent,human,hybrid").split(",").filter(Boolean);
      var box = el("div", "dash-approach");
      var pick = el("select", "dash-approach-select");
      pick.setAttribute("aria-label", uiT("dash_approach_label", "Approach"));
      ids.forEach(function (id) {
        var title = uiT("guide_approach_" + id + "_title", vars["approach_" + id + "_title"] || id);
        var opt = el("option", "", title + (id === vars.rec ? " (" + uiT("dash_recommended", "recommended") + ")" : ""));
        opt.value = id;
        if (id === vars.rec) opt.selected = true;
        pick.appendChild(opt);
      });
      var use = el("button", "btn btn-primary dash-approach-use", uiT("dash_use_approach", "Use this approach"));
      use.type = "button";
      var note = el("span", "field-hint dash-approach-note", "");
      use.addEventListener("click", function () {
        use.disabled = true;
        post("/api/ops/approach", { project: project, set_to: pick.value })
          .then(function (data) {
            if (!data || data.ok === false) {
              note.textContent = (data && (data.error || data.summary)) || uiT("dash_could_not_start", "Could not start");
              use.disabled = false;
              return;
            }
            load(project);
          })
          .catch(function () {
            note.textContent = uiT("dash_request_failed", "Request failed");
            use.disabled = false;
          });
      });
      box.appendChild(pick);
      box.appendChild(use);
      box.appendChild(note);
      return box;
    }
    if (step.id === "review") {
      var open = el("a", "btn btn-primary", uiT("dash_open_the_editor", "Open the editor"));
      open.href = "/app/editor";
      return open;
    }
    return null;
  }

  function formatGuideDetail(step) {
    var text = step.detail_key
      ? uiT(step.detail_key, step.detail || step.detail_key)
      : (step.detail || "");
    var vars = Object.assign({}, step.detail_vars || {});
    if (vars.approaches) {
      // The server sends English option text; rebuild each line from catalogue keys.
      var line = uiT("guide_approach_option", "- {id}: {title} - {words}; {cost}.");
      vars.options = vars.approaches.split(",").map(function (id) {
        var part = function (field) {
          return uiT("guide_approach_" + id + "_" + field, vars["approach_" + id + "_" + field] || "");
        };
        return line.split("{id}").join(id).split("{title}").join(part("title"))
          .split("{words}").join(part("words")).split("{cost}").join(part("cost"));
      }).join("\n");
    }
    if (vars.reason_key) vars.reason = uiT(vars.reason_key, vars.reason || "");
    Object.keys(vars).forEach(function (k) {
      text = text.split("{" + k + "}").join(String(vars[k]));
    });
    return text;
  }

  function guideCard(project, data) {
    var frag = document.createDocumentFragment();
    if (!data || !data.steps || data.next == null) return frag;
    var card = el("div", "dash-section guide-card");
    var head = el("div", "dash-section-row guide-head");
    head.appendChild(el("div", "dash-section-label", uiT("dash_getting_started", "Getting started")));
    head.appendChild(el("span", "guide-progress",
      uiT("dash_guide_progress", "{done} of {total} steps")
        .replace("{done}", String(data.done))
        .replace("{total}", String(data.total))));
    card.appendChild(head);
    var list = el("ol", "guide-steps");
    data.steps.forEach(function (step) {
      if (!step.required) return;
      var isNext = step.id === data.next;
      var item = el("li", "guide-step" + (step.status === "done" ? " is-done" : "") + (isNext ? " is-next" : ""));
      item.appendChild(el("span", "guide-mark", step.status === "done" ? "✓" : "○"));
      var text = el("div", "guide-text");
      text.appendChild(el("div", "guide-title",
        uiT("guide_" + step.id, step.title || step.id)));
      if (isNext) {
        text.appendChild(el("div", "guide-detail", formatGuideDetail(step)));
        var action = guideAction(step, project);
        if (action) text.appendChild(action);
        if (step.cli) {
          var hint = el("div", "guide-cli-row");
          hint.appendChild(el("span", "guide-cli-label", uiT("dash_or_terminal", "or in a terminal: ")));
          hint.appendChild(el("code", "guide-cli", step.cli));
          text.appendChild(hint);
        }
      }
      item.appendChild(text);
      list.appendChild(item);
    });
    card.appendChild(list);
    frag.appendChild(card);
    return frag;
  }

  function loadGuide(project) {
    var host = document.getElementById("dash-guide");
    if (!host) return;
    post("/api/ops/guide", {
      project: project,
      skip_provider: true,
      skip_validate: true,
    })
      .then(function (result) { host.replaceChildren(guideCard(project, result && result.data)); })
      .catch(function () { host.replaceChildren(); });
  }

  function sectionMessage(label, message) {
    var wrap = el("div", "dash-section");
    wrap.appendChild(el("div", "dash-section-label", label));
    wrap.appendChild(el("p", "empty-state", message));
    return wrap;
  }

  function load(project) {
    var gen = ++loadGen;
    var query = "project=" + encodeURIComponent(project);
    ensureFrame();
    var title = document.getElementById("dash-title");
    var sub = document.getElementById("dash-sub");
    if (title) title.textContent = project || uiT("dash_title", "Dashboard");
    if (sub) sub.textContent = uiT("dash_loading", "Loading…");
    setText("dash-count-coverage", "…");
    setText("dash-count-pending", "…");
    setText("dash-count-quality", "—");
    var panel = document.getElementById("dash-locales");
    if (panel) panel.replaceChildren(el("p", "empty-state", uiT("dash_loading_coverage", "Loading coverage…")));
    var actions = document.getElementById("dash-actions");
    if (actions) actions.replaceChildren(quickActions(project, {}, {}));
    var activity = document.getElementById("dash-activity");
    if (activity) activity.replaceChildren(sectionMessage(
      uiT("dash_recent_activity", "Recent activity"),
      uiT("dash_loading_activity", "Loading activity…")));
    var quality = document.getElementById("dash-quality");
    if (quality) quality.replaceChildren(sectionMessage(
      uiT("dash_quality_dist", "Quality distribution"),
      uiT("dash_loading_quality", "Loading quality…")));
    loadGuide(project);

    function afterCore(lite, stats) {
      if (gen !== loadGen) return;
      currentLite = lite || {};
      currentProject = project || "";
      applyLite(project, currentLite);
      applyStats(project, currentLite, stats || {});
      loadExtras(project);
      loadWorkflowSummary(project);
      return apiGet("/api/progress", { project: project || "" }).then(function (progress) {
        if (gen !== loadGen || !progress) return;
        if (progress.error && progress.ok === false) {
          var panel = document.getElementById("dash-locales");
          if (panel) {
            panel.appendChild(el("p", "empty-state is-error",
              uiT("dash_progress_unavailable", "Progress unavailable: {err}")
                .replace("{err}", progress.error || "error")));
          }
          return;
        }
        applyProgress(progress);
      });
    }

    apiGet("/api/dashboard", { project: project }).then(function (dash) {
      if (gen !== loadGen) return null;
      if (dash && dash.ok && dash.lite) {
        if (dash.review && typeof dash.review.active === "number") {
          setReviewBadge(dash.review.active);
        }
        return afterCore(dash.lite, dash.stats || {});
      }
      // Fallback for older servers: parallel lite + stats.
      return Promise.all([
        apiGet("/api/overview-lite", { project: project }),
        apiGet("/api/overview-stats", { project: project }),
      ]).then(function (parts) {
        return afterCore(parts[0], parts[1]);
      });
    }).catch(function (err) {
      if (gen !== loadGen) return;
      var msg = String((err && err.message) || err || uiT("dash_load_failed", "Could not load dashboard"));
      body.replaceChildren(el("p", "empty-state is-error", msg));
      var retry = el("button", "btn", uiT("dash_retry", "Retry"));
      retry.type = "button";
      retry.addEventListener("click", function () { load(project); });
      body.appendChild(retry);
    });
  }

  function paintHead(project, lite, stats) {
    var title = document.getElementById("dash-title");
    var sub = document.getElementById("dash-sub");
    if (title) title.textContent = project || lite.project || uiT("dash_title", "Dashboard");
    if (!sub) return;
    var locales = (lite.activeLocales || []).concat(lite.frozenLocales || []);
    var nLoc = locales.length;
    var parts = [
      uiT("dash_source_strings", "{n} source strings")
        .replace("{n}", (lite.sourceTotal || 0).toLocaleString()),
      nLoc === 1
        ? uiT("dash_target_locale_one", "{n} target locale").replace("{n}", "1")
        : uiT("dash_target_locales", "{n} target locales").replace("{n}", String(nLoc)),
    ];
    var last = stats && stats.lastRunAt;
    parts.push(last
      ? uiT("dash_last_run", "last run {when}").replace("{when}", relativeTime(last))
      : uiT("dash_no_runs_yet", "no runs yet"));
    sub.textContent = parts.join(" · ");
  }

  function count(label, value, sub, opts) {
    opts = opts || {};
    var node = el("div", "count");
    node.appendChild(el("span", "count-kicker", label));
    var strong = el("strong", opts.accent ? "is-accent" : "", value);
    if (opts.valueId) strong.id = opts.valueId;
    node.appendChild(strong);
    if (sub) {
      if (opts.linkHref) {
        var link = el("a", "count-sub-link", sub);
        link.href = opts.linkHref;
        if (opts.subId) link.id = opts.subId;
        node.appendChild(link);
      } else {
        var span = el("span", "count-sub", sub);
        if (opts.subId) span.id = opts.subId;
        node.appendChild(span);
      }
    }
    return node;
  }

  var wfSummary = null;

  function workflowLine(locale) {
    var info = wfSummary && wfSummary.locales && wfSummary.locales[locale];
    var node = el("div", "locale-workflow");
    node.setAttribute("data-locale", locale);
    fillWorkflowLine(node, info);
    return node;
  }

  function fillWorkflowLine(node, info) {
    node.replaceChildren();
    if (!info) return;
    node.appendChild(document.createTextNode(uiT("ed_workflow", "Workflow:") + " "));
    var link = el("a", "", info.workflow || uiT("ed_wf_none", "none"));
    link.href = "/app/workflow";
    node.appendChild(link);
    if (!info.workflow) return;
    var state = info.run && info.run.status && info.run.status !== "done"
      ? info.run.status
      : (info.lastRun
        ? uiT("dash_last_run", "last run {when}").replace(
          "{when}",
          relativeTime(info.lastRun.at || info.lastRun.finished || info.lastRun.ts),
        )
        : uiT("dash_never_run", "never run"));
    node.appendChild(document.createTextNode(" · " + state));
  }

  function loadWorkflowSummary(project) {
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/workflow/summary", { project: project || "" })
      : Promise.reject(new Error("LLMApi missing"));
    get.then(function (data) {
        if (!data || data.ok === false) return;
        wfSummary = data;
        document.querySelectorAll(".locale-workflow").forEach(function (node) {
          fillWorkflowLine(node, (data.locales || {})[node.getAttribute("data-locale")]);
        });
      })
      .catch(function () {});
  }

  function bar(row) {
    var wrap = el("div", "locale-row");
    var top = el("div", "locale-row-top");
    var left = el("div", "locale-row-id");
    left.appendChild(el("span", "locale-code", row.locale));
    var nameWrap = el("span", "locale-name");
    nameWrap.appendChild(document.createTextNode(localeName(row.locale)));
    if (row.frozen) {
      nameWrap.appendChild(el("span", "frozen-badge", uiT("dash_frozen", "frozen")));
    }
    left.appendChild(nameWrap);
    top.appendChild(left);

    var right = el("div", "locale-row-meta");
    var total = row.total != null ? row.total : (
      (row.translated || 0) + (row.stale || 0) + (row.missing || 0)
    );
    right.appendChild(el(
      "span",
      "locale-frac",
      (row.translated || 0).toLocaleString() + " / " + total.toLocaleString(),
    ));
    var coverage = Number(row.coverage) || 0;
    right.appendChild(el("span", "locale-pct", Math.round(coverage) + "%"));
    var edit = el("a", "locale-edit", uiT("pc_edit", "Edit →"));
    edit.href = "/app/editor?locale=" + encodeURIComponent(row.locale);
    right.appendChild(edit);
    if (!row.frozen) {
      var translate = document.createElement("button");
      translate.className = "btn btn-tiny";
      translate.type = "button";
      translate.title = uiT("dash_translate_locale", "Translate {locale}").replace("{locale}", row.locale);
      translate.textContent = "▶";
      translate.addEventListener("click", function () {
        translate.disabled = true;
        post("/api/ops/translate", {
          project: select.value,
          locales: [row.locale],
        }).then(function (data) {
          translate.textContent = data.ok ? "✓" : "✗";
        }).catch(function () { translate.textContent = "✗"; });
      });
      right.appendChild(translate);
    }
    top.appendChild(right);
    wrap.appendChild(top);

    var track = el("div", "bar-track");
    var fill = el("div", "bar-fill");
    if (row.frozen) fill.classList.add("is-frozen");
    else if (coverage >= 80) fill.classList.add("is-high");
    else if (coverage < 50) fill.classList.add("is-low");
    fill.style.width = Math.max(0, Math.min(100, coverage)) + "%";
    track.appendChild(fill);
    wrap.appendChild(track);

    wrap.appendChild(workflowLine(row.locale));

    if (!row.frozen || row.stale || row.missing) {
      var dots = el("div", "status-dots");
      dots.appendChild(el("span", "dot is-done",
        uiT("dash_dot_done", "● {n} done").replace("{n}", (row.translated || 0).toLocaleString())));
      dots.appendChild(el("span", "dot is-stale",
        uiT("dash_dot_stale", "● {n} stale").replace("{n}", (row.stale || 0).toLocaleString())));
      dots.appendChild(el("span", "dot is-missing",
        uiT("dash_dot_missing", "● {n} missing").replace("{n}", (row.missing || 0).toLocaleString())));
      wrap.appendChild(dots);
    }
    return wrap;
  }

  function quickActions(project, lite, stats) {
    var wrap = el("div", "dash-section");
    wrap.appendChild(el("div", "dash-section-label", uiT("dash_quick_actions", "Quick actions")));
    var list = el("div", "quick-actions");
    var active = (lite.activeLocales || []).filter(Boolean);
    var run = el("button", "quick-action", "");
    run.type = "button";
    run.appendChild(el("span", "quick-icon", "⚡"));
    run.appendChild(document.createTextNode(
      uiT("dash_run_translation", "Run translation")
        + (active.length ? " — " + active.join(", ") : ""),
    ));
    run.disabled = !active.length;
    run.addEventListener("click", function () {
      run.disabled = true;
      post("/api/ops/translate", { project: project, locales: active })
        .then(function (data) {
          run.appendChild(el("span", "quick-status", data.ok ? " ✓" : " ✗"));
          if (data.ok) load(project);
        })
        .catch(function () {
          run.appendChild(el("span", "quick-status", " ✗"));
        })
        .finally(function () { run.disabled = !active.length; });
    });
    list.appendChild(run);

    var pending = (stats && stats.pendingReview) || 0;
    var review = el("a", "quick-action", "");
    review.href = "/app/review";
    review.appendChild(el("span", "quick-icon", "✓"));
    var reviewLabel = el(
      "span",
      "",
      pending
        ? uiT("dash_review_pending", "Review {n} pending strings").replace("{n}", String(pending))
        : uiT("dash_open_review_queue", "Open review queue"),
    );
    reviewLabel.id = "dash-review-label";
    review.appendChild(reviewLabel);
    list.appendChild(review);

    var exp = el("button", "quick-action", "");
    exp.type = "button";
    exp.appendChild(el("span", "quick-icon", "↓"));
    exp.appendChild(document.createTextNode(uiT("dash_export_csv", "Export handoff (CSV)")));
    exp.addEventListener("click", function () {
      exp.disabled = true;
      post("/api/export", {
        project: project,
        format: "csv",
        locales: (lite.activeLocales || []).concat(lite.frozenLocales || []),
      }).then(function (data) {
        if (!data.ok && data.error) throw new Error(data.error);
        if (!data.file_base64) return;
        var binary = atob(data.file_base64);
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        var link = document.createElement("a");
        link.href = URL.createObjectURL(new Blob([bytes], { type: data.content_type || "text/csv" }));
        link.download = data.filename || "handoff.csv";
        link.click();
      }).catch(function (err) {
        exp.appendChild(el("span", "quick-status", " " + String(err.message || err)));
      }).finally(function () { exp.disabled = false; });
    });
    list.appendChild(exp);

    var validate = el("button", "quick-action", "");
    validate.type = "button";
    validate.appendChild(el("span", "quick-icon", "⚠"));
    validate.appendChild(document.createTextNode(uiT("dash_validate_all", "Validate all locales")));
    validate.addEventListener("click", function () {
      validate.disabled = true;
      post("/api/ops/validate", {
        project: project,
        locales: (lite.activeLocales || []).concat(lite.frozenLocales || []),
        detail: "summary",
      }).then(function (data) {
        validate.appendChild(el("span", "quick-status", data.ok ? " ✓" : " ✗"));
      }).catch(function () {
        validate.appendChild(el("span", "quick-status", " ✗"));
      }).finally(function () { validate.disabled = false; });
    });
    list.appendChild(validate);

    wrap.appendChild(list);
    return wrap;
  }

  function activitySection(progress) {
    var wrap = el("div", "dash-section");
    wrap.appendChild(el("div", "dash-section-label", uiT("dash_recent_activity", "Recent activity")));
    var list = el("div", "activity-list");
    var runs = (progress && progress.runs) || [];
    if (!runs.length) {
      list.appendChild(el("p", "empty-state", uiT("dash_no_runs", "No runs yet.")));
    } else {
      runs.slice(0, 8).forEach(function (run) {
        var row = el("div", "activity-row");
        row.appendChild(el("span", "activity-time", relativeTime(run.at)));
        row.appendChild(el("span", "activity-text", activityLabel(run)));
        var locales = (run.locales || []).join(", ");
        if (locales) row.appendChild(el("span", "activity-locale", locales));
        list.appendChild(row);
      });
    }
    wrap.appendChild(list);
    return wrap;
  }

  function qualitySection(stats) {
    var wrap = el("div", "dash-section");
    var locale = (stats && stats.qualityLocale) || "";
    wrap.appendChild(el(
      "div",
      "dash-section-label",
      uiT("dash_quality_dist", "Quality distribution") + (locale ? " — " + locale : ""),
    ));
    var card = el("div", "quality-card");
    var bins = (stats && stats.qualityBins) || [];
    var total = bins.reduce(function (sum, n) { return sum + (Number(n) || 0); }, 0);
    if (!total) {
      card.appendChild(el("p", "empty-state", uiT("dash_no_quality", "No quality scores yet.")));
      wrap.appendChild(card);
      return wrap;
    }
    // Display high→low to match the mockup.
    var order = [5, 4, 3, 2, 1, 0];
    var colors = ["#68d391", "#68d391", "#f6e05e", "#f6e05e", "#fc8181", "#fc8181"];
    var hist = el("div", "quality-hist");
    order.forEach(function (idx, i) {
      var n = Number(bins[idx]) || 0;
      var bar = el("div", "quality-bar");
      bar.style.height = Math.max(8, Math.round((n / total) * 100)) + "%";
      bar.style.background = colors[i];
      bar.title = String(n);
      hist.appendChild(bar);
    });
    card.appendChild(hist);
    var axis = el("div", "quality-axis");
    ["0.5", "0.6", "0.7", "0.8", "0.9", "1.0"].forEach(function (label) {
      axis.appendChild(el("span", "", label));
    });
    card.appendChild(axis);

    var ge80 = (bins[4] || 0) + (bins[5] || 0);
    var mid = (bins[2] || 0) + (bins[3] || 0);
    var low = (bins[0] || 0) + (bins[1] || 0);
    var legend = el("div", "quality-legend");
    legend.appendChild(el("span", "dot is-done",
      uiT("dash_quality_excellent", "● {pct}% excellent (≥0.8)")
        .replace("{pct}", String(Math.round(ge80 / total * 100)))));
    legend.appendChild(el("span", "dot is-stale",
      uiT("dash_quality_fair", "● {pct}% fair (0.6–0.8)")
        .replace("{pct}", String(Math.round(mid / total * 100)))));
    legend.appendChild(el("span", "dot is-missing",
      uiT("dash_quality_low", "● {pct}% low (<0.6)")
        .replace("{pct}", String(Math.round(low / total * 100)))));
    card.appendChild(legend);
    wrap.appendChild(card);
    return wrap;
  }

  var currentLite = {};
  var currentProject = "";

  var REGIONAL_LOCALES = [
    "en-GB", "en-US", "en-AU", "en-CA",
    "pt-BR", "pt-PT",
    "zh-Hans", "zh-Hant", "zh-CN", "zh-TW",
    "es-MX", "es-ES", "es-AR",
    "fr-CA", "fr-FR",
    "nl-BE", "nl-NL",
    "de-AT", "de-CH",
    "nb", "nn", "sv", "da", "fi", "is",
    "sr-Latn", "sr-Cyrl", "az-Latn", "uz-Latn",
  ];

  var FALLBACK_LANGUAGES = [
    "af", "am", "ar", "az", "be", "bg", "bn", "bs", "ca", "cs", "cy", "da",
    "de", "el", "en", "eo", "es", "et", "eu", "fa", "fi", "fil", "fr", "ga",
    "gl", "gu", "he", "hi", "hr", "hu", "hy", "id", "is", "it", "ja", "ka",
    "kk", "km", "kn", "ko", "ku", "ky", "lo", "lt", "lv", "mk", "ml", "mn",
    "mr", "ms", "mt", "my", "nb", "ne", "nl", "nn", "no", "pa", "pl", "ps",
    "pt", "ro", "ru", "si", "sk", "sl", "sq", "sr", "sv", "sw", "ta", "te",
    "th", "tk", "tr", "uk", "ur", "uz", "vi", "yi", "zh",
  ];

  function localeCatalog() {
    var codes = {};
    var list = FALLBACK_LANGUAGES.slice();
    try {
      if (typeof Intl !== "undefined" && typeof Intl.supportedValuesOf === "function") {
        list = Intl.supportedValuesOf("language");
      }
    } catch (err) { /* keep fallback */ }
    list.forEach(function (code) { codes[code] = true; });
    REGIONAL_LOCALES.forEach(function (code) { codes[code] = true; });
    var rows = Object.keys(codes).map(function (code) {
      return { code: code, name: localeName(code) };
    });
    rows.sort(function (a, b) {
      var an = (a.name || a.code).toLowerCase();
      var bn = (b.name || b.code).toLowerCase();
      if (an < bn) return -1;
      if (an > bn) return 1;
      return a.code < b.code ? -1 : 1;
    });
    return rows;
  }

  function takenLocales(lite) {
    var taken = {};
    ((lite && lite.activeLocales) || []).forEach(function (c) { taken[c] = true; });
    ((lite && lite.frozenLocales) || []).forEach(function (c) { taken[c] = true; });
    if (lite && lite.sourceLocale) taken[lite.sourceLocale] = true;
    return taken;
  }

  function openAddLocaleModal() {
    var taken = takenLocales(currentLite);
    window.localePicker(localeCatalog(), taken, function (locale, done) {
      post("/api/add-locale", { project: currentProject || select.value, locale: locale })
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "add locale failed");
          done(null);
          load(currentProject || select.value);
        })
        .catch(function (ex) { done(String(ex.message || ex)); });
    });
  }

  function ensureFrame() {
    if (document.getElementById("dash-counts")) return;
    var counts = el("div", "counts");
    counts.id = "dash-counts";
    counts.appendChild(count(
      uiT("dash_total_strings", "Total strings"), "…",
      uiT("dash_across_namespaces_ph", "across … namespaces"), {
      valueId: "dash-count-strings",
      subId: "dash-count-strings-sub",
    }));
    counts.appendChild(count(
      uiT("dash_avg_coverage", "Avg coverage"), "…",
      uiT("dash_across_all_locales", "across all locales"), {
      accent: true,
      valueId: "dash-count-coverage",
    }));
    counts.appendChild(count(
      uiT("dash_pending_review", "Pending review"), "…",
      uiT("dash_open_queue", "Open queue →"), {
      linkHref: "/app/review",
      valueId: "dash-count-pending",
      subId: "dash-count-pending-sub",
    }));
    counts.appendChild(count(
      uiT("dash_avg_quality", "Avg quality"), "—",
      uiT("dash_bt_score", "back-translation score"), {
      valueId: "dash-count-quality",
    }));
    var guideHost = el("div");
    guideHost.id = "dash-guide";
    body.replaceChildren(guideHost, counts);

    var grid = el("div", "dash-grid");
    var left = el("div", "dash-col");
    var coverageHead = el("div", "dash-section-row");
    coverageHead.appendChild(el("div", "dash-section-label", uiT("dash_coverage_by_locale", "Coverage by locale")));
    if (window.LLMHelp) coverageHead.appendChild(window.LLMHelp.helpBtn("dashboard:general"));
    left.appendChild(coverageHead);
    var panel = el("div", "locale-panel");
    panel.id = "dash-locales";
    panel.appendChild(el("p", "empty-state", uiT("dash_loading_coverage", "Loading coverage…")));
    left.appendChild(panel);
    grid.appendChild(left);

    var right = el("div", "dash-col dash-col-side");
    var actions = el("div");
    actions.id = "dash-actions";
    right.appendChild(actions);
    var activity = el("div");
    activity.id = "dash-activity";
    right.appendChild(activity);
    var quality = el("div");
    quality.id = "dash-quality";
    right.appendChild(quality);
    actions.replaceChildren(quickActions("", {}, {}));
    activity.replaceChildren(sectionMessage(
      uiT("dash_recent_activity", "Recent activity"),
      uiT("dash_loading_activity", "Loading activity…")));
    quality.replaceChildren(sectionMessage(
      uiT("dash_quality_dist", "Quality distribution"),
      uiT("dash_loading_quality", "Loading quality…")));
    ["dash-budget", "dash-trend", "dash-screens", "dash-scan", "dash-source-review"].forEach(function (id) {
      var host = el("div");
      host.id = id;
      right.appendChild(host);
    });
    grid.appendChild(right);
    body.appendChild(grid);
  }

  function applyLite(project, lite) {
    paintHead(project, lite, null);
    var nsCount = ((lite && lite.namespaces) || []).length;
    setText("dash-count-strings", String((lite && lite.sourceTotal) || 0));
    setText(
      "dash-count-strings-sub",
      uiT("dash_across_n_namespaces", "across {n} namespace{s}")
        .replace("{n}", String(nsCount))
        .replace("{s}", nsCount === 1 ? "" : "s"),
    );
    var actions = document.getElementById("dash-actions");
    if (actions) actions.replaceChildren(quickActions(project, lite, {}));
  }

  function applyStats(project, lite, stats) {
    paintHead(project, lite, stats);
    var pending = (stats && stats.pendingReview) || 0;
    setReviewBadge(pending);
    var coverage = "…";
    if (stats && stats.locales && stats.locales.length) {
      var sum = 0;
      stats.locales.forEach(function (row) { sum += Number(row.coverage) || 0; });
      coverage = Math.round(sum / stats.locales.length) + "%";
    }
    setText("dash-count-coverage", coverage);
    setText("dash-count-pending", String(pending));
    setText("dash-count-pending-sub", pending
      ? uiT("dash_review_now", "Review now →")
      : uiT("dash_open_queue", "Open queue →"));
    var quality = (stats && stats.avgQuality != null) ? String(stats.avgQuality) : "—";
    setText("dash-count-quality", quality);
    var reviewLabel = document.getElementById("dash-review-label");
    if (reviewLabel) {
      reviewLabel.textContent = pending
        ? uiT("dash_review_pending", "Review {n} pending strings").replace("{n}", String(pending))
        : uiT("dash_open_review_queue", "Open review queue");
    }
    var panel = document.getElementById("dash-locales");
    if (panel) {
      panel.replaceChildren();
      if (stats.locales && stats.locales.length) {
        stats.locales.forEach(function (row) { panel.appendChild(bar(row)); });
      } else {
        panel.appendChild(el("p", "empty-state", uiT("dash_no_locales", "No locales configured.")));
      }
    }
    var qualityHost = document.getElementById("dash-quality");
    if (qualityHost) qualityHost.replaceChildren(qualitySection(stats));
    var budgetHost = document.getElementById("dash-budget");
    if (budgetHost) budgetHost.replaceChildren(budgetSection(stats));
  }

  function sparkline(values, width, height) {
    var ns = "http:" + "//www.w3.org/2000/svg"; // SVG namespace, not a request
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("class", "spark");
    var pts = [];
    values.forEach(function (v, i) {
      if (v == null || !isFinite(Number(v))) return;
      var x = values.length > 1 ? (i / (values.length - 1)) * (width - 2) + 1 : width / 2;
      var y = height - 1 - Math.max(0, Math.min(1, Number(v))) * (height - 2);
      pts.push(x.toFixed(1) + "," + y.toFixed(1));
    });
    if (pts.length) {
      var line = document.createElementNS(ns, "polyline");
      line.setAttribute("points", pts.join(" "));
      line.setAttribute("fill", "none");
      line.setAttribute("stroke", "currentColor");
      line.setAttribute("stroke-width", "1.5");
      svg.appendChild(line);
    }
    return svg;
  }

  function money(value) {
    var n = Number(value) || 0;
    return "$" + n.toFixed(n >= 100 ? 0 : 2);
  }

  function budgetSection(stats) {
    var b = (stats && stats.budget) || {};
    var wrap = el("div", "dash-section");
    wrap.appendChild(el("div", "dash-section-label", uiT("dash_cloud_budget", "Cloud budget")));
    var card = el("div", "quality-card budget-card");
    var months = b.byMonth || [];
    if (b.localOnly) {
      card.appendChild(el(
        "p", "empty-state",
        uiT("dash_budget_local_only", "Local only: no cloud calls are allowed, so nothing is spent."),
      ));
    } else if (!b.capUsd && !months.length && !b.cloudEnabled) {
      card.appendChild(el(
        "p", "empty-state",
        uiT(
          "dash_budget_cloud_off",
          "Cloud translation is off. Local models are free and are not counted here.",
        ),
      ));
    } else {
      var spent = Number(b.spentUsd) || 0;
      var cap = Number(b.capUsd) || 0;
      card.appendChild(el(
        "div", "budget-line",
        cap
          ? uiT("dash_budget_of_cap", "{spent} of {cap} this month")
            .replace("{spent}", money(spent)).replace("{cap}", money(cap))
          : uiT("dash_budget_no_cap", "{spent} this month (no ceiling set)")
            .replace("{spent}", money(spent)),
      ));
      if (cap) {
        var track = el("div", "budget-track");
        var fill = el("div", "budget-fill");
        var pct = Math.min(100, Math.round(spent / cap * 100));
        fill.style.width = pct + "%";
        if (pct >= 90) fill.classList.add("is-hot");
        track.appendChild(fill);
        card.appendChild(track);
        card.appendChild(el(
          "div", "budget-sub",
          uiT("dash_budget_left", "{left} left · mode {mode}")
            .replace("{left}", money(b.remainingUsd))
            .replace("{mode}", String(b.mode || "").replace(/_/g, " ")),
        ));
      }
      if (b.projectedUsd != null) {
        var over = cap && b.projectedUsd > cap;
        card.appendChild(el(
          "div", "budget-sub" + (over ? " is-over" : ""),
          over
            ? uiT("dash_budget_pace_over", "On pace for {amt} (over the ceiling)")
              .replace("{amt}", money(b.projectedUsd))
            : uiT("dash_budget_pace", "On pace for {amt}")
              .replace("{amt}", money(b.projectedUsd)),
        ));
      }
      if (months.length) {
        var spark = sparkline(months.map(function (m) { return m.usd; }), 120, 24);
        spark.setAttribute(
          "aria-label",
          uiT("dash_budget_spark", "Spend, last {n} months").replace("{n}", String(months.length)),
        );
        card.appendChild(spark);
      }
    }
    wrap.appendChild(card);
    return wrap;
  }

  function trendSection(metrics) {
    var wrap = el("div", "dash-section");
    wrap.appendChild(el("div", "dash-section-label", uiT("dash_quality_trend", "Quality trend")));
    var card = el("div", "quality-card");
    var rows = (metrics && metrics.data && metrics.data.locales) || [];
    if (!rows.length) {
      card.appendChild(el("p", "empty-state", uiT("dash_no_history", "No history yet.")));
    }
    rows.forEach(function (row) {
      var line = el("div", "trend-row");
      line.appendChild(el("span", "trend-locale", row.locale));
      line.appendChild(el("span", "trend-label", uiT("dash_trend_coverage", "coverage")));
      line.appendChild(sparkline((row.coverageTrend || []).map(function (p) { return p.coverage; }), 90, 22));
      line.appendChild(el("span", "trend-label", uiT("dash_trend_edit_rate", "edit rate")));
      line.appendChild(sparkline((row.editRateWeekly || []).map(function (p) { return p.editRate; }), 90, 22));
      line.appendChild(el("span", "trend-value", row.editRate == null ? "-" : Math.round(row.editRate * 100) + "%"));
      card.appendChild(line);
    });
    wrap.appendChild(card);
    return wrap;
  }

  function screensSection(result) {
    var rows = (result && result.data && result.data.screens) || [];
    var wrap = el("div", "dash-section");
    wrap.appendChild(el("div", "dash-section-label", uiT("dash_coverage_by_screen", "Coverage by screen")));
    var card = el("div", "quality-card");
    if (!rows.length || rows.every(function (r) { return r.screen === "(no screen)"; })) {
      card.appendChild(el(
        "p", "empty-state",
        uiT("dash_no_screens", "No screens named in context notes."),
      ));
    } else {
      rows.slice(0, 8).forEach(function (r) {
        var line = el("div", "trend-row");
        line.appendChild(el("span", "trend-locale", r.screen));
        line.appendChild(el("span", "trend-label", r.locale));
        line.appendChild(el(
          "span", "trend-value",
          uiT("dash_screen_pending", "{pct}% ({n} pending)")
            .replace("{pct}", String(Math.round(r.coverage * 100)))
            .replace("{n}", String(r.pending)),
        ));
        card.appendChild(line);
      });
    }
    wrap.appendChild(card);
    return wrap;
  }

  function sourceReviewSection(result) {
    var rows = (result && result.data && result.data.tickets) || [];
    if (!rows.length) return el("div");
    var wrap = el("div", "dash-section");
    wrap.appendChild(el(
      "div", "dash-section-label",
      uiT("dash_en_flagged", "English flagged for review ({n})")
        .replace("{n}", String(rows.length)),
    ));
    var card = el("div", "quality-card");
    rows.slice(0, 8).forEach(function (t) {
      var line = el("div", "trend-row");
      line.appendChild(el("span", "trend-locale", t.namespace + "." + t.key));
      line.appendChild(el("span", "trend-label", String(t.reason || "").replace(/^source-review:?\s*/, "")));
      card.appendChild(line);
    });
    wrap.appendChild(card);
    return wrap;
  }

  function scanAge(ts) {
    var then = ts ? Date.parse(ts) : NaN;
    if (isNaN(then)) return "";
    var minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
    if (minutes < 60) return uiT("dash_scan_age_min", "last scan {n} min ago").replace("{n}", String(minutes));
    var hours = Math.round(minutes / 60);
    if (hours < 48) return uiT("dash_scan_age_h", "last scan {n} h ago").replace("{n}", String(hours));
    return uiT("dash_scan_age_d", "last scan {n} days ago").replace("{n}", String(Math.round(hours / 24)));
  }

  function scanNext(result, wrap) {
    var steps = (result && result.next) || [];
    if (!steps.length) return;
    var list = el("ul", "dash-next");
    steps.slice(0, 3).forEach(function (step) {
      var item = el("li");
      item.appendChild(el("code", "", step.cmd || ""));
      if (step.why) item.appendChild(el("span", "muted", " — " + step.why));
      list.appendChild(item);
    });
    wrap.appendChild(list);
  }

  function scanButton(label) {
    // Static scan only (no --llm): read-only and inline, then the card repaints from the new cache (W5).
    var btn = el("button", "btn btn-primary dash-scan-run", label);
    btn.type = "button";
    btn.addEventListener("click", function () {
      var project = (select && select.value) || "";
      btn.disabled = true;
      btn.textContent = uiT("dash_scan_running", "Scanning…");
      post("/api/ops/agent-hardcoded", { project: project, format: "json" })
        .then(function (data) {
          if (!data || data.ok === false) {
            btn.textContent = (data && (data.error || data.summary)) || uiT("dash_could_not_start", "Could not start");
            btn.disabled = false;
            return;
          }
          loadExtras(project);
        })
        .catch(function () {
          btn.textContent = uiT("dash_request_failed", "Request failed");
          btn.disabled = false;
        });
    });
    return btn;
  }

  function findingsLink() {
    var link = el("a", "btn dash-scan-open", uiT("dash_scan_open", "Open findings"));
    link.href = "/app/hardcoded";
    return link;
  }

  function scanSection(result) {
    var d = (result && result.decisions) || null;
    if (result && !result.cached) {
      var empty = el("div", "dash-section dash-scan-empty");
      empty.appendChild(el("div", "dash-section-label", uiT("dash_hardcoded", "Hardcoded strings")));
      empty.appendChild(el("p", "muted", uiT("dash_scan_none", "No scan yet.")));
      empty.appendChild(el("p", "field-hint", uiT(
        "dash_scan_none_hint",
        "A scan finds user-visible text in the source that is not in the catalogue yet. It reads files only.")));
      empty.appendChild(scanButton(uiT("dash_scan_run", "Run a scan")));
      scanNext(result, empty);
      return empty;
    }
    if (!result || !d) return el("div");
    var wrap = el("div", "dash-section");
    wrap.appendChild(el(
      "div", "dash-section-label",
      result.stale
        ? uiT("dash_hardcoded_stale", "Hardcoded strings (source changed since the last scan)")
        : uiT("dash_hardcoded", "Hardcoded strings"),
    ));
    var card = el("div", "quality-card");
    [
      ["pending", uiT("dash_scan_waiting", "Waiting for your decision")],
      ["accepted", uiT("dash_scan_accepted", "Accepted")],
      ["applied", uiT("dash_scan_applied", "Applied")],
      ["ignored", uiT("dash_scan_ignored", "Ignored")],
    ].forEach(function (pair) {
      var line = el("div", "trend-row");
      line.appendChild(el("span", "trend-label", pair[1]));
      line.appendChild(el("span", "trend-value", String(d[pair[0]] || 0)));
      card.appendChild(line);
    });
    if (d.orphaned) {
      var gone = el("div", "trend-row");
      gone.appendChild(el(
        "span", "trend-label",
        uiT("dash_scan_orphaned", "Decisions for strings no longer found"),
      ));
      gone.appendChild(el("span", "trend-value", String(d.orphaned)));
      card.appendChild(gone);
    }
    wrap.appendChild(card);
    var age = scanAge(result.ts);
    if (age) wrap.appendChild(el("p", "muted", age));
    var actions = el("div", "dash-scan-actions");
    actions.appendChild(findingsLink());
    if (result.stale) actions.appendChild(scanButton(uiT("dash_scan_rerun", "Scan again")));
    wrap.appendChild(actions);
    scanNext(result, wrap);
    return wrap;
  }

  function loadExtras(project) {
    var query = "project=" + encodeURIComponent(project);
    function fill(id, promise, build) {
      promise.then(function (result) {
        var host = document.getElementById(id);
        if (host && result) host.replaceChildren(build(result));
      }).catch(function () {});
    }
    var getJson = function (url) {
      return fetch(url, { headers: headers() }).then(function (r) { return r.ok ? r.json() : null; });
    };
    fill("dash-trend", getJson("/api/metrics?" + query + "&since=90d"), trendSection);
    fill("dash-screens", getJson("/api/status?group_by=screen&" + query), screensSection);
    fill("dash-scan", getJson("/api/scan/status?" + query), scanSection);
    // The heaviest panel is a POST op; start it after the cheap GETs have painted.
    window.setTimeout(function () {
      fill("dash-source-review", post("/api/ops/source-review-queue", { project: project }), sourceReviewSection);
    }, 1200);
  }

  function applyProgress(progress) {
    var host = document.getElementById("dash-activity");
    if (host) host.replaceChildren(activitySection(progress));
  }

  var addBtn = document.getElementById("dash-add-locale");
  if (addBtn) {
    addBtn.addEventListener("click", function () {
      window.llmNavigate("/app/settings#locales");
    });
  }

  function boot() {
    ensureFrame();
    select.addEventListener("change", function () {
      if (select.value) load(select.value);
    });
    if (select.value) load(select.value);
  }

  // Wait for ui-locale dict so uiT() does not bake English fallbacks into
  // count kickers / quick actions under en-XX (leftover-hunt false positives).
  var ready = (window.uiLocale && typeof window.uiLocale.whenReady === "function")
    ? window.uiLocale.whenReady()
    : Promise.resolve();
  ready.then(boot);
})();
