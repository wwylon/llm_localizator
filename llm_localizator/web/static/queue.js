(function () {
  // Queue page (W3): the project's taskqueue blueprints with their status, read-only. The page never starts the
  // daemon; the only write is "switch engine" (Admin), which rewrites blueprints that already exist.
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "queue" || !root) return;

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

  function apiGet(path, params) {
    if (window.LLMApi && LLMApi.apiGet) return LLMApi.apiGet(path, params);
    var qs = new URLSearchParams(params || {}).toString();
    return fetch(path + (qs ? "?" + qs : ""), { credentials: "same-origin" }).then(function (r) { return r.json(); });
  }

  function opPost(command, body) {
    body.project = project();
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost("/api/ops/" + command, body);
    return fetch("/api/ops/" + command, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function vramText(v) {
    if (v === null || v === undefined) return "?";
    return Number(v) > 0 ? Number(v) + " GiB" : "—";
  }

  function laneBadge(lane) {
    var labels = { cloud: uiT("q_lane_cloud", "cloud"), gpu: uiT("q_lane_gpu", "GPU"), cpu: uiT("q_lane_cpu", "CPU") };
    return el("span", "settings-badge q-lane q-lane-" + lane, labels[lane] || lane || "?");
  }

  function banner(daemon) {
    if (daemon.running && daemon.db) return null;
    var box = el("div", "settings-card q-banner");
    box.setAttribute("role", "status");
    var dot = el("span", "status-dot status-offline");
    box.appendChild(dot);
    var text = !daemon.db
      ? uiT("q_db_missing", "The taskqueue database was not found or could not be read, so task status is unknown.")
      : uiT("q_daemon_down", "The taskqueue daemon is not running: queued tasks wait until it starts.");
    box.appendChild(el("span", "", " " + text));
    box.appendChild(el("p", "field-hint", uiT(
      "q_daemon_hint", "Start it from a terminal (tqdaemon); this page only reads the queue.")));
    return box;
  }

  function table(tasks) {
    var t = el("table", "settings-table q-table");
    var head = document.createElement("thead");
    var hr = document.createElement("tr");
    [
      uiT("q_col_task", "Task"), uiT("q_col_status", "Status"), uiT("q_col_engine", "Engine"),
      uiT("q_col_model", "Model"), uiT("q_col_vram", "VRAM"), uiT("q_col_lane", "Lane"),
      uiT("q_col_last", "Last run"),
    ].forEach(function (label) { hr.appendChild(el("th", "", label)); });
    head.appendChild(hr);
    t.appendChild(head);
    var body = document.createElement("tbody");
    tasks.forEach(function (task) {
      var tr = document.createElement("tr");
      tr.dataset.task = task.task;
      var name = el("td", "settings-mono", task.task);
      name.title = task.file;
      tr.appendChild(name);
      var st = el("td", "");
      st.appendChild(el("span", "settings-badge q-status q-status-" + String(task.status).replace(/\s+/g, "-"),
        task.status));
      tr.appendChild(st);
      tr.appendChild(el("td", "settings-mono", task.engine || "—"));
      tr.appendChild(el("td", "settings-mono", task.model || "—"));
      tr.appendChild(el("td", "", vramText(task.vram)));
      var lane = el("td", "");
      lane.appendChild(laneBadge(task.lane));
      if (task.error) lane.appendChild(el("span", "field-hint", " " + task.error));
      tr.appendChild(lane);
      var last = task.lastRun;
      tr.appendChild(el("td", "field-hint", last
        ? (last.status || "") + (last.finishedAt ? " · " + last.finishedAt : "") + (last.lastLine ? " · " + last.lastLine : "")
        : "—"));
      body.appendChild(tr);
    });
    t.appendChild(body);
    return t;
  }

  function switchCard(data) {
    var box = el("div", "settings-card q-switch");
    box.hidden = true;
    var head = el("div", "settings-card-head");
    head.appendChild(el("div", "section-label", uiT("q_switch_title", "Switch engine for queued jobs")));
    head.appendChild(el("p", "field-hint", uiT(
      "q_switch_hint",
      "Rewrites the blueprints listed above with --engine baked in and the GPU reservation sized for it. " +
      "No new blueprint is created and the project config is not changed.")));
    box.appendChild(head);
    var row = el("div", "settings-actions");
    var select = el("select", "q-engine-select");
    select.setAttribute("aria-label", uiT("q_col_engine", "Engine"));
    var preview = el("button", "btn", uiT("q_preview", "Preview"));
    preview.type = "button";
    var apply = el("button", "btn btn-primary", uiT("q_apply", "Rewrite blueprints"));
    apply.type = "button";
    apply.disabled = true;
    row.appendChild(select);
    row.appendChild(preview);
    row.appendChild(apply);
    box.appendChild(row);
    var out = el("pre", "settings-mono q-out");
    out.hidden = true;
    box.appendChild(out);

    function run(dry) {
      if (!select.value) return;
      preview.disabled = apply.disabled = true;
      opPost("queue-engine", { engine_id: select.value, dry_run: dry }).then(function (res) {
        out.hidden = false;
        out.textContent = [res.summary || res.error || ""].concat(res.lines || []).join("\n");
        apply.disabled = !dry || !res.ok;
        preview.disabled = false;
        if (!dry && res.ok) load();
      }).catch(function (err) {
        out.hidden = false;
        out.textContent = String(err);
        preview.disabled = false;
      });
    }
    preview.addEventListener("click", function () { run(true); });
    apply.addEventListener("click", function () { run(false); });
    select.addEventListener("change", function () { apply.disabled = true; out.hidden = true; });

    if (!data.tasks.length) return box;
    // Admin only (the engine list op is Admin): anyone else never sees the card.
    opPost("engine", { action: "list" }).then(function (res) {
      if (!res || res.ok === false || !res.data) return;
      (res.data.engines || []).forEach(function (engine) {
        var opt = el("option", "", engine.id + (engine.current ? " (" + uiT("q_current", "current") + ")" : ""));
        opt.value = engine.id;
        select.appendChild(opt);
      });
      box.hidden = false;
    }).catch(function () {});
    return box;
  }

  function paint(data) {
    root.replaceChildren();
    var b = banner(data.daemon || {});
    if (b) root.appendChild(b);
    var card = el("div", "settings-card");
    var head = el("div", "settings-card-head");
    head.appendChild(el("div", "section-label", uiT("q_title", "Queued jobs")));
    head.appendChild(el("p", "field-hint", uiT(
      "q_hint", "Blueprints in experiments/operator_queue that run llm-localizator, with their taskqueue status.")));
    card.appendChild(head);
    if (!data.tasks || !data.tasks.length) {
      card.appendChild(el("p", "empty-state", uiT(
        "q_empty", "No blueprints yet. Create them with: llm-localizator init <project> --taskqueue")));
    } else {
      card.appendChild(table(data.tasks));
    }
    root.appendChild(card);
    root.appendChild(switchCard(data));
  }

  function load() {
    return apiGet("/api/queue", { project: project() }).then(function (data) {
      if (!data || data.ok === false) {
        root.replaceChildren(el("p", "empty-state", (data && data.error) || uiT("q_load_failed", "Could not load the queue.")));
        return;
      }
      paint(data);
    }).catch(function () {
      root.replaceChildren(el("p", "empty-state", uiT("q_load_failed", "Could not load the queue.")));
    });
  }

  var select = document.getElementById("project-select");
  if (select) select.addEventListener("change", load);
  load();
})();
