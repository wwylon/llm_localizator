(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "workflow" || !root) return;

  root.replaceChildren();

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

  /** Display label for a workflow id (ids stay English in the API / config). */
  function workflowLabel(name) {
    if (name === "default") return t("wf_name_default", "default");
    return name;
  }

  function project() {
    var select = document.getElementById("project-select");
    return select && select.value ? select.value : "";
  }

  function post(path, body) {
    body = body || {};
    body.project = project();
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost(path, body);
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function getJson(path) {
    if (window.LLMApi && LLMApi.apiGet) {
      var q = {};
      var qi = path.indexOf("?");
      var base = qi >= 0 ? path.slice(0, qi) : path;
      if (qi >= 0) {
        path.slice(qi + 1).split("&").forEach(function (pair) {
          var parts = pair.split("=");
          if (parts[0]) q[decodeURIComponent(parts[0])] = decodeURIComponent(parts[1] || "");
        });
      }
      if (!q.project) q.project = project();
      return LLMApi.apiGet(base, q);
    }
    return fetch(path).then(function (r) { return r.json(); });
  }

  function button(label, cls, onClick) {
    var b = el("button", "btn" + (cls ? " " + cls : ""), label);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  function help(key) {
    return window.LLMHelp ? window.LLMHelp.helpBtn(key) : document.createComment("");
  }

  function clone(x) { return JSON.parse(JSON.stringify(x)); }

  // --- block catalogue -----------------------------------------------
  var CATS = [
    { id: "run", label: ["wf_cat_run", "Run"], blocks: ["translate", "rescore", "improve", "llm_review", "validate"] },
    { id: "control", label: ["wf_cat_control", "Control"], blocks: ["if", "stop"] },
    { id: "result", label: ["wf_cat_result", "Result"], blocks: ["verify", "review_ticket"] },
    { id: "mark", label: ["wf_cat_mark", "Mark"], blocks: ["flag"] },
    { id: "notify", label: ["wf_cat_notify", "Notify"], blocks: ["notify"] },
  ];
  var BLOCK_LABEL = {
    translate: "Translate", rescore: "Re-score", improve: "Improve",
    llm_review: "LLM review", validate: "Validate", "if": "If", stop: "Stop",
    verify: "Auto-approve", review_ticket: "Human review ticket",
    flag: "Flag for admin", notify: "Send webhook",
  };
  var BLOCK_TIP = {
    translate: "Translate missing and stale strings with the local model.",
    rescore: "Back-translate and score every string that reaches this block.",
    improve: "Re-translate low-scoring strings with the improve prompt (cooldown and loop cap apply).",
    llm_review: "Run the LLM review pass on the strings that reach this block.",
    validate: "Check placeholders, ICU and the other validation rules. Findings are logged; strings keep flowing.",
    "if": "Split the strings by a condition. Matching ones take Then, the rest take Else.",
    stop: "End the script here for the strings that reach this block.",
    verify: "Stamp the strings verified (verified_by=workflow). They leave the flow.",
    review_ticket: "Open a human review ticket (low_score). The strings leave the flow.",
    flag: "Add the strings to the admin flag list. They keep flowing.",
    notify: "Post a short summary to the project webhook when the run ends.",
  };
  function catOf(type) {
    for (var i = 0; i < CATS.length; i++) {
      if (CATS[i].blocks.indexOf(type) >= 0) return CATS[i].id;
    }
    return "run";
  }
  function blockLabel(type) { return t("wf_blk_" + type, BLOCK_LABEL[type] || type); }
  function blockTip(type) { return t("wf_blk_" + type + "_tip", BLOCK_TIP[type] || ""); }

  var FIELD_LABEL = {
    score: ["wf_field_score", "score"], status: ["wf_field_status", "status"],
    locale: ["wf_field_locale", "locale"], namespace: ["wf_field_namespace", "namespace"],
  };
  var OP_LABEL = {
    ge: "≥", le: "≤", is: ["wf_op_is", "is"], is_not: ["wf_op_is_not", "is not"],
  };
  function fieldLabel(f) { var l = FIELD_LABEL[f] || [f, f]; return t(l[0], l[1]); }
  function opLabel(o) { var l = OP_LABEL[o]; return Array.isArray(l) ? t(l[0], l[1]) : (l || o); }
  function opsFor(field) { return field === "score" ? ["ge", "le"] : ["is", "is_not"]; }

  var WARN = {
    score_before_rescore: "A score condition runs before any Re-score block: it reads the scores already stored.",
    empty_branch: "An If block has no blocks in Then or Else.",
    unreachable_after_stop: "Blocks after a Stop block never run.",
  };

  // --- state ---------------------------------------------------------
  var state = {
    workflows: [], active: "", options: {}, dirty: false, canEdit: true,
    slot: null, selected: null, undo: [], redo: [], poll: null, drag: null,
  };

  // --- script helpers (a "path" is [i, "then", j, ...]; stack path ends in a branch) ----
  function stackAt(script, spath) {
    var cur = script;
    for (var i = 0; i < spath.length; i += 2) {
      cur = cur[spath[i]][spath[i + 1]];
    }
    return cur;
  }
  function countBlocks(stack) {
    var n = 0;
    stack.forEach(function (b) {
      n += 1;
      if (b.type === "if") n += countBlocks(b.then || []) + countBlocks(b.else || []);
    });
    return n;
  }
  function depthOf(spath) { return spath.length / 2; }
  function pathKey(p) { return p.join("."); }
  function isPrefix(a, b) {
    if (a.length > b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }
  function defaultValue(field) {
    var o = state.options;
    if (field === "score") return 0.8;
    if (field === "status") return (o.statuses || ["machine"])[0];
    if (field === "locale") return (o.locales || [""])[0] || "";
    return (o.namespaces || [""])[0] || "";
  }
  function newBlock(type) {
    if (type === "if") {
      return { type: "if", field: "score", op: "ge", value: 0.8, then: [], "else": [] };
    }
    return { type: type };
  }

  // --- skeleton ------------------------------------------------------
  var head = el("div", "wf-head");
  var headText = el("div", "");
  var h1 = el("h1", "wf-title", t("wf_title", "Workflow automation"));
  var sub = el("p", "", t(
    "wf_subtitle_blocks",
    "Build the pipeline from blocks — they run top to bottom, in the order you stack them ") + " ");
  sub.appendChild(help("workflow:general"));
  headText.appendChild(h1);
  headText.appendChild(sub);
  head.appendChild(headText);
  var headBtns = el("div", "wf-actions");
  var newBtn = button(t("wf_new", "+ New workflow"), "", openNew);
  var undoBtn = button("↶", "", function () { stepHistory(state.undo, state.redo); });
  var redoBtn = button("↷", "", function () { stepHistory(state.redo, state.undo); });
  undoBtn.title = t("wf_undo", "Undo");
  redoBtn.title = t("wf_redo", "Redo");
  var saveBtn = button(t("wf_save", "Save"), "btn-primary", save);
  var dupBtn = button(t("wf_duplicate", "Duplicate"), "", duplicate);
  var copyBtn = button(t("wf_copy_to", "Copy to project…"), "", openCopy);
  [undoBtn, redoBtn, dupBtn, copyBtn, newBtn, saveBtn].forEach(function (b) { headBtns.appendChild(b); });
  head.appendChild(headBtns);

  var tabs = el("div", "wf-tabs");
  var layout = el("div", "wf-layout wf-blocks-layout");
  var palette = el("aside", "wf-palette");
  var canvas = el("div", "wf-canvas wf-script");
  var panel = el("aside", "wf-panel");
  layout.appendChild(palette);
  layout.appendChild(canvas);
  layout.appendChild(panel);
  var status = el("p", "pc-status", "");
  root.appendChild(head);
  root.appendChild(tabs);
  root.appendChild(layout);
  root.appendChild(status);

  function say(text, isError) {
    status.textContent = text || "";
    status.className = "pc-status" + (isError ? " is-error" : "");
  }

  function active() {
    return state.workflows.find(function (w) { return w.name === state.active; }) || null;
  }

  function touch() {
    state.dirty = true;
    saveBtn.disabled = !state.canEdit;
    saveBtn.textContent = t("wf_save", "Save") + " •";
  }

  // --- undo / redo ----------------------------------------------------
  function snapshot(wf) {
    return JSON.stringify({ script: wf.script, loops: wf.maxImproveLoops });
  }
  function remember(wf) {
    state.undo.push(snapshot(wf));
    if (state.undo.length > 100) state.undo.shift();
    state.redo = [];
  }
  function stepHistory(from, to) {
    var wf = active();
    if (!wf || !from.length) return;
    to.push(snapshot(wf));
    var snap = JSON.parse(from.pop());
    wf.script = snap.script;
    wf.maxImproveLoops = snap.loops;
    state.slot = null; state.selected = null;
    touch(); paint();
  }
  function mutate(fn) {
    var wf = active();
    if (!wf || !state.canEdit) return;
    remember(wf);
    fn(wf);
    touch(); paint();
  }

  // --- editing operations --------------------------------------------
  function insertBlock(wf, spath, index, block) {
    if (countBlocks(wf.script) + countBlocks([block]) > (state.options.maxBlocks || 100)) {
      say(t("wf_too_many", "A script may hold at most {n} blocks.", { n: state.options.maxBlocks || 100 }), true);
      return false;
    }
    if (depthOf(spath) >= (state.options.maxDepth || 6) - 1 && block.type === "if") {
      say(t("wf_too_deep", "Blocks cannot be nested deeper than {n} levels.", { n: state.options.maxDepth || 6 }), true);
      return false;
    }
    stackAt(wf.script, spath).splice(index, 0, block);
    return true;
  }

  function addFromPalette(type) {
    mutate(function (wf) {
      var spath = state.slot ? state.slot.spath : [];
      var stack = stackAt(wf.script, spath);
      var index = state.slot ? Math.min(state.slot.index, stack.length) : stack.length;
      if (insertBlock(wf, spath, index, newBlock(type)) && state.slot) {
        state.slot = { spath: spath, index: index + 1 };
      }
    });
  }

  function moveBlock(from, spath, index) {
    // from = {spath, index}
    mutate(function (wf) {
      var src = stackAt(wf.script, from.spath);
      var block = src[from.index];
      var blockPath = from.spath.concat([from.index]);
      if (isPrefix(blockPath, spath)) return; // cannot drop into itself
      src.splice(from.index, 1);
      var dest = spath;
      // adjust target index / path when removal shifted earlier siblings
      var same = pathKey(from.spath) === pathKey(spath);
      if (same && from.index < index) index -= 1;
      if (!same && isPrefix(from.spath, spath) && spath[from.spath.length] > from.index) {
        dest = spath.slice();
        dest[from.spath.length] -= 1;
      }
      stackAt(wf.script, dest).splice(index, 0, block);
    });
  }

  function removeBlock(spath, index) {
    mutate(function (wf) {
      stackAt(wf.script, spath).splice(index, 1);
      state.slot = null; state.selected = null;
    });
  }

  function shiftBlock(spath, index, delta) {
    mutate(function (wf) {
      var stack = stackAt(wf.script, spath);
      var j = index + delta;
      if (j < 0 || j >= stack.length) return;
      var tmp = stack[index]; stack[index] = stack[j]; stack[j] = tmp;
    });
  }

  // --- palette --------------------------------------------------------
  function paintPalette() {
    palette.replaceChildren();
    var h = el("h3", "wf-section-title", t("wf_palette", "Blocks") + " ");
    h.appendChild(help("workflow:blocks"));
    palette.appendChild(h);
    var filter = el("input", "pc-input wf-filter");
    filter.type = "search";
    filter.placeholder = t("wf_search", "Search blocks…");
    palette.appendChild(filter);
    var groups = [];
    CATS.forEach(function (cat) {
      var g = el("div", "wf-cat");
      g.appendChild(el("div", "wf-cat-title", t(cat.label[0], cat.label[1])));
      cat.blocks.forEach(function (type) {
        var b = el("div", "wf-blk wf-cat-" + cat.id + " wf-pal", blockLabel(type));
        b.tabIndex = 0;
        b.setAttribute("role", "button");
        b.title = blockTip(type);
        b.draggable = state.canEdit;
        b.dataset.label = blockLabel(type).toLowerCase();
        b.addEventListener("dragstart", function (e) {
          state.drag = { kind: "new", type: type };
          e.dataTransfer.setData("text/plain", "new:" + type);
          e.dataTransfer.effectAllowed = "copy";
        });
        b.addEventListener("dragend", function () { state.drag = null; clearDropMarks(); });
        b.addEventListener("click", function () { addFromPalette(type); });
        b.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); addFromPalette(type); }
        });
        g.appendChild(b);
      });
      groups.push(g);
      palette.appendChild(g);
    });
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase();
      palette.querySelectorAll(".wf-pal").forEach(function (b) {
        b.style.display = !q || b.dataset.label.indexOf(q) >= 0 ? "" : "none";
      });
    });
    palette.appendChild(el("p", "pc-hint", t(
      "wf_palette_hint", "Drag a block into the script, or click it to add it at the highlighted spot.")));
  }

  // --- script area ----------------------------------------------------
  function clearDropMarks() {
    canvas.querySelectorAll(".is-over").forEach(function (n) { n.classList.remove("is-over"); });
  }

  function dropZone(spath, index) {
    var z = el("div", "wf-drop");
    var sel = state.slot && pathKey(state.slot.spath) === pathKey(spath) && state.slot.index === index;
    if (sel) z.classList.add("is-slot");
    z.title = t("wf_drop_here", "Add blocks here");
    z.addEventListener("click", function () {
      state.slot = sel ? null : { spath: spath, index: index };
      paintCanvas(active());
    });
    z.addEventListener("dragover", function (e) {
      if (!state.drag) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = state.drag.kind === "new" ? "copy" : "move";
      z.classList.add("is-over");
    });
    z.addEventListener("dragleave", function () { z.classList.remove("is-over"); });
    z.addEventListener("drop", function (e) {
      e.preventDefault();
      z.classList.remove("is-over");
      var d = state.drag;
      state.drag = null;
      if (!d) return;
      if (d.kind === "new") {
        mutate(function (wf) { insertBlock(wf, spath, index, newBlock(d.type)); });
      } else {
        moveBlock(d, spath, index);
      }
    });
    return z;
  }

  function select(values, current, labelFn, onChange) {
    var s = el("select", "pc-select");
    values.forEach(function (v) {
      var o = el("option", "", labelFn ? labelFn(v) : v);
      o.value = v;
      s.appendChild(o);
    });
    if (values.indexOf(current) < 0 && current !== "") {
      var o2 = el("option", "", String(current));
      o2.value = current;
      s.appendChild(o2);
    }
    s.value = current;
    s.disabled = !state.canEdit;
    s.addEventListener("change", function () { onChange(s.value); });
    return s;
  }

  function valueInput(block) {
    var o = state.options;
    if (block.field === "score") {
      var i = el("input", "pc-input wf-score");
      i.type = "number"; i.step = "0.01"; i.min = "0"; i.max = "1";
      i.value = String(block.value);
      i.disabled = !state.canEdit;
      i.addEventListener("change", function () {
        mutate(function () { block.value = Math.min(1, Math.max(0, Number(i.value) || 0)); });
      });
      return i;
    }
    var list = (block.field === "status" ? o.statuses
      : block.field === "locale" ? o.locales : o.namespaces) || [];
    if (!list.length) {
      var txt = el("input", "pc-input");
      txt.type = "text"; txt.value = String(block.value);
      txt.disabled = !state.canEdit;
      txt.addEventListener("change", function () { mutate(function () { block.value = txt.value; }); });
      return txt;
    }
    return select(list, String(block.value), null, function (v) {
      mutate(function () { block.value = v; });
    });
  }

  function badge(wf, key) {
    var counts = (wf.run && wf.run.counts && Object.keys(wf.run.counts).length ? wf.run.counts : null) || (wf.lastRun && wf.lastRun.counts) || {};
    var n = counts[key];
    if (n == null) return null;
    var b = el("span", "wf-count", n < 0 ? t("wf_count_all", "all") : String(n));
    b.title = t("wf_count_tip", "Strings that reached this block in the last run");
    return b;
  }

  function renderStack(wf, spath, stack) {
    var wrap = el("div", "wf-stack");
    wrap.appendChild(dropZone(spath, 0));
    stack.forEach(function (block, i) {
      wrap.appendChild(renderBlock(wf, spath, i, block));
      wrap.appendChild(dropZone(spath, i + 1));
    });
    return wrap;
  }

  function renderBlock(wf, spath, i, block) {
    var path = spath.concat([i]);
    var key = pathKey(path);
    var cat = catOf(block.type);
    var running = wf.run && wf.run.status === "waiting" &&
      (wf.run.waiting || []).some(function (w) { return w.at === key; });
    var node = el("div", "wf-blk wf-cat-" + cat + (block.type === "if" ? " wf-c" : "") +
      (running ? " is-running" : "") + (state.selected === key ? " is-selected" : ""));
    node.draggable = state.canEdit;
    node.addEventListener("dragstart", function (e) {
      if (e.target !== node) return;
      state.drag = { kind: "move", spath: spath, index: i };
      e.dataTransfer.setData("text/plain", "move:" + key);
      e.dataTransfer.effectAllowed = "move";
      e.stopPropagation();
    });
    node.addEventListener("dragend", function () { state.drag = null; clearDropMarks(); });

    var row = el("div", "wf-blk-row");
    row.appendChild(el("strong", "wf-blk-name", blockLabel(block.type)));
    if (block.type === "if") {
      row.appendChild(select(state.options.fields || ["score", "status", "locale", "namespace"],
        block.field, fieldLabel, function (v) {
          mutate(function () { block.field = v; block.op = opsFor(v)[0]; block.value = defaultValue(v); });
        }));
      row.appendChild(select(opsFor(block.field), block.op, opLabel, function (v) {
        mutate(function () { block.op = v; });
      }));
      row.appendChild(valueInput(block));
    } else if (block.type === "improve") {
      row.appendChild(el("span", "wf-param", t("wf_max_loops_blk", "max loops")));
      var lp = el("input", "pc-input wf-loops");
      lp.type = "number"; lp.min = "0"; lp.max = String(state.options.maxLoops || 5);
      lp.value = String(block.max_loops != null ? block.max_loops : wf.maxImproveLoops);
      lp.disabled = !state.canEdit;
      lp.addEventListener("click", function (e) { e.stopPropagation(); });
      lp.addEventListener("change", function () {
        var n = Math.min(Number(lp.max), Math.max(0, Math.floor(Number(lp.value) || 0)));
        mutate(function () { block.max_loops = n; });
      });
      row.appendChild(lp);
    }
    var b = badge(wf, key);
    if (b) row.appendChild(b);
    var tools = el("span", "wf-tools");
    [["▲", -1, t("wf_move_up", "Move up")], ["▼", 1, t("wf_move_down", "Move down")]].forEach(function (d) {
      var tb = button(d[0], "wf-tool", function () { shiftBlock(spath, i, d[1]); });
      tb.title = d[2]; tb.disabled = !state.canEdit;
      tools.appendChild(tb);
    });
    var del = button("✕", "wf-tool wf-del", function () { removeBlock(spath, i); });
    del.title = t("wf_remove_block", "Remove block"); del.disabled = !state.canEdit;
    tools.appendChild(del);
    row.appendChild(tools);
    row.addEventListener("click", function (e) {
      if (e.target.closest("select, input, button")) return;
      state.selected = state.selected === key ? null : key;
      paintCanvas(wf);
      paintPanel(wf);
    });
    node.appendChild(row);

    if (block.type === "if") {
      ["then", "else"].forEach(function (branch) {
        var slot = el("div", "wf-slot");
        slot.appendChild(el("div", "wf-slot-label", t("wf_" + branch, branch === "then" ? "then" : "else")));
        var inner = renderStack(wf, path.concat([branch]), block[branch] || []);
        slot.appendChild(inner);
        node.appendChild(slot);
      });
    }
    return node;
  }

  function paintCanvas(wf) {
    canvas.replaceChildren();
    var hat = el("div", "wf-blk wf-hat");
    hat.appendChild(el("strong", "", t("wf_hat", "When workflow runs")));
    hat.appendChild(el("span", "wf-param", wf.locales && wf.locales.length
      ? wf.locales.join(", ") : t("wf_locales_all", "All active locales")));
    canvas.appendChild(hat);
    canvas.appendChild(renderStack(wf, [], wf.script));
    if (!wf.script.length) {
      canvas.appendChild(el("p", "empty-state", t(
        "wf_empty_script", "Empty script — drag blocks here or click one in the palette.")));
    }
    (wf.warnings || []).forEach(function () {});
    var warns = localWarnings(wf);
    warns.forEach(function (code) {
      canvas.appendChild(el("p", "wf-warn", "⚠ " + t("wf_warn_" + code, WARN[code] || code)));
    });
  }

  // recompute soft warnings client-side so they follow edits before saving
  function localWarnings(wf) {
    var out = [];
    var rescored = false;
    (function walk(stack) {
      stack.forEach(function (b, i) {
        if (b.type === "rescore") rescored = true;
        if (b.type === "if") {
          if (b.field === "score" && !rescored && out.indexOf("score_before_rescore") < 0) {
            out.push("score_before_rescore");
          }
          if (!(b.then || []).length && !(b["else"] || []).length && out.indexOf("empty_branch") < 0) {
            out.push("empty_branch");
          }
          walk(b.then || []); walk(b["else"] || []);
        }
        if (b.type === "stop" && i + 1 < stack.length && out.indexOf("unreachable_after_stop") < 0) {
          out.push("unreachable_after_stop");
        }
      });
    })(wf.script);
    return out;
  }

  // --- which workflow applies to which locale (mirrors ops.workflow_assignments) ----
  function assignments() {
    var by = {}, over = {};
    (state.options.locales || []).forEach(function (loc) {
      var scoped = state.workflows.filter(function (w) {
        return w.locales && w.locales.indexOf(loc) >= 0;
      }).map(function (w) { return w.name; }).sort();
      if (scoped.length > 1) over[loc] = scoped;
      if (scoped.length) by[loc] = scoped[0];
      else {
        var d = state.workflows.find(function (w) { return w.name === "default" && !w.locales; });
        by[loc] = d ? "default" : null;
      }
    });
    return { by: by, over: over };
  }
  function appliesTo(wf) {
    var a = assignments();
    return Object.keys(a.by).filter(function (loc) { return a.by[loc] === wf.name; });
  }
  function assignWarnings() {
    var a = assignments(), out = [];
    Object.keys(a.over).forEach(function (loc) {
      out.push(t("wf_warn_overlap", "{loc} is in several workflow scopes ({names}); the first alphabetically wins.",
        { loc: loc, names: a.over[loc].join(", ") }));
    });
    var un = Object.keys(a.by).filter(function (loc) { return !a.by[loc]; });
    if (un.length) {
      out.push(t("wf_warn_uncovered", "No workflow applies to: {locs}. Scope a workflow to them or define \"default\".",
        { locs: un.join(", ") }));
    }
    return out;
  }

  // --- panel ---------------------------------------------------------
  function section(titleText, helpKey) {
    var s = el("div", "wf-section");
    var h = el("h3", "wf-section-title", titleText + " ");
    if (helpKey) h.appendChild(help(helpKey));
    s.appendChild(h);
    return s;
  }

  function field(labelText, control) {
    var f = el("label", "pc-field");
    f.appendChild(el("span", "pc-label", labelText));
    f.appendChild(control);
    return f;
  }

  function paintPanel(wf) {
    panel.replaceChildren();
    var cfg = section(t("wf_config_title", "Workflow settings"), "workflow:config");

    var nameIn = el("input", "pc-input");
    nameIn.type = "text"; nameIn.value = wf.name; nameIn.disabled = !state.canEdit;
    nameIn.addEventListener("change", function () {
      var nn = nameIn.value.trim();
      if (!nn || state.workflows.some(function (w) { return w !== wf && w.name === nn; })) {
        nameIn.value = wf.name;
        say(t("wf_name_invalid", "Name must be unique and not empty."), true);
        return;
      }
      wf.name = nn; state.active = nn; touch(); paint();
    });
    cfg.appendChild(field(t("wf_name", "Workflow name"), nameIn));

    var locField = el("div", "pc-field");
    locField.appendChild(el("span", "pc-label", t("wf_locales", "Locales")));
    var all = state.options.locales || [];
    var scope = wf.locales || null;
    var allBox = el("label", "pc-check");
    var allCb = el("input", ""); allCb.type = "checkbox";
    allCb.checked = !scope; allCb.disabled = !state.canEdit;
    allCb.addEventListener("change", function () {
      wf.locales = allCb.checked ? null : all.slice();
      touch(); paint();
    });
    allBox.appendChild(allCb);
    allBox.appendChild(el("span", "", t("wf_locales_all", "All active locales")));
    locField.appendChild(allBox);
    if (scope) {
      all.forEach(function (loc) {
        var l = el("label", "pc-check");
        var cb = el("input", ""); cb.type = "checkbox";
        cb.checked = scope.indexOf(loc) >= 0; cb.disabled = !state.canEdit;
        cb.addEventListener("change", function () {
          wf.locales = all.filter(function (x) {
            return x === loc ? cb.checked : scope.indexOf(x) >= 0;
          });
          if (!wf.locales.length) wf.locales = null;
          touch(); paint();
        });
        l.appendChild(cb);
        l.appendChild(el("span", "", loc));
        locField.appendChild(l);
      });
    }
    cfg.appendChild(locField);
    var ap = el("p", "pc-hint wf-applies", t("wf_applies_to", "Applies to") + ": " +
      (appliesTo(wf).join(", ") || t("wf_applies_none", "no locale")));
    cfg.appendChild(ap);
    assignWarnings().forEach(function (w) { cfg.appendChild(el("p", "wf-warn", "⚠ " + w)); });

    var ns = el("select", "pc-select");
    [
      ["none", t("wf_notify_none", "None"), false],
      ["webhook", t("wf_notify_webhook", "Webhook"), false],
    ].forEach(function (o) {
      var op = el("option", "", o[1]);
      op.value = o[0]; op.disabled = o[2];
      ns.appendChild(op);
    });
    ns.value = wf.notify || "none"; ns.disabled = !state.canEdit;
    ns.addEventListener("change", function () { wf.notify = ns.value; touch(); paint(); });
    var nf = field(t("wf_notify", "Notification"), ns);
    cfg.appendChild(nf);
    var hasNotifyBlock = false;
    (function walk(stack) {
      stack.forEach(function (b) {
        if (b.type === "notify") hasNotifyBlock = true;
        if (b.type === "if") { walk(b.then || []); walk(b["else"] || []); }
      });
    })(wf.script);
    var showHook = wf.notify === "webhook" || hasNotifyBlock;
    var hook = el("input", "pc-input");
    hook.type = "url"; hook.disabled = !state.canEdit;
    hook.value = state.hookDraft || "";
    hook.placeholder = state.options.webhookConfigured
      ? t("wf_hook_set", "Webhook configured — paste a URL to replace")
      : "https://…";
    hook.addEventListener("input", function () { state.hookDraft = hook.value.trim(); touch(); });
    var hf = field(t("wf_hook_url", "Webhook URL"), hook);
    hf.appendChild(el("p", "pc-hint", t(
      "wf_notify_hint", "Saved to [notify] webhook in the project config; applies to all workflows.")));
    if (showHook) cfg.appendChild(hf);
    panel.appendChild(cfg);

    if (state.selected != null) {
      var blk = blockByKey(wf, state.selected);
      if (blk) {
        var sel = section(blockLabel(blk.type), "workflow:blocks");
        sel.appendChild(el("p", "pc-hint", blockTip(blk.type)));
        panel.appendChild(sel);
      }
    }

    paintRun(wf);
  }

  function blockByKey(wf, key) {
    var parts = String(key).split(".");
    var stack = wf.script;
    var blk = null;
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (p === "then" || p === "else") { stack = blk[p]; continue; }
      blk = stack[Number(p)];
      if (!blk) return null;
    }
    return blk;
  }

  function pct(n) { return Math.round((n || 0) * 100) + "%"; }

  function paintRun(wf) {
    var run = el("div", "wf-section wf-run-box");
    var h = el("h3", "wf-section-title", t("wf_run_title", "Run") + " ");
    h.appendChild(help("workflow:run"));
    run.appendChild(h);

    var r = wf.run;
    if (r && r.status === "waiting") {
      var line = el("p", "wf-run-status is-waiting",
        t("wf_run_waiting", "Waiting for the task queue — {n} task(s)", {
          n: (r.waiting || []).reduce(function (a, w) { return a + (w.tasks || []).length; }, 0),
        }));
      run.appendChild(line);
      run.appendChild(button(t("wf_run_cancel", "Cancel run"), "", function () { cancelRun(wf); }));
    } else if (r) {
      var cls = r.status === "failed" ? "is-failed" : r.status === "canceled" ? "is-canceled" : "is-done";
      var text = t(r.status === "failed" ? "wf_run_failed_status" : "wf_run_" + r.status, r.status) + (r.dryRun ? " (" + t("wf_run_dry_tag", "dry run") + ")" : "");
      run.appendChild(el("p", "wf-run-status " + cls, text));
      if (r.message && r.status === "failed") run.appendChild(el("p", "pc-hint", r.message));
    }

    var btns = el("div", "wf-run-btns");
    btns.appendChild(button(t("wf_run_dry", "Dry run"), "", function () { runIt(wf, true, false); }));
    var routeOnly = button(t("wf_run_route", "Re-route only"), "", function () { runIt(wf, false, true); });
    routeOnly.disabled = !state.canEdit;
    btns.appendChild(routeOnly);
    var full = button(t("wf_run_full", "Run"), "btn-primary", function () { runIt(wf, false, false); });
    full.disabled = !state.canEdit;
    btns.appendChild(full);
    run.appendChild(btns);
    if (!state.options.taskqueue) {
      run.appendChild(el("p", "pc-hint", t(
        "wf_run_inline_hint", "No task queue found: LLM blocks run inside this request and can take a while.")));
    }

    var lr = wf.lastRun;
    if (lr) {
      var lastRunLine = el("p", "pc-hint", t("wf_last_run", "Last run") + ": " +
        String(lr.ts || "").replace("T", " ").slice(0, 16) + " ");
      lastRunLine.appendChild(help("workflow:history"));
      run.appendChild(lastRunLine);
      var total = lr.routed || 0;
      [
        ["verified", "wf_act_verify", "Auto-approved"],
        ["improved", "wf_act_improve", "Improved"],
        ["tickets", "wf_act_review", "Human review"],
        ["flagged", "wf_act_flag", "Flagged"],
        ["llm_reviewed", "wf_act_llm_review", "LLM reviewed"],
      ].forEach(function (k) {
        if (lr[k[0]] == null) return;
        var ln = el("div", "wf-hist");
        ln.appendChild(el("span", "", t(k[1], k[2])));
        ln.appendChild(el("strong", "", lr[k[0]] + (total ? " (" + pct(lr[k[0]] / total) + ")" : "")));
        run.appendChild(ln);
      });
    }
    var oldRun = panel.querySelector(".wf-run-box");
    if (oldRun) oldRun.replaceWith(run); else panel.appendChild(run);
  }

  // --- running -------------------------------------------------------
  function runIt(wf, dry, routeOnly) {
    if (state.dirty) { say(t("wf_save_first", "Save changes before running."), true); return; }
    say(t("wf_running", "Running…"));
    post("/api/ops/workflow", { name: wf.name, route_only: routeOnly, dry_run: dry })
      .then(function (r) {
        say(r.summary || r.error || t("wf_done_msg", "Done."), !r.ok && !!r.error);
        if (dry) {
          var d = r.data || {};
          if (d.run) wf.run = d.run;
          paint();
        } else {
          load(true);
        }
      })
      .catch(function () { say(t("wf_run_failed", "Run failed."), true); });
  }

  function cancelRun(wf) {
    if (!wf.run) return;
    post("/api/workflow/cancel", { id: wf.run.id }).then(function (r) {
      if (!r.ok) { say(r.error || t("wf_run_failed", "Run failed."), true); return; }
      wf.run = r.run;
      paint();
    });
  }

  function stopPoll() { if (state.poll) { clearInterval(state.poll); state.poll = null; } }
  function startPoll() {
    stopPoll();
    var wf = active();
    if (!wf || !wf.run || wf.run.status !== "waiting") return;
    state.poll = setInterval(function () {
      if (typeof document !== "undefined" && document.hidden) return;
      var cur = active();
      if (!cur || !cur.run || cur.run.status !== "waiting") { stopPoll(); return; }
      var rb = { id: cur.run.id };
      if (project()) rb.project = project();
      post("/api/workflow/resume", rb).then(function (r) {
        if (!r.ok) { stopPoll(); return; }
        cur.run = r.run;
        if (r.run.status !== "waiting") { stopPoll(); load(true); return; }
        paintCanvas(cur); paintRun(cur);
      }).catch(stopPoll);
    }, 4000);
    if (typeof document !== "undefined" && !state._pollVis) {
      state._pollVis = true;
      document.addEventListener("visibilitychange", function () {
        if (document.hidden) return;
        var cur = active();
        if (cur && cur.run && cur.run.status === "waiting" && !state.poll) startPoll();
      });
    }
  }

  // --- tabs ----------------------------------------------------------
  function paintTabs() {
    tabs.replaceChildren();
    state.workflows.forEach(function (wf) {
      var b = el("button", "wf-tab" + (wf.name === state.active ? " is-active" : ""), "");
      b.type = "button";
      b.appendChild(document.createTextNode(workflowLabel(wf.name)));
      var ap = appliesTo(wf);
      var chip = el("span", "wf-tab-scope", ap.length === (state.options.locales || []).length && ap.length
        ? t("wf_scope_all", "all") : (ap.join(", ") || "—"));
      b.appendChild(chip);
      b.addEventListener("click", function () {
        state.active = wf.name; state.slot = null; state.selected = null;
        state.undo = []; state.redo = [];
        paint();
      });
      tabs.appendChild(b);
    });
    var add = el("button", "wf-tab wf-tab-add", t("wf_add", "+ Add"));
    add.type = "button";
    add.disabled = !state.canEdit;
    add.addEventListener("click", openNew);
    tabs.appendChild(add);
  }

  function paint() {
    paintTabs();
    undoBtn.disabled = !state.undo.length;
    redoBtn.disabled = !state.redo.length;
    var wf = active();
    if (!wf) {
      canvas.replaceChildren(el("p", "empty-state", t("wf_none", "No workflow.")));
      panel.replaceChildren(); palette.replaceChildren(); return;
    }
    paintPalette();
    paintCanvas(wf);
    paintPanel(wf);
    startPoll();
  }

  // --- templates + modal ----------------------------------------------
  var TEMPLATES = {
    pipeline: {
      label: ["wf_tpl_pipeline", "Default pipeline (translate → score → route)"],
      script: function () {
        return [
          { type: "translate" }, { type: "rescore" },
          { type: "if", field: "score", op: "ge", value: 0.8, then: [{ type: "verify" }],
            "else": [{ type: "if", field: "score", op: "le", value: 0.55,
              then: [{ type: "improve" }], "else": [{ type: "review_ticket" }] }] },
        ];
      },
    },
    reroute: {
      label: ["wf_tpl_reroute", "Re-route existing scores"],
      script: function () {
        return [
          { type: "if", field: "score", op: "ge", value: 0.8, then: [{ type: "verify" }],
            "else": [{ type: "review_ticket" }] },
        ];
      },
    },
    approve: {
      label: ["wf_tpl_approve", "Auto-approve only"],
      script: function () {
        return [{ type: "if", field: "score", op: "ge", value: 0.9, then: [{ type: "verify" }], "else": [] }];
      },
    },
    blank: { label: ["wf_tpl_blank", "Blank"], script: function () { return []; } },
  };

  // The server list wins; TEMPLATES above is the offline fallback.
  function presetList() {
    var server = (state.options && state.options.presets) || [];
    if (!server.length) {
      return Object.keys(TEMPLATES).map(function (k) {
        return { id: k, label: t(TEMPLATES[k].label[0], TEMPLATES[k].label[1]), build: TEMPLATES[k].script };
      });
    }
    return server.map(function (p) {
      var local = TEMPLATES[p.id];
      return {
        id: p.id,
        label: local ? t(local.label[0], local.label[1]) : t("wf_tpl_" + p.id, p.label),
        build: function () { return clone(p.script); },
      };
    });
  }

  function openNew() {
    if (!state.canEdit) return;
    var shade = el("div", "br-shade");
    var box = el("div", "br-modal");
    box.setAttribute("role", "dialog");
    box.appendChild(el("h2", "", t("wf_new_title", "New workflow")));
    var f = el("label", "br-field");
    f.appendChild(el("span", "", t("wf_name", "Workflow name")));
    var input = el("input", "");
    input.type = "text";
    f.appendChild(input);
    box.appendChild(f);
    var tf = el("label", "br-field");
    tf.appendChild(el("span", "", t("wf_template", "Start from")));
    var tsel = el("select", "pc-select");
    var presetsNow = presetList();
    presetsNow.forEach(function (p) {
      var o = el("option", "", p.label);
      o.value = p.id;
      tsel.appendChild(o);
    });
    tf.appendChild(tsel);
    box.appendChild(tf);
    var err = el("p", "pc-status is-error", "");
    box.appendChild(err);
    var foot = el("div", "br-actions br-foot");
    function close() { shade.remove(); }
    foot.appendChild(button(t("wf_cancel", "Cancel"), "", close));
    foot.appendChild(button(t("wf_create", "Create"), "btn-primary", function () {
      var name = input.value.trim();
      if (!name || state.workflows.some(function (w) { return w.name === name; })) {
        err.textContent = t("wf_name_invalid", "Name must be unique and not empty.");
        return;
      }
      state.workflows.push({
        name: name, maxImproveLoops: 2, notify: "none", locales: null, warnings: [],
        script: presetsNow.filter(function (p) { return p.id === tsel.value; })[0].build(),
      });
      state.active = name; state.undo = []; state.redo = [];
      touch(); close(); paint(); save();
    }));
    box.appendChild(foot);
    shade.appendChild(box);
    shade.addEventListener("click", function (e) { if (e.target === shade) close(); });
    document.body.appendChild(shade);
    input.focus();
  }

  function duplicate() {
    var wf = active();
    if (!wf || !state.canEdit) return;
    var base = wf.name + "-copy", name = base, n = 2;
    while (state.workflows.some(function (w) { return w.name === name; })) name = base + n++;
    var c = clone(wf);
    c.name = name; c.locales = null; c.lastRun = null; c.run = null;
    state.workflows.push(c);
    state.active = name; state.undo = []; state.redo = []; state.selected = null;
    touch(); paint();
    say(t("wf_duplicated", "Duplicated as {name} — pick its locales, then Save.", { name: name }));
  }

  function openCopy() {
    var wf = active();
    if (!wf) return;
    if (state.dirty) { say(t("wf_copy_save_first", "Save your changes before copying."), true); return; }
    var shade = el("div", "br-shade");
    var box = el("div", "br-modal");
    box.setAttribute("role", "dialog");
    box.appendChild(el("h2", "", t("wf_copy_title", "Copy workflow to another project")));
    var f = el("label", "br-field");
    f.appendChild(el("span", "", t("wf_copy_project", "Target project")));
    var sel = el("select", "pc-select");
    var cur = project();
    var src = document.getElementById("project-select");
    Array.prototype.forEach.call(src ? src.options : [], function (o) {
      if (!o.value || o.value === cur) return;
      var op = el("option", "", o.textContent); op.value = o.value; sel.appendChild(op);
    });
    f.appendChild(sel);
    box.appendChild(f);
    var nf = el("label", "br-field");
    nf.appendChild(el("span", "", t("wf_name", "Workflow name")));
    var nin = el("input", ""); nin.type = "text"; nin.value = wf.name;
    nf.appendChild(nin);
    box.appendChild(nf);
    var ow = el("label", "pc-check");
    var owCb = el("input", ""); owCb.type = "checkbox";
    ow.appendChild(owCb);
    ow.appendChild(el("span", "", t("wf_copy_overwrite", "Overwrite if it exists")));
    box.appendChild(ow);
    var err = el("p", "pc-status is-error", "");
    box.appendChild(err);
    var foot = el("div", "br-actions br-foot");
    function close() { shade.remove(); }
    foot.appendChild(button(t("wf_cancel", "Cancel"), "", close));
    var go = button(t("wf_copy", "Copy"), "btn-primary", function () {
      if (!sel.value) { err.textContent = t("wf_copy_no_target", "No other project available."); return; }
      post("/api/workflow/copy", {
        name: wf.name, toProject: sel.value, newName: nin.value.trim() || wf.name, overwrite: owCb.checked,
      }).then(function (r) {
        if (!r.ok) { err.textContent = r.error || t("wf_copy_failed", "Copy failed."); return; }
        close();
        var msg = t("wf_copied", "Copied to {project}.", { project: sel.value });
        if ((r.droppedLocales || []).length) {
          msg += " " + t("wf_copy_dropped", "Locales not in the target were dropped: {locs}.",
            { locs: r.droppedLocales.join(", ") });
        }
        say(msg);
      }).catch(function () { err.textContent = t("wf_copy_failed", "Copy failed."); });
    });
    go.disabled = !sel.options.length;
    foot.appendChild(go);
    box.appendChild(foot);
    shade.appendChild(box);
    shade.addEventListener("click", function (e) { if (e.target === shade) close(); });
    document.body.appendChild(shade);
  }

  // --- load / save ---------------------------------------------------
  function save() {
    if (!state.canEdit) return;
    var body = { workflows: {}, notifyWebhook: state.hookDraft || "" };
    state.workflows.forEach(function (w) {
      body.workflows[w.name] = {
        script: w.script, maxImproveLoops: w.maxImproveLoops,
        notify: w.notify || "none", locales: w.locales || [],
      };
    });
    say(t("wf_saving", "Saving…"));
    post("/api/workflow", body).then(function (r) {
      if (!r.ok) { say(r.error || t("wf_save_failed", "Save failed."), true); return; }
      state.dirty = false; state.hookDraft = "";
      saveBtn.textContent = t("wf_save", "Save");
      say(t("wf_saved", "Saved."));
      load(true);
    }).catch(function () { say(t("wf_save_failed", "Save failed."), true); });
  }

  function load(keep) {
    var q = project() ? "?project=" + encodeURIComponent(project()) : "";
    getJson("/api/workflow" + q).then(function (data) {
      if (data.ok === false) { say(data.error || t("wf_load_failed", "Could not load workflows."), true); return; }
      state.workflows = (data.workflows || []).map(function (w) {
        w.script = clone(w.script || []);
        return w;
      });
      state.options = data.options || {};
      if (data.canEdit === false) state.canEdit = false;
      if (!state.workflows.length) {
        state.workflows = [{
          name: "default", maxImproveLoops: 2, notify: "none", locales: null, warnings: [],
          script: TEMPLATES.pipeline.script(),
        }];
      }
      if (!keep || !active()) state.active = state.workflows[0].name;
      saveBtn.disabled = !state.canEdit;
      newBtn.disabled = !state.canEdit;
      dupBtn.disabled = !state.canEdit;
      paint();
    }).catch(function () { say(t("wf_load_failed", "Could not load workflows."), true); });
  }

  function relabelHead() {
    h1.textContent = t("wf_title", "Workflow automation");
    if (sub.firstChild && sub.firstChild.nodeType === 3) {
      sub.firstChild.textContent = t(
        "wf_subtitle_blocks",
        "Build the pipeline from blocks — they run top to bottom, in the order you stack them ",
      ) + " ";
    }
    newBtn.textContent = t("wf_new", "+ New workflow");
    undoBtn.title = t("wf_undo", "Undo");
    redoBtn.title = t("wf_redo", "Redo");
    saveBtn.textContent = state.dirty
      ? t("wf_save", "Save") + " •"
      : t("wf_save", "Save");
    dupBtn.textContent = t("wf_duplicate", "Duplicate");
    copyBtn.textContent = t("wf_copy_to", "Copy to project…");
  }

  var lastProject = project();
  var projSel = document.getElementById("project-select");
  if (projSel) {
    projSel.addEventListener("change", function () {
      if (project() === lastProject) return;
      lastProject = project();
      stopPoll();
      state.active = ""; state.selected = null; state.slot = null;
      state.undo = []; state.redo = []; state.dirty = false; state.hookDraft = "";
      saveBtn.textContent = t("wf_save", "Save");
      say("");
      load(false);
    });
  }

  var ready = (window.uiLocale && typeof window.uiLocale.whenReady === "function")
    ? window.uiLocale.whenReady()
    : Promise.resolve();
  ready.then(function () {
    relabelHead();
    load(false);
  });
})();
