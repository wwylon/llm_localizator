(function () {
  var body = document.getElementById("page-body");
  var select = document.getElementById("project-select");
  if (!body || !select) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  var state = {
    project: "",
    query: "",
    domains: {},
    locales: [],
    activeLocales: [],
    sourceLocale: "en",
    visibleLocales: [],
    editing: null,
    importPending: null,
    status: "",
    modalShowAllLocales: false,
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function storageKey(project) {
    return "ll.glossary.visibleLocales." + project;
  }

  function loadVisible(project, locales, defaults) {
    var fallback = (defaults && defaults.length) ? defaults.slice() : locales.slice();
    var saved = [];
    try {
      saved = JSON.parse(localStorage.getItem(storageKey(project)) || "[]");
    } catch (err) {
      saved = [];
    }
    if (!Array.isArray(saved)) saved = [];
    var next = locales.filter(function (code) {
      return saved.indexOf(code) >= 0;
    });
    if (!next.length) next = fallback.filter(function (code) {
      return locales.indexOf(code) >= 0;
    });
    if (!next.length) next = locales.slice();
    return next;
  }

  function saveVisible() {
    try {
      localStorage.setItem(
        storageKey(state.project),
        JSON.stringify(state.visibleLocales),
      );
    } catch (err) { /* ignore quota */ }
  }

  function post(path, payload) {
    payload.project = state.project;
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost(path, payload);
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (response) { return response.json(); });
  }

  function termCount() {
    return rows("").length;
  }

  function subtitleText() {
    var n = termCount();
    var template = n === 1
      ? uiT("gloss_sub_one", "{n} term · injected into every LLM translation prompt")
      : uiT("gloss_sub_many", "{n} terms · injected into every LLM translation prompt");
    return template.replace("{n}", String(n));
  }

  function domainLabel(domain) {
    var value = domain || "global";
    if (value === "global") return uiT("gloss_domain_global", "global");
    return value;
  }

  function setSubtitle() {
    var text = subtitleText();
    var sub = document.getElementById("glossary-sub");
    if (sub) sub.textContent = text;
    var fallback = document.getElementById("glossary-sub-fallback");
    if (fallback) fallback.textContent = text;
    return text;
  }

  function load() {
    state.project = select.value;
    state.editing = null;
    state.importPending = null;
    body.replaceChildren(el("p", "empty-state", uiT("dash_loading", "Loading…")));
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/glossary", { project: state.project })
      : fetch("/api/glossary?project=" + encodeURIComponent(state.project)).then(function (response) {
          return response.json();
        });
    get.then(function (payload) {
      if (!payload.ok) throw new Error(payload.error || "no glossary");
      state.domains = payload.domains || {};
      state.locales = payload.locales || [];
      state.activeLocales = payload.activeLocales || state.locales.slice();
      state.sourceLocale = payload.sourceLocale || "en";
      state.visibleLocales = loadVisible(
        state.project,
        state.locales,
        state.activeLocales,
      );
      render();
    }).catch(function (err) {
      body.replaceChildren(el("p", "empty-state", String(err.message || err)));
      var sub = document.getElementById("glossary-sub");
      if (sub) sub.textContent = "";
    });
  }

  function rows(needleOverride) {
    var out = [];
    var needle = (needleOverride != null ? needleOverride : state.query).trim().toLowerCase();
    Object.keys(state.domains).sort().forEach(function (domain) {
      var part = state.domains[domain] || {};
      (part.doNotTranslate || []).forEach(function (term) {
        if (!needle || String(term).toLowerCase().indexOf(needle) >= 0) {
          out.push({ domain: domain, kind: "dnt", term: term, data: {} });
        }
      });
      Object.keys(part.terms || {}).sort().forEach(function (term) {
        var data = part.terms[term] || {};
        var blob = term + " " + JSON.stringify(data);
        if (!needle || blob.toLowerCase().indexOf(needle) >= 0) {
          out.push({ domain: domain, kind: "term", term: term, data: data });
        }
      });
    });
    return out;
  }

  function render() {
    document.querySelectorAll(".glossary-modal").forEach(function (node) {
      node.remove();
    });
    body.replaceChildren();
    setSubtitle();
    if (!document.getElementById("glossary-sub")) {
      body.appendChild(el("p", "page-sub", subtitleText())).id = "glossary-sub-fallback";
    }

    var banner = el("div", "glossary-banner");
    banner.appendChild(el(
      "span",
      "",
      uiT(
        "gloss_banner",
        "Glossary terms are automatically included in translation prompts for "
          + "their respective locales. Add preferred translations for brand names, "
          + "technical terms, and domain-specific vocabulary.",
      ),
    ));
    body.appendChild(banner);

    var bar = el("div", "toolbar glossary-toolbar");
    var search = document.createElement("input");
    search.type = "search";
    search.placeholder = uiT("gloss_search_ph", "Search terms…");
    search.setAttribute("aria-label", uiT("gloss_search_aria", "Search terms"));
    search.value = state.query;
    search.addEventListener("input", function () {
      state.query = search.value;
      paintTable();
      setSubtitle();
    });
    bar.appendChild(search);
    bar.appendChild(localePicker());
    var add = el("button", "btn btn-primary", uiT("gloss_add_term", "+ Add term"));
    add.type = "button";
    add.addEventListener("click", function () {
      state.modalShowAllLocales = false;
      state.editing = {
        action: "add",
        domain: "global",
        kind: "term",
        term: "",
        data: {},
      };
      render();
    });
    bar.appendChild(add);
    body.appendChild(bar);

    if (state.status) {
      body.appendChild(el("p", "glossary-status", state.status));
    }

    var host = el("div", "glossary-table-wrap");
    host.id = "glossary-rows";
    body.appendChild(host);
    paintTable();

    body.appendChild(footerBar());

    if (state.editing) {
      document.body.appendChild(modal());
    }
  }

  function localePicker() {
    var wrap = el("div", "glossary-locale-picker");
    var toggle = el("button", "btn", uiT("set_tab_locales", "Locales"));
    toggle.type = "button";
    toggle.setAttribute("aria-haspopup", "true");
    toggle.setAttribute("aria-expanded", "false");
    var panel = el("div", "glossary-locale-menu");
    panel.hidden = true;
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", uiT("gloss_visible_locales", "Visible locales"));

    function paintChecks() {
      panel.replaceChildren();
      if (!state.locales.length) {
        panel.appendChild(el("p", "empty-state", uiT("gloss_no_locales", "No locales.")));
        return;
      }
      state.locales.forEach(function (locale) {
        var label = el("label", "glossary-locale-option");
        var box = document.createElement("input");
        box.type = "checkbox";
        box.value = locale;
        box.checked = state.visibleLocales.indexOf(locale) >= 0;
        box.disabled = box.checked && state.visibleLocales.length === 1;
        box.addEventListener("change", function () {
          if (box.checked) {
            if (state.visibleLocales.indexOf(locale) < 0) {
              state.visibleLocales = state.locales.filter(function (code) {
                return state.visibleLocales.indexOf(code) >= 0 || code === locale;
              });
            }
          } else {
            if (state.visibleLocales.length <= 1) {
              box.checked = true;
              return;
            }
            state.visibleLocales = state.visibleLocales.filter(function (code) {
              return code !== locale;
            });
          }
          saveVisible();
          paintChecks();
          paintTable();
        });
        label.appendChild(box);
        label.appendChild(document.createTextNode(" " + locale));
        panel.appendChild(label);
      });
    }

    toggle.addEventListener("click", function (event) {
      event.stopPropagation();
      var open = panel.hidden;
      document.querySelectorAll(".glossary-locale-menu").forEach(function (menu) {
        if (menu !== panel) menu.hidden = true;
      });
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) paintChecks();
    });
    wrap.appendChild(toggle);
    wrap.appendChild(panel);
    return wrap;
  }

  function paintTable() {
    var host = document.getElementById("glossary-rows");
    if (!host) return;
    host.replaceChildren();
    var items = rows();
    if (!items.length) {
      host.appendChild(el("p", "empty-state", uiT("gloss_no_terms", "No terms.")));
      return;
    }
    var table = document.createElement("table");
    table.className = "glossary-table";
    var head = document.createElement("tr");
    [
      uiT("gloss_col_term", "Term"),
      uiT("gloss_col_domain", "Domain"),
      uiT("set_col_type", "Type"),
    ].forEach(function (name) {
      head.appendChild(el("th", "", name));
    });
    state.visibleLocales.forEach(function (locale) {
      head.appendChild(el("th", "", locale));
    });
    head.appendChild(el("th", "", ""));
    table.appendChild(head);

    items.forEach(function (item) {
      var row = document.createElement("tr");
      row.appendChild(el("td", "glossary-term", item.term));
      row.appendChild(el("td", "", domainLabel(item.domain)));
      var typeCell = document.createElement("td");
      var badge = el(
        "span",
        "glossary-type " + (item.kind === "dnt" ? "is-dnt" : "is-preferred"),
        item.kind === "dnt"
          ? uiT("gloss_kind_dnt", "do not translate")
          : uiT("gloss_kind_preferred", "preferred"),
      );
      typeCell.appendChild(badge);
      row.appendChild(typeCell);

      state.visibleLocales.forEach(function (locale) {
        var cell = el("td", "glossary-locale-cell");
        var text = item.data[locale] || "";
        cell.appendChild(el("div", "glossary-preferred", text || "—"));
        var words = (item.data && item.data[locale + "_forbidden"]) || [];
        if (words.length) {
          var tags = el("div", "glossary-forbidden-list");
          words.forEach(function (word) {
            tags.appendChild(el("span", "glossary-forbidden-tag", word));
          });
          cell.appendChild(tags);
        }
        var localeNote = (item.data && item.data[locale + "_note"]) || "";
        if (localeNote) {
          cell.appendChild(el("div", "glossary-locale-note", localeNote));
        }
        row.appendChild(cell);
      });

      var actions = document.createElement("td");
      actions.className = "glossary-actions";
      var edit = el("button", "btn", uiT("gloss_edit", "Edit"));
      edit.type = "button";
      edit.addEventListener("click", function () {
        state.modalShowAllLocales = false;
        state.editing = {
          action: "edit",
          domain: item.domain,
          kind: item.kind,
          term: item.term,
          data: item.data,
        };
        render();
      });
      var remove = el("button", "btn", "✕");
      remove.type = "button";
      remove.setAttribute(
        "aria-label",
        uiT("gloss_delete_aria", "Delete {term}").replace("{term}", item.term),
      );
      remove.addEventListener("click", function () {
        post("/api/glossary", {
          domain: item.domain,
          action: "delete",
          kind: item.kind,
          term: item.term,
        }).then(function (data) {
          if (!data.ok) throw new Error(data.error || "delete failed");
          load();
        }).catch(function (err) {
          state.status = String(err.message || err);
          render();
        });
      });
      actions.appendChild(edit);
      actions.appendChild(remove);
      row.appendChild(actions);
      table.appendChild(row);
    });
    host.appendChild(table);
  }

  function footerBar() {
    var bar = el("div", "glossary-footer");
    var n = termCount();
    bar.appendChild(el(
      "span",
      "glossary-footer-count",
      n === 1
        ? uiT("gloss_n_term", "{n} term").replace("{n}", String(n))
        : uiT("gloss_n_terms", "{n} terms").replace("{n}", String(n)),
    ));
    var spacer = el("div", "");
    spacer.style.flex = "1";
    bar.appendChild(spacer);

    var gHost = document.getElementById("glossary-head-actions");
    if (gHost && window.LLMHelp && !gHost.querySelector(".help-trigger")) {
      gHost.appendChild(window.LLMHelp.helpBtn("glossary:general"));
    }
    var exportBtn = el("button", "btn", uiT("usage_export", "↓ Export CSV"));
    exportBtn.type = "button";
    exportBtn.addEventListener("click", function () {
      post("/api/ops/glossary-export", { format: "csv" }).then(function (data) {
        if (!data.ok) throw new Error(data.summary || data.error || "export failed");
        var text = (data.data && data.data.text) || "";
        var blob = new Blob([text], { type: "text/csv;charset=utf-8" });
        var link = el("a", "", "glossary.csv");
        link.href = URL.createObjectURL(blob);
        link.download = "glossary.csv";
        link.click();
        URL.revokeObjectURL(link.href);
        state.status = data.summary || uiT("gloss_exported_csv", "Exported CSV");
        render();
      }).catch(function (err) {
        state.status = String(err.message || err);
        render();
      });
    });
    bar.appendChild(exportBtn);
    if (window.LLMHelp) bar.appendChild(window.LLMHelp.helpBtn("glossary:csv"));

    var importBtn = el("button", "btn", uiT("gloss_import_csv", "↑ Import CSV"));
    importBtn.type = "button";
    var fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".csv,text/csv";
    fileInput.hidden = true;
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        var text = String(reader.result || "");
        post("/api/ops/glossary-import", {
          format: "csv",
          text: text,
          conflict: "skip",
          dry_run: true,
        }).then(function (data) {
          if (!data.ok) throw new Error(data.summary || data.error || "import failed");
          var counts = data.data || {};
          state.importPending = { text: text, counts: counts };
          state.status = (data.summary || uiT("gloss_dry_run_ok", "Dry-run ok"))
            + " "
            + uiT("gloss_apply_hint", "— click Apply import to write.");
          render();
        }).catch(function (err) {
          state.status = String(err.message || err);
          state.importPending = null;
          render();
        });
      };
      reader.readAsText(file);
    });
    importBtn.addEventListener("click", function () { fileInput.click(); });
    bar.appendChild(importBtn);
    bar.appendChild(fileInput);

    if (state.importPending) {
      var apply = el("button", "btn btn-primary", uiT("gloss_apply_import", "Apply import"));
      apply.type = "button";
      apply.addEventListener("click", function () {
        var pending = state.importPending;
        post("/api/ops/glossary-import", {
          format: "csv",
          text: pending.text,
          conflict: "skip",
          dry_run: false,
        }).then(function (data) {
          if (!data.ok) throw new Error(data.summary || data.error || "import failed");
          state.importPending = null;
          state.status = data.summary || uiT("gloss_import_applied", "Import applied");
          load();
        }).catch(function (err) {
          state.status = String(err.message || err);
          render();
        });
      });
      bar.appendChild(apply);
    }
    return bar;
  }

  function field(labelText, control, hint) {
    var label = el("label", "field");
    var title = el("span", "field-label", labelText);
    label.appendChild(title);
    if (hint) {
      title.appendChild(document.createTextNode(" "));
      title.appendChild(el("span", "field-hint", hint));
    }
    label.appendChild(control);
    return label;
  }

  function modalLocales() {
    var visible = state.visibleLocales.slice();
    if (state.modalShowAllLocales) {
      state.locales.forEach(function (locale) {
        if (visible.indexOf(locale) < 0) visible.push(locale);
      });
      return visible;
    }
    return visible.length ? visible : state.locales.slice();
  }

  function modal() {
    var edit = state.editing;
    var overlay = el("div", "modal glossary-modal");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "glossary-modal-title");

    var box = el("div", "modal-body glossary-modal-body");
    var scroll = el("div", "glossary-modal-scroll");

    scroll.appendChild(el(
      "h2",
      "",
      edit.action === "add"
        ? uiT("gloss_add_title", "Add glossary term")
        : uiT("gloss_edit_title", "Edit glossary term"),
    )).id = "glossary-modal-title";
    if (window.LLMHelp) scroll.lastChild.appendChild(window.LLMHelp.helpBtn("glossary:modal"));

    var term = document.createElement("input");
    term.type = "text";
    term.value = edit.term;
    term.placeholder = uiT("gloss_term_ph", "e.g. namespace");
    term.setAttribute("aria-label", uiT("gloss_col_term", "Term"));
    term.disabled = edit.action === "edit";
    scroll.appendChild(field(
      uiT("gloss_term_source", "Term (source — {locale})")
        .replace("{locale}", state.sourceLocale),
      term,
    ));

    var meta = el("div", "glossary-modal-meta");
    var kind = document.createElement("select");
    kind.setAttribute("aria-label", uiT("set_col_type", "Type"));
    ["term", "dnt"].forEach(function (name) {
      var option = el(
        "option", "",
        name === "dnt"
          ? uiT("gloss_kind_dnt", "do not translate")
          : uiT("gloss_kind_preferred", "preferred"),
      );
      option.value = name;
      if (name === edit.kind) option.selected = true;
      kind.appendChild(option);
    });
    kind.disabled = edit.action === "edit";
    meta.appendChild(field(uiT("set_col_type", "Type"), kind));

    var domain = document.createElement("input");
    domain.type = "text";
    domain.value = edit.domain || "global";
    domain.setAttribute("aria-label", uiT("gloss_col_domain", "Domain"));
    domain.disabled = edit.action === "edit";
    meta.appendChild(field(uiT("gloss_col_domain", "Domain"), domain));
    scroll.appendChild(meta);

    var localeFields = {};
    var translationsBlock = el("div", "glossary-modal-translations");
    var translationsHead = el("div", "glossary-modal-section-head");
    translationsHead.appendChild(el(
      "div", "glossary-modal-section-label",
      uiT("nav_translations", "Translations"),
    ));
    translationsHead.appendChild(el(
      "p",
      "glossary-modal-section-sub",
      uiT(
        "gloss_translations_help",
        "Preferred translation, forbidden terms, and notes for each enabled locale.",
      ),
    ));
    translationsBlock.appendChild(translationsHead);

    var dntNote = el(
      "p",
      "glossary-modal-dnt-note",
      uiT(
        "gloss_dnt_note",
        "Do-not-translate terms stay in the source language. Locale fields are ignored.",
      ),
    );
    dntNote.hidden = kind.value !== "dnt";
    translationsBlock.appendChild(dntNote);

    var localeList = el("div", "glossary-modal-locale-list");
    translationsBlock.appendChild(localeList);

    var sharedLegacy = (edit.data && edit.data.note) || "";

    function localeNoteValue(locale) {
      if (localeFields[locale] && localeFields[locale].note) {
        return localeFields[locale].note.value;
      }
      if (edit.data && edit.data[locale + "_note"]) {
        return edit.data[locale + "_note"];
      }
      return sharedLegacy;
    }

    function paintLocaleRows() {
      localeList.replaceChildren();
      var shown = modalLocales();
      var table = document.createElement("table");
      table.className = "glossary-modal-table";
      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      [
        uiT("gloss_col_language", "Language"),
        uiT("gloss_col_preferred", "Preferred"),
        uiT("gloss_col_forbidden", "Forbidden"),
        uiT("gloss_col_notes", "Notes"),
      ].forEach(function (name) {
        headRow.appendChild(el("th", "", name));
      });
      thead.appendChild(headRow);
      table.appendChild(thead);
      var tbody = document.createElement("tbody");

      shown.forEach(function (locale) {
        var row = document.createElement("tr");
        row.appendChild(el("td", "glossary-modal-locale-code", locale));

        var preferredField = document.createElement("input");
        preferredField.type = "text";
        preferredField.value = (localeFields[locale] && localeFields[locale].preferred)
          ? localeFields[locale].preferred.value
          : ((edit.data && edit.data[locale]) || "");
        preferredField.placeholder = uiT("gloss_preferred_ph", "Preferred translation…");
        preferredField.setAttribute("aria-label", locale + " preferred");
        preferredField.disabled = kind.value === "dnt";

        var forbiddenField = document.createElement("input");
        forbiddenField.type = "text";
        var existingForbidden = (localeFields[locale] && localeFields[locale].forbidden)
          ? localeFields[locale].forbidden.value
          : (((edit.data && edit.data[locale + "_forbidden"]) || []).join("; "));
        forbiddenField.value = existingForbidden;
        forbiddenField.placeholder = uiT(
          "gloss_forbidden_ph",
          "Forbidden (semicolon-separated)",
        );
        forbiddenField.setAttribute("aria-label", locale + " forbidden");
        forbiddenField.disabled = kind.value === "dnt";

        var noteField = document.createElement("input");
        noteField.type = "text";
        noteField.value = localeNoteValue(locale);
        noteField.placeholder = uiT("gloss_notes_ph", "Notes for this locale…");
        noteField.setAttribute("aria-label", locale + " note");
        noteField.disabled = kind.value === "dnt";

        localeFields[locale] = {
          preferred: preferredField,
          forbidden: forbiddenField,
          note: noteField,
        };

        var preferredCell = document.createElement("td");
        preferredCell.appendChild(preferredField);
        var forbiddenCell = document.createElement("td");
        forbiddenCell.appendChild(forbiddenField);
        var noteCell = document.createElement("td");
        noteCell.appendChild(noteField);
        row.appendChild(preferredCell);
        row.appendChild(forbiddenCell);
        row.appendChild(noteCell);
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      localeList.appendChild(table);

      var hiddenCount = state.locales.length - shown.length;
      if (hiddenCount > 0 && !state.modalShowAllLocales) {
        var more = el(
          "button", "btn glossary-modal-more",
          uiT("gloss_show_all", "Show all {n} locales")
            .replace("{n}", String(state.locales.length)),
        );
        more.type = "button";
        more.addEventListener("click", function () {
          state.modalShowAllLocales = true;
          paintLocaleRows();
        });
        localeList.appendChild(more);
      } else if (state.modalShowAllLocales && state.visibleLocales.length && state.visibleLocales.length < state.locales.length) {
        var less = el(
          "button", "btn glossary-modal-more",
          uiT("gloss_show_enabled", "Show enabled locales only"),
        );
        less.type = "button";
        less.addEventListener("click", function () {
          state.modalShowAllLocales = false;
          paintLocaleRows();
        });
        localeList.appendChild(less);
      }
    }

    kind.addEventListener("change", function () {
      dntNote.hidden = kind.value !== "dnt";
      paintLocaleRows();
    });
    paintLocaleRows();
    scroll.appendChild(translationsBlock);

    box.appendChild(scroll);

    var actions = el("div", "glossary-modal-actions");
    var cancel = el("button", "btn", uiT("wf_cancel", "Cancel"));
    cancel.type = "button";
    cancel.addEventListener("click", function () {
      state.editing = null;
      state.modalShowAllLocales = false;
      overlay.remove();
      render();
    });
    var save = el(
      "button", "btn btn-primary",
      edit.action === "add"
        ? uiT("gloss_add_term_btn", "Add term")
        : uiT("wf_save", "Save"),
    );
    save.type = "button";
    save.addEventListener("click", function () {
      var translations = {};
      var forbiddenMap = {};
      var notesMap = {};
      state.locales.forEach(function (locale) {
        var fields = localeFields[locale];
        if (!fields) {
          translations[locale] = (edit.data && edit.data[locale]) || "";
          forbiddenMap[locale] = (edit.data && edit.data[locale + "_forbidden"]) || [];
          notesMap[locale] = (edit.data && edit.data[locale + "_note"]) || "";
          return;
        }
        translations[locale] = fields.preferred.value;
        forbiddenMap[locale] = fields.forbidden.value.split(";").map(function (part) {
          return part.trim();
        }).filter(Boolean);
        notesMap[locale] = fields.note.value;
      });
      post("/api/glossary", {
        domain: domain.value || "global",
        action: edit.action,
        kind: kind.value,
        term: term.value,
        translations: translations,
        forbidden: forbiddenMap,
        notes: notesMap,
      }).then(function (data) {
        if (!data.ok) throw new Error(data.error || "save failed");
        state.editing = null;
        state.modalShowAllLocales = false;
        overlay.remove();
        load();
      }).catch(function (err) {
        var prev = box.querySelector(".search-error");
        if (prev) prev.remove();
        actions.insertAdjacentElement("beforebegin", el("p", "search-error", String(err.message || err)));
      });
    });
    actions.appendChild(cancel);
    actions.appendChild(save);
    box.appendChild(actions);
    overlay.appendChild(box);

    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) {
        state.editing = null;
        state.modalShowAllLocales = false;
        overlay.remove();
        render();
      }
    });

    setTimeout(function () {
      if (!term.disabled) term.focus();
    }, 0);
    return overlay;
  }

  var scope = (window.LLMApi && LLMApi.requestScope) ? LLMApi.requestScope() : null;
  var _loadImpl = load;
  load = function () {
    if (scope) scope.next();
    return _loadImpl.apply(this, arguments);
  };
  select.addEventListener("change", load);
  var navGen = window.__LLM_NAV_GEN || 0;
  document.addEventListener("click", function (event) {
    if ((window.__LLM_NAV_GEN || 0) !== navGen) return;
    document.querySelectorAll(".glossary-locale-menu").forEach(function (menu) {
      if (menu.hidden) return;
      var picker = menu.closest(".glossary-locale-picker");
      if (picker && picker.contains(event.target)) return;
      menu.hidden = true;
      var btn = picker && picker.querySelector("[aria-haspopup]");
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
  });
  var ready = (window.uiLocale && typeof window.uiLocale.whenReady === "function")
    ? window.uiLocale.whenReady()
    : Promise.resolve();
  ready.then(function () {
    if (select.value) load();
  });
})();
