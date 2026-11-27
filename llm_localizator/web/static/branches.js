(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "branches" || !root) return;

  root.replaceChildren();

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function t(key, fallback, vars) {
    var text = (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
    Object.keys(vars || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(vars[name]));
    });
    return text;
  }

  function project() {
    var select = document.getElementById("project-select");
    return select && select.value ? select.value : "";
  }

  function q(extra) {
    var s = project() ? "?project=" + encodeURIComponent(project()) : "?";
    return s + (extra ? (s === "?" ? "" : "&") + extra : "");
  }

  function post(path, body) {
    body = body || {};
    body.project = project();
    if (window.LLMApi && LLMApi.apiPost) return window.LLMApi.apiPost(path, body);
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function getJson(path) { return fetch(path).then(function (r) { return r.json(); }); }

  function button(label, cls, onClick) {
    var b = el("button", "btn" + (cls ? " " + cls : ""), label);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  var STATUS_LABEL = {
    default: ["br_badge_default", "default"],
    tracked: ["br_badge_progress", "tracked"],
    in_progress: ["br_badge_progress", "in progress"],
    ready: ["br_badge_ready", "ready to merge"],
    synced: ["br_badge_synced", "in sync"],
    merged: ["br_badge_merged", "merged"],
    archived: ["br_badge_archived", "archived"],
    unknown: ["br_badge_unknown", "no git data"],
  };

  function help(key) {
    return window.LLMHelp ? window.LLMHelp.helpBtn(key) : document.createComment("");
  }
  var head = el("div", "br-head");
  var headText = el("div", "");
  var sub = el("p", "", t(
    "br_subtitle", "Isolated translation sets per git branch — translate feature strings before they ship") + " ");
  sub.appendChild(help("branches:general"));
  headText.appendChild(sub);
  head.appendChild(headText);
  var headBtns = el("div", "br-actions");
  headBtns.appendChild(button(t("br_sync", "↻ Sync from git"), "", openSync));
  headBtns.appendChild(button(t("br_track", "+ Track branch"), "btn-primary", openTrack));
  head.appendChild(headBtns);
  var info = el("div", "br-info", t(
    "br_banner",
    "State and scores are kept per branch. Catalogues stay shared and travel through git; merging here moves only translation provenance into main."));

  var card = el("div", "br-card");
  var cardHead = el("div", "br-card-head");
  var title = el("div", "br-card-title", "");
  var filter = el("input", "br-filter");
  filter.type = "search";
  filter.placeholder = t("br_filter", "filter…");
  filter.addEventListener("input", paintRows);
  cardHead.appendChild(title);
  cardHead.appendChild(filter);
  var list = el("div", "br-list");
  var preview = el("div", "br-preview");
  var notice = el("p", "pg-sub br-notice", "");
  card.appendChild(cardHead);
  card.appendChild(list);
  root.appendChild(head);
  root.appendChild(info);
  root.appendChild(card);
  root.appendChild(preview);
  root.appendChild(notice);

  var data = { main: null, branches: [], targets: [] };

  function say(text) { notice.textContent = text || ""; }

  function covChip(locale, pct) {
    var level = pct >= 80 ? "ok" : pct >= 40 ? "mid" : "low";
    var chip = el("span", "", locale + " ");
    chip.appendChild(el("strong", "br-cov-" + level, pct + "%"));
    return chip;
  }

  function metaLine(b) {
    var parts = [];
    if (b.commit) parts.push(b.commit);
    if (b.base) parts.push(t("br_from", "from {base}", { base: b.base }));
    if (b.new_strings != null) {
      parts.push(t("br_new_strings", "+{n} new strings", { n: b.new_strings }));
    }
    if (b.changed_strings) {
      parts.push(t("br_changed_strings", "{n} changed", { n: b.changed_strings }));
    }
    if (b.tracked_at) parts.push(t("br_tracked", "tracked {d}", { d: String(b.tracked_at).slice(0, 10) }));
    return parts.join(" · ");
  }

  function row(b, isMain) {
    var r = el("div", "br-row" + (b.status === "merged" || b.status === "archived" ? " br-row-dim" : ""));
    var left = el("div", "br-left");
    left.appendChild(el("span", "br-dot br-dot-" + b.status));
    var body = el("div", "br-body");
    var line = el("div", "br-line");
    line.appendChild(el("span", "br-name", b.name));
    var lab = STATUS_LABEL[b.status];
    if (lab) line.appendChild(el("span", "br-badge br-badge-" + b.status, t(lab[0], lab[1])));
    if (b.active) line.appendChild(el("span", "br-badge br-badge-active", t("br_badge_active", "active")));
    body.appendChild(line);
    var meta = isMain
      ? (b.commit || "") + (b.source_strings != null
        ? " · " + t("br_source_strings", "{n} source strings", { n: b.source_strings }) : "")
      : metaLine(b);
    if (meta) body.appendChild(el("div", "br-meta", meta));
    var cov = el("div", "br-covs");
    Object.keys(b.coverage || {}).forEach(function (loc) { cov.appendChild(covChip(loc, b.coverage[loc])); });
    left.appendChild(body);
    r.appendChild(left);
    var right = el("div", "br-right");
    right.appendChild(cov);

    var acts = right;
    if (isMain) {
      if (!b.active) {
        acts.appendChild(button(t("br_use_main", "Use main state"), "", function () {
          post("/api/branches/active", { name: "main" }).then(load);
        }));
      }
    } else if (b.status === "archived" || b.status === "merged") {
      acts.appendChild(button(t("br_unarchive", "Unarchive"), "", function () {
        post("/api/branches/unarchive", { name: b.name }).then(function (res) { afterAction(res); });
      }));
      acts.appendChild(button(t("br_delete", "Delete"), "br-danger", function () { confirmDelete(b); }));
    } else {
      if (!b.active) {
        acts.appendChild(button(t("br_open_editor", "Open editor"), "", function () {
          post("/api/branches/active", { name: b.name }).then(function () {
            window.location.href = "/app/editor" + q();
          });
        }));
      }
      var tr = el("a", b.status === "in_progress" ? "btn btn-primary" : "btn", t("br_translate", "Translate →"));
      tr.href = "/app/operations" + q("branch=" + encodeURIComponent(b.name));
      acts.appendChild(tr);
      acts.appendChild(button(
        b.status === "ready" ? t("br_merge", "Merge →") : t("br_review", "Review"),
        b.status === "ready" ? "btn-primary" : "",
        function () { showMerge(b.name); }));
      acts.appendChild(button(t("br_archive", "Archive"), "", function () {
        post("/api/branches/archive", { name: b.name }).then(function (res) { afterAction(res); });
      }));
    }
    r.appendChild(right);
    return r;
  }

  function afterAction(res) {
    if (res && res.ok === false) say(res.error || t("br_failed", "Failed."));
    else say("");
    load();
  }

  function paintRows() {
    list.replaceChildren();
    var needle = filter.value.trim().toLowerCase();
    if (data.main) list.appendChild(row(data.main, true));
    var shown = 0;
    (data.branches || []).forEach(function (b) {
      if (needle && b.name.toLowerCase().indexOf(needle) < 0) return;
      shown += 1;
      list.appendChild(row(b, false));
    });
    if (!shown) {
      list.appendChild(el("p", "empty-state", (data.branches || []).length
        ? t("br_no_match", "No branch matches.")
        : t("br_none", "No tracked branches yet.")));
    }
  }

  function paint(res) {
    data = res || data;
    title.textContent = t("br_tracked_count", "Tracked branches — {n}", { n: (data.branches || []).length });
    paintRows();
  }

  function load() {
    getJson("/api/branches" + q()).then(paint).catch(function () {
      say(t("br_load_failed", "Could not load branches."));
    });
  }

  // --- modal -----------------------------------------------------------
  function modal(titleText, content, actions, helpKey) {
    var shade = el("div", "br-shade");
    var box = el("div", "br-modal");
    box.setAttribute("role", "dialog");
    var h2 = el("h2", "", titleText + " ");
    if (helpKey) h2.appendChild(help(helpKey));
    box.appendChild(h2);
    box.appendChild(content);
    var foot = el("div", "br-actions br-foot");
    foot.appendChild(button(t("br_close", "Close"), "", close));
    (actions || []).forEach(function (a) { foot.appendChild(a); });
    box.appendChild(foot);
    shade.appendChild(box);
    shade.addEventListener("click", function (e) { if (e.target === shade) close(); });
    function close() { shade.remove(); }
    document.body.appendChild(shade);
    return close;
  }

  function field(label, input) {
    var f = el("label", "br-field");
    f.appendChild(el("span", "", label));
    f.appendChild(input);
    return f;
  }

  function openTrack() {
    var wrap = el("div", "");
    var name = el("input", "");
    name.type = "text";
    name.placeholder = t("br_branch_ph", "feature/new-onboarding");
    var base = el("select", "");
    [(data.main && data.main.name) || "main"].concat(
      (data.branches || []).map(function (b) { return b.name; })
    ).forEach(function (n) { base.appendChild(el("option", "", n)); });
    var auto = el("input", "");
    auto.type = "checkbox";
    auto.checked = true;
    var autoLab = el("label", "br-check");
    autoLab.appendChild(auto);
    autoLab.appendChild(el("span", "", t("br_auto", "Auto-translate new strings")));
    wrap.appendChild(field(t("br_name", "Branch name"), name));
    wrap.appendChild(field(t("br_base", "Base branch"), base));
    wrap.appendChild(autoLab);
    var err = el("p", "pg-sub", "");
    wrap.appendChild(err);
    var close = modal(t("br_track_title", "Track a branch"), wrap, [
      button(t("br_track_go", "Track"), "btn-primary", function () {
        post("/api/branches/track", {
          name: name.value.trim(), base: base.value, auto_translate: auto.checked,
        }).then(function (res) {
          if (res.ok) { close(); load(); } else err.textContent = res.error || t("br_failed", "Failed.");
        });
      }),
    ], "branches:track");
    name.focus();
  }

  function openSync() {
    var wrap = el("div", "");
    var pre = el("pre", "br-term", "$ git status --porcelain\n…");
    wrap.appendChild(pre);
    var actions = [];
    getJson("/api/branches/sync" + q()).then(function (res) {
      if (!res.ok) { pre.textContent = res.error || t("br_failed", "Failed."); return; }
      var lines = ["$ git status --porcelain", (res.files || []).length
        ? (res.files || []).join("\n") : t("br_clean", "(no changed files)")];
      (res.branches || []).forEach(function (b) {
        lines.push(b.git
          ? b.name + "  " + b.commit + "  +" + b.added + " ~" + b.changed + " -" + b.removed
          : b.name + "  " + t("br_no_git", "not found in git"));
      });
      pre.textContent = lines.join("\n");
      if (res.has_remote) {
        var f = button(t("br_fetch", "git fetch (network)"), "", function () {
          pre.textContent = t("br_fetch_running", "$ git fetch --all --prune\n…");
          post("/api/branches/fetch", {}).then(function (r) {
            pre.textContent = t("br_fetch_prefix", "$ git fetch --all --prune\n") + (r.output || r.error || "");
            load();
          });
        });
        wrap.appendChild(f);
      }
    });
    modal(t("br_sync_title", "Sync from git"), wrap, actions, "branches:sync");
  }

  function confirmDelete(b) {
    var wrap = el("p", "", t(
      "br_delete_body",
      "Forget {name} and delete its state and scores? This cannot be undone.", { name: b.name }));
    var close = modal(t("br_delete_title", "Delete branch"), wrap, [
      button(t("br_delete", "Delete"), "br-danger", function () {
        post("/api/branches/delete", { name: b.name, confirm: true }).then(function (res) {
          close();
          afterAction(res);
        });
      }),
    ]);
  }

  // --- merge preview ---------------------------------------------------
  function showMerge(name) {
    preview.replaceChildren();
    getJson("/api/branches/merge-preview" + q("branch=" + encodeURIComponent(name))).then(function (res) {
      preview.replaceChildren();
      var box = el("div", "br-card br-pad");
      var ph = el("strong", "", t("br_preview_title", "Merge preview — {name}", { name: name }) + " ");
      ph.appendChild(help("branches:merge"));
      box.appendChild(ph);
      if (!res.ok) {
        box.appendChild(el("p", "empty-state", res.error || t("br_failed", "Failed.")));
        preview.appendChild(box);
        return;
      }
      var rows = res.rows || [];
      var fresh = rows.filter(function (r) { return r.kind !== "conflict"; });
      var conflicts = rows.filter(function (r) { return r.kind === "conflict"; });
      box.appendChild(el("div", "br-meta", t(
        "br_preview_counts", "{n} entries to import · {c} conflicts", { n: fresh.length, c: conflicts.length })));
      fresh.slice(0, 3).forEach(function (r) {
        box.appendChild(el("div", "br-key", r.locale + " · " + r.namespace + "." + r.key));
      });
      if (fresh.length > 3) {
        box.appendChild(el("div", "br-meta", t("br_more", "…{n} more", { n: fresh.length - 3 })));
      }
      var picks = {};
      var mergeBtn;
      function refresh() {
        var open = conflicts.filter(function (r) {
          return !picks[r.locale + "|" + r.namespace + "|" + r.key];
        }).length;
        mergeBtn.disabled = open > 0;
        mergeBtn.title = open ? t("br_resolve_first", "Resolve every conflict first") : "";
      }
      if (!conflicts.length) {
        box.appendChild(el("div", "br-safe", t("br_safe", "✓ No conflicts — safe to merge")));
      } else {
        var cb = el("div", "br-conflicts");
        cb.appendChild(el("strong", "", t("br_conflicts", "Conflicts")));
        conflicts.forEach(function (r) {
          var id = r.locale + "|" + r.namespace + "|" + r.key;
          var line = el("div", "br-conflict");
          line.appendChild(el("div", "br-key", r.locale + " · " + r.namespace + "." + r.key));
          line.appendChild(el("div", "br-meta",
            t("br_main", "main") + ": " + ((r.main && r.main.model) || "?") + " · " +
            t("br_branch", "branch") + ": " + ((r.branch && r.branch.model) || "?")));
          ["branch", "main"].forEach(function (side) {
            var b = button(side === "branch" ? t("br_take_branch", "Take branch") : t("br_keep_main", "Keep main"),
              "", function () {
                picks[id] = side;
                line.querySelectorAll("button").forEach(function (x) { x.classList.remove("btn-primary"); });
                b.classList.add("btn-primary");
                refresh();
              });
            line.appendChild(b);
          });
          cb.appendChild(line);
        });
        box.appendChild(cb);
      }
      var acts = el("div", "br-actions");
      mergeBtn = button(t("br_merge_main", "Merge to main"), "btn-primary", function () {
        var choices = Object.keys(picks).map(function (k) {
          var p = k.split("|");
          return { locale: p[0], namespace: p[1], key: p[2], side: picks[k] };
        });
        post("/api/branches/merge", { branch: name, choices: choices }).then(function (r) {
          say(r.ok
            ? t("br_merged", "Merged: applied {a}, skipped {s}.", { a: r.applied, s: r.skipped })
            : (r.error || t("br_failed", "Failed.")));
          preview.replaceChildren();
          load();
        });
      });
      acts.appendChild(mergeBtn);
      var dl = el("a", "btn", t("br_download", "Download diff"));
      dl.href = "/api/branches/diff" + q("branch=" + encodeURIComponent(name));
      dl.target = "_blank";
      dl.rel = "noopener";
      acts.appendChild(dl);
      box.appendChild(acts);
      preview.appendChild(box);
      refresh();
    });
  }

  load();
})();
