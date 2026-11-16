(function () {
  var drawer = document.getElementById("ops-drawer");
  var button = document.getElementById("ops-btn");
  if (!drawer || !button) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  var commands = {};
  var current = "status";
  var abort = null;

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

  function log(text) {
    var node = document.getElementById("ops-log");
    if (node) node.textContent = text;
  }

  button.addEventListener("click", function () {
    drawer.hidden = !drawer.hidden;
    if (!drawer.hidden) loadCommands();
  });
  document.getElementById("ops-close").addEventListener("click", function () {
    drawer.hidden = true;
  });

  function loadCommands() {
    if (Object.keys(commands).length) return;
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/commands", {})
      : fetch("/api/commands").then(function (response) { return response.json(); });
    get.then(function (payload) {
      commands = payload.commands || {};
      commands.export = commands.export || { fields: [] };
      commands.import = commands.import || { fields: [] };
      var nav = document.getElementById("ops-commands");
      nav.replaceChildren();
      Object.keys(commands).sort().forEach(function (name) {
        var item = el("button", "btn", name);
        item.type = "button";
        item.addEventListener("click", function () {
          current = name;
          paintForm();
        });
        nav.appendChild(item);
      });
      paintForm();
    });
  }

  function paintForm() {
    var form = document.getElementById("ops-form");
    var desc = document.getElementById("ops-desc");
    form.replaceChildren();
    desc.textContent = current;
    if (current === "export") return paintExport(form);
    if (current === "import") return paintImport(form);
    var fields = (commands[current] && commands[current].fields) || [];
    fields.forEach(function (field) {
      if (field.name === "project" || field.name === "config") return;
      var label = el("label", "field", field.name);
      var input;
      if (field.type === "bool") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.checked = !!field.default;
      } else {
        input = document.createElement("input");
        input.type = "text";
        if (field.default != null) input.value = String(field.default);
      }
      input.dataset.field = field.name;
      input.dataset.type = field.type || "str";
      label.appendChild(input);
      form.appendChild(label);
    });
    if (!form.children.length) {
      form.appendChild(el(
        "p", "empty-state",
        uiT("ops_need_locale", "Select at least one locale when the command needs one."),
      ));
    }
    if (QUOTED[current]) paintQuote(form);
  }

  // Commands that call a model get a "what will this cost / how long" line before running.
  // Commands that show an Estimate button; review/rescore price judging translated strings (M6 spend estimate).
  var QUOTED = { translate: 1, improve: 1, review: 1, rescore: 1 };

  function fmtEta(seconds) {
    if (seconds == null) return uiT("ops_eta_unknown", "time unknown (no earlier runs)");
    if (seconds < 90) {
      return uiT("ops_eta_s", "about {n} s").replace("{n}", String(Math.max(1, Math.round(seconds))));
    }
    if (seconds < 5400) {
      return uiT("ops_eta_min", "about {n} min").replace("{n}", String(Math.round(seconds / 60)));
    }
    return uiT("ops_eta_h", "about {n} h").replace("{n}", (seconds / 3600).toFixed(1));
  }

  function paintQuote(form) {
    var line = el("p", "excerpt");
    line.id = "ops-quote";
    var btn = el("button", "btn", uiT("ops_estimate", "Estimate"));
    btn.type = "button";
    btn.addEventListener("click", function () {
      var body = readBody();
      line.textContent = uiT("ops_estimating", "Estimating…");
      var estBody = {
        project: project(),
        locales: body.locales,
        keys: body.keys,
        namespace: body.namespace,
        namespaces: body.namespaces,
        purpose: (current === "review" || current === "rescore") ? current : "translate",
      };
      var post = (window.LLMApi && LLMApi.apiPost)
        ? LLMApi.apiPost("/api/ops/estimate-cost", estBody)
        : fetch("/api/ops/estimate-cost", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(estBody),
          }).then(function (response) { return response.json(); });
      post.then(function (data) {
        var est = (data && data.data) || {};
        if (!data || data.ok === false) {
          line.textContent = (data && data.summary) || uiT("ops_estimate_failed", "Estimate failed.");
          return;
        }
        var cost = est.local === false
          ? uiT("ops_cost_cloud", "up to ${max} (budget left ${left})")
            .replace("${max}", String(est.max_usd))
            .replace("${left}", String(est.remaining_usd))
          : uiT("ops_cost_local", "no cloud cost (local model)");
        line.textContent = est.purpose === "review" || est.purpose === "rescore"
          ? uiT("ops_quote_judged", "{n} translated strings to judge, {cost}")
            .replace("{n}", String(est.keys || 0))
            .replace("{cost}", cost)
          : uiT("ops_quote_line", "{n} strings due, {cost}, {eta}")
            .replace("{n}", String(est.keys || 0))
            .replace("{cost}", cost)
            .replace("{eta}", fmtEta(est.eta_s));
      }).catch(function (err) { line.textContent = String(err.message || err); });
    });
    form.appendChild(btn);
    form.appendChild(line);
  }

  function paintExport(form) {
    var format = document.createElement("select");
    format.id = "ops-format";
    ["csv", "xliff", "json", "xlsx"].forEach(function (name) {
      format.appendChild(el("option", "", name));
    });
    var layout = document.createElement("select");
    layout.id = "ops-layout";
    ["single", "per-locale", "per-namespace"].forEach(function (name) {
      layout.appendChild(el("option", "", name));
    });
    var files = document.createElement("input");
    files.id = "ops-file-count";
    files.type = "number";
    files.min = "1";
    files.value = "1";
    form.appendChild(labeled("format", format));
    form.appendChild(labeled("layout", layout));
    form.appendChild(labeled("files", files));
  }

  function paintImport(form) {
    var files = document.createElement("input");
    files.id = "ops-import-files";
    files.type = "file";
    files.multiple = true;
    files.accept = ".csv,.xlsx,.json,.xliff,.xlf,.zip";
    var who = document.createElement("input");
    who.id = "ops-localized-by";
    who.placeholder = uiT("ops_localized_by_ph", "localized by");
    form.appendChild(labeled(uiT("ops_files", "files"), files));
    form.appendChild(labeled(uiT("op_localized_by", "Localized by"), who));
  }

  function labeled(text, input) {
    var label = el("label", "field", text);
    label.appendChild(input);
    return label;
  }

  function readBody() {
    var payload = { project: project() };
    if (current === "export") {
      payload.format = document.getElementById("ops-format").value;
      payload.layout = document.getElementById("ops-layout").value;
      payload.file_count = Number(document.getElementById("ops-file-count").value || "1");
      return payload;
    }
    document.querySelectorAll("#ops-form [data-field]").forEach(function (input) {
      var name = input.dataset.field;
      if (input.dataset.type === "bool") payload[name] = input.checked;
      else if (input.value !== "") payload[name] = input.value;
    });
    if (payload.locales && typeof payload.locales === "string") {
      payload.locales = payload.locales.split(",").map(function (part) { return part.trim(); }).filter(Boolean);
    }
    return payload;
  }

  function run(dry) {
    var payload = readBody();
    payload.dry_run = !!dry;
    if (current === "export") return runExport(payload);
    if (current === "import") return runImport(payload);
    payload.stream = true;
    var stop = document.getElementById("ops-stop-btn");
    stop.hidden = false;
    abort = new AbortController();
    stop.onclick = function () { if (abort) abort.abort(); };
    var hdrs = (window.LLMApi && LLMApi.authHeaders)
      ? LLMApi.authHeaders({ "Content-Type": "application/json", "Accept": "text/event-stream" })
      : { "Content-Type": "application/json", "Accept": "text/event-stream" };
    return fetch("/api/ops/" + current, {
      method: "POST",
      headers: hdrs,
      body: JSON.stringify(payload),
      signal: abort.signal,
    }).then(function (response) {
      var type = response.headers.get("Content-Type") || "";
      if (type.indexOf("text/event-stream") >= 0 && response.body) return readStream(response);
      return response.json().then(function (data) { log(data.summary || JSON.stringify(data)); });
    }).catch(function (err) {
      log(String(err.message || err));
    }).then(function () { stop.hidden = true; return showReportParts(payload); });
  }

  function showReportParts(payload) {
    var old = document.getElementById("ops-parts");
    if (old) old.remove();
    if (current !== "agent-backlog" && current !== "agent-hardcoded") return null;
    // No folder typed: the server looks where the op writes by default (engine data home, ADR-112).
    var dir = payload.out_dir || "";
    var partsQuery = { project: project(), dir: dir, kind: current };
    var query = "?project=" + encodeURIComponent(project()) + "&dir=" + encodeURIComponent(dir)
      + "&kind=" + encodeURIComponent(current);
    var getParts = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/report-parts", partsQuery).catch(function () { return null; })
      : fetch("/api/report-parts" + query).then(function (r) { return r.ok ? r.json() : null; });
    return getParts.then(function (data) {
      var node = document.getElementById("ops-log");
      if (!data || !data.parts || !data.parts.length || !node) return;
      var list = document.createElement("div");
      list.id = "ops-parts";
      data.parts.forEach(function (part) {
        var link = document.createElement("a");
        link.href = "/api/report-part" + query + "&name=" + encodeURIComponent(part.name);
        link.textContent = part.name + " (" + part.size + " B)";
        link.download = part.name;
        link.style.display = "block";
        list.appendChild(link);
      });
      node.parentNode.insertBefore(list, node.nextSibling);
    }).catch(function () { return null; });
  }

  // improve keeps targets edited outside the run (M6): list them with a link to each string in the editor.
  function paintSkipped(data) {
    var old = document.getElementById("ops-skipped");
    if (old) old.remove();
    var rows = (data && data.skippedExternal) || [];
    var host = document.getElementById("ops-log");
    if (!rows.length || !host || !host.parentNode) return;
    var box = el("div", "ops-skipped");
    box.id = "ops-skipped";
    box.appendChild(el("p", "muted", uiT(
      "ops_skipped_external", "Edited outside the run and kept ({n}); run adopt to keep them for good:",
    ).replace("{n}", String(rows.length))));
    var list = el("ul");
    rows.slice(0, 50).forEach(function (row) {
      var item = el("li");
      var link = el("a", "", row.locale + " · " + (row.namespace ? row.namespace + "." : "") + row.key);
      link.href = "/app/editor?locale=" + encodeURIComponent(row.locale)
        + "&namespace=" + encodeURIComponent(row.namespace || "")
        + "&key=" + encodeURIComponent(row.key || "");
      item.appendChild(link);
      list.appendChild(item);
    });
    box.appendChild(list);
    host.parentNode.insertBefore(box, host.nextSibling);
  }

  function readStream(response) {
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
            if (event.line) log(event.line);
            if (event.summary) log(event.summary);
            if (event.type === "result") paintSkipped(event.data);
          } catch (err) {
            log(line);
          }
        });
        return pump();
      });
    }
    return pump();
  }

  function runExport(payload) {
    var post = (window.LLMApi && LLMApi.apiPost)
      ? LLMApi.apiPost("/api/export", payload)
      : fetch("/api/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }).then(function (response) { return response.json(); });
    return post.then(function (data) {
      log(data.summary || data.error || "exported");
      if (!data.file_base64) return;
      var binary = atob(data.file_base64);
      var bytes = new Uint8Array(binary.length);
      for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      var link = el("a", "", data.filename || "export");
      link.href = URL.createObjectURL(new Blob([bytes], { type: data.content_type }));
      link.download = data.filename || "export";
      link.click();
    });
  }

  function runImport(payload) {
    var files = document.getElementById("ops-import-files").files;
    if (!files || !files.length) {
      log(uiT("op_select_locale_file", "Select at least one locale file."));
      return;
    }
    var reader = new FileReader();
    reader.onload = function () {
      var name = files[0].name || "";
      var fmt = name.endsWith(".json") ? "json" : (name.endsWith(".xliff") || name.endsWith(".xlf") ? "xliff" : "csv");
      var body = {
        project: project(),
        format: fmt,
        dry_run: payload.dry_run,
        model: (document.getElementById("ops-localized-by") || {}).value || "import",
      };
      if (/\.xlsx$/i.test(name)) {
        var bytes = new Uint8Array(reader.result), bin = "";
        for (var i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
        body = { project: project(), format: "csv", dry_run: payload.dry_run, filename: name, xlsx_base64: btoa(bin),
          model: body.model };
      } else {
        body[fmt === "xliff" ? "xliff" : fmt] = String(reader.result || "");
      }
      var post = (window.LLMApi && LLMApi.apiPost)
        ? LLMApi.apiPost("/api/import", body)
        : fetch("/api/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }).then(function (response) { return response.json(); });
      post.then(function (data) {
        log(data.summary || data.error || JSON.stringify(data));
      });
    };
    if (/\.xlsx$/i.test(files[0].name || "")) reader.readAsArrayBuffer(files[0]);
    else reader.readAsText(files[0]);
  }

  document.getElementById("ops-dry-btn").addEventListener("click", function () { run(true); });
  document.getElementById("ops-run-btn").addEventListener("click", function () { run(false); });
})();
