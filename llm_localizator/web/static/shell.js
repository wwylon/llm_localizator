(function () {
  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function roleLabel(role) {
    if (!role) return "";
    var keys = {
      Admin: "role_admin",
      Supervisor: "role_supervisor",
      Translator: "role_translator",
      Developer: "role_developer",
    };
    return uiT(keys[role] || ("role_" + String(role).toLowerCase()), role);
  }

  var ADMIN_ROUTES = {
    users: true,
    settings: true,
    "project-config": true,
  };
  var TEAM_ROUTES = {
    activity: true,
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function applyAdminNav(isAdmin, canSeeTeam) {
    window.__LLM_IS_ADMIN = !!isAdmin;
    document.querySelectorAll(".nav-link[data-route]").forEach(function (link) {
      var route = link.getAttribute("data-route");
      if (ADMIN_ROUTES[route]) {
        link.hidden = !isAdmin;
        return;
      }
      if (TEAM_ROUTES[route]) {
        link.hidden = !canSeeTeam;
      }
    });
    document.querySelectorAll(".nav-group").forEach(function (group) {
      var sib = group.nextElementSibling;
      var visible = false;
      while (sib && !sib.classList.contains("nav-group")) {
        if (
          sib.classList.contains("nav-link")
          && !sib.hidden
          && sib.style.display !== "none"
        ) {
          visible = true;
          break;
        }
        sib = sib.nextElementSibling;
      }
      group.hidden = !visible;
    });
  }

  function paintUser() {
    var mount = document.getElementById("shell-user");
    var headers = {};
    if (window.__LLM_TOKEN) headers["X-LLM-Token"] = window.__LLM_TOKEN;
    fetch("/api/auth/me", { headers: headers, credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (me) {
        window.__LLM_ME = me || null;
        window.__LLM_READY = true;
        window.dispatchEvent(new CustomEvent("llm-me"));
        var isAdmin = !!(me && me.authenticated && me.role === "Admin");
        var canSeeTeam = !!(me && me.authenticated && (
          me.role === "Admin" || me.role === "Supervisor"
        ));
        applyAdminNav(isAdmin, canSeeTeam);
        if (!mount) return;
        if (!me || !me.authenticated) {
          applyAdminNav(false, false);
          return;
        }
        mount.replaceChildren();
        if (!me.user) {
          mount.appendChild(el("span", "shell-name", uiT("shell_local", "local")));
          mount.appendChild(el("span", "shell-role", roleLabel(me.role || "Admin")));
          return;
        }
        var name = me.user.username || "?";
        var link = document.createElement("a");
        link.className = "shell-user";
        link.href = (window.uiLocale && window.uiLocale.withLocale)
          ? window.uiLocale.withLocale(isAdmin ? "/app/settings" : "/app", window.uiLocale.current || "en")
          : (isAdmin ? "/app/settings" : "/app");
        link.appendChild(el("span", "shell-avatar", name.slice(0, 2).toUpperCase()));
        var meta = el("span", "shell-meta");
        meta.appendChild(el("span", "shell-name", name));
        meta.appendChild(el("span", "shell-role", roleLabel(me.role || "")));
        link.appendChild(meta);
        mount.appendChild(link);
      })
      .catch(function () {
        window.__LLM_ME = null;
        window.__LLM_READY = true;
        window.dispatchEvent(new CustomEvent("llm-me"));
        applyAdminNav(false, false);
      });
  }

  paintUser();

  var select = document.getElementById("project-select");
  if (!select) return;

  document.addEventListener("change", function (event) {
    var target = event.target;
    if (!target || target.id !== "project-select") return;
    if (target.value) localStorage.setItem("llm_project", target.value);
  });

  var loadProjects = (window.LLMApi && LLMApi.apiGet)
    ? LLMApi.apiGet("/api/projects", {})
    : Promise.reject(new Error("LLMApi missing"));
  loadProjects.then(function (data) {
    if (data && data.error && !data.projects) return null;
    return data;
  }).then(function (data) {
    var live = document.getElementById("project-select");
    if (!live) return;
    if (!data || !data.projects) {
      live.replaceChildren();
      var fail = document.createElement("option");
      fail.value = "";
      fail.textContent = uiT("shell_no_projects", "(no projects)");
      live.appendChild(fail);
      live.dispatchEvent(new Event("change"));
      return;
    }
    var names = [];
    data.projects.forEach(function (project) {
      if (!project || !project.name) return;
      names.push(project.name);
      var option = document.createElement("option");
      option.value = project.name;
      option.textContent = project.name;
      live.appendChild(option);
    });
    var saved = localStorage.getItem("llm_project");
    var pick = saved && names.indexOf(saved) !== -1 ? saved : data.default;
    if (pick && names.indexOf(pick) !== -1) live.value = pick;
    live.dispatchEvent(new Event("change"));
  }).catch(function () {
    var live = document.getElementById("project-select");
    if (!live) return;
    live.replaceChildren();
    var fail = document.createElement("option");
    fail.value = "";
    fail.textContent = uiT("shell_projects_failed", "(projects failed to load)");
    live.appendChild(fail);
    live.dispatchEvent(new Event("change"));
  });

  // "Remove from list" unregisters the selected project (files stay). Admin only,
  // and only while another project remains to switch to (the server refuses to
  // unregister the project a request is served from).
  var removeBtn = document.getElementById("project-remove");
  function syncRemove() {
    var live = document.getElementById("project-select");
    var admin = !!(window.__LLM_ME && window.__LLM_ME.authenticated && window.__LLM_ME.role === "Admin");
    if (removeBtn) removeBtn.hidden = !(admin && live && live.options.length > 1 && live.value);
  }
  window.addEventListener("llm-me", syncRemove);
  document.addEventListener("change", function (event) {
    if (event.target && event.target.id === "project-select") syncRemove();
  });

  var branchChip = document.getElementById("shell-branch-chip");
  function refreshBranchChip() {
    if (!branchChip) return;
    var query = {};
    var live = document.getElementById("project-select");
    if (live && live.value) query.project = live.value;
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/branches", query)
      : Promise.reject(new Error("LLMApi missing"));
    get.then(function (data) {
      if (!data || !data.ok) {
        branchChip.hidden = true;
        return;
      }
      var name = data.active || (data.main && data.main.name) || "";
      if (!name) {
        branchChip.hidden = true;
        return;
      }
      branchChip.hidden = false;
      branchChip.textContent = data.active
        ? uiT("shell_branch_active", "branch: {name}").replace("{name}", name)
        : uiT("shell_branch_source", "source: {name}").replace("{name}", name);
    }).catch(function () { branchChip.hidden = true; });
  }
  document.addEventListener("change", function (event) {
    if (event.target && event.target.id === "project-select") refreshBranchChip();
  });
  window.addEventListener("llm-me", refreshBranchChip);
  refreshBranchChip();

  if (removeBtn) removeBtn.addEventListener("click", function () {
    var live = document.getElementById("project-select");
    if (!live || !live.value) return;
    var name = live.value;
    var other = "";
    for (var i = 0; i < live.options.length; i++) {
      if (live.options[i].value && live.options[i].value !== name) { other = live.options[i].value; break; }
    }
    if (!other) return;
    if (!window.confirm(uiT("shell_remove_confirm", "Remove '{name}' from the list? Its files are not touched.").replace("{name}", name))) return;
    var headers = { "Content-Type": "application/json" };
    if (window.__LLM_TOKEN) headers["X-LLM-Token"] = window.__LLM_TOKEN;
    fetch("/api/ops/projects", {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ project: other, action: "remove", names: [name] }),
    }).then(function (response) { return response.json().catch(function () { return {}; }); })
      .then(function (result) {
        if (result && result.ok === false) {
          window.alert(result.summary || uiT("shell_remove_failed", "Could not remove the project."));
          return;
        }
        try { localStorage.removeItem("llm_project"); } catch (err) { /* private mode */ }
        location.reload();
      })
      .catch(function () {
        window.alert(uiT("shell_remove_failed", "Could not remove the project."));
      });
  });

  // In-app links swap <main> only. A full document load repaints the sidebar
  // and the page together, which is the flash on every navigation.
  var SHELL_SCRIPTS = {
    "/static/ui-locale.js": true,
    "/static/appearance.js": true,
    "/static/api.js": true,
    "/static/request-health.js": true,
    "/static/shell.js": true,
    "/static/help.js": true,
  };
  var HELP_SRC = "/static/help.js";
  var helpLoading = null;

  function ensureHelp() {
    if (window.LLMHelp || document.querySelector('script[src*="help.js"]')) {
      return Promise.resolve();
    }
    if (helpLoading) return helpLoading;
    helpLoading = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = HELP_SRC + (window.__LLM_ASSET_V ? ("?v=" + window.__LLM_ASSET_V) : "");
      script.async = true;
      script.onload = function () { resolve(); };
      script.onerror = function () { helpLoading = null; reject(new Error(HELP_SRC)); };
      document.body.appendChild(script);
    });
    return helpLoading;
  }
  window.__LLM_ENSURE_HELP = ensureHelp;
  var navSeq = 0;
  window.__LLM_NAV_GEN = window.__LLM_NAV_GEN || 0;

  function appURL(href) {
    try {
      return new URL(href, location.href);
    } catch (err) {
      return null;
    }
  }

  function barePath(pathname) {
    if (window.uiLocale && window.uiLocale.stripLocale) {
      return window.uiLocale.stripLocale(pathname);
    }
    return (pathname || "").replace(
      /^\/(en|de|pl|fr|ar)(?=\/app(?:\/|$)|\/login|\/register|\/pending|\/setup)/,
      ""
    ) || pathname;
  }

  function isAppPath(url) {
    var p = barePath(url.pathname);
    return p === "/app" || p.indexOf("/app/") === 0;
  }

  function dropPageSelectListeners() {
    var live = document.getElementById("project-select");
    if (!live || !live.parentNode) return;
    live.replaceWith(live.cloneNode(true));
  }

  function markActive(pathname) {
    var want = barePath(pathname);
    document.querySelectorAll("a.nav-link").forEach(function (link) {
      var url = appURL(link.getAttribute("href"));
      var on = !!(url && barePath(url.pathname) === want);
      link.classList.toggle("is-active", on);
      if (on) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function pageScriptSrcs(doc) {
    var srcs = [];
    doc.querySelectorAll("script[src]").forEach(function (node) {
      var src = node.getAttribute("src") || "";
      var path = src.split("?")[0];
      if (!path || SHELL_SCRIPTS[path]) return;
      srcs.push(src);
    });
    return srcs;
  }

  function runScripts(srcs) {
    document.querySelectorAll("script[data-page-script]").forEach(function (node) {
      node.remove();
    });
    return srcs.reduce(function (chain, src) {
      return chain.then(function () {
        return new Promise(function (resolve, reject) {
          var script = document.createElement("script");
          script.src = src;
          script.async = false;
          script.setAttribute("data-page-script", "1");
          script.onload = function () { resolve(); };
          script.onerror = function () { reject(new Error(src)); };
          document.body.appendChild(script);
        });
      });
    }, Promise.resolve());
  }

  function clearPageOverlays() {
    Array.prototype.slice.call(document.body.children).forEach(function (node) {
      if (node.classList && node.classList.contains("shell")) return;
      if (node.tagName === "SCRIPT") return;
      node.remove();
    });
  }

  function swapMain(doc) {
    var shell = document.querySelector(".shell");
    var current = document.querySelector(".shell > main");
    var next = doc.querySelector("main#page");
    if (!shell || !current || !next || !doc.querySelector(".sidebar")) return null;
    // Drop id on the outgoing main itself — querySelectorAll only sees
    // descendants. Leaving main#page in place makes the next page script's
    // getElementById("page") hit the old node and bail (dataset.page mismatch),
    // so SPA navigations stick on "Loading…".
    if (current.id) current.removeAttribute("id");
    current.querySelectorAll("[id]").forEach(function (node) {
      node.removeAttribute("id");
    });
    var imported = document.importNode(next, true);
    imported.hidden = true;
    imported.style.setProperty("display", "none", "important");
    shell.appendChild(imported);
    return { current: current, imported: imported };
  }

  function go(url, push) {
    var next = url.pathname + url.search;
    if (next === location.pathname + location.search && push) return Promise.resolve();
    var seq = ++navSeq;
    return fetch(next, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("nav " + response.status);
      return response.text();
    }).then(function (html) {
      if (seq !== navSeq) return;
      var doc = new DOMParser().parseFromString(html, "text/html");
      clearPageOverlays();
      dropPageSelectListeners();
      var swapped = swapMain(doc);
      if (!swapped) {
        location.assign(next);
        return;
      }
      document.title = doc.title || document.title;
      markActive(url.pathname);
      if (push) history.pushState({ llmNav: 1 }, "", next);
      window.__LLM_NAV_GEN = (window.__LLM_NAV_GEN || 0) + 1;
      return runScripts(pageScriptSrcs(doc)).then(function () {
        if (seq !== navSeq) {
          swapped.imported.remove();
          return;
        }
        swapped.current.remove();
        swapped.imported.hidden = false;
        swapped.imported.style.removeProperty("display");
        if (window.uiLocale) {
          if (window.uiLocale.ensureSelector) window.uiLocale.ensureSelector();
          if (window.uiLocale._apply) window.uiLocale._apply();
        }
        if (window.__LLM_ENSURE_HELP) {
          var run = function () { window.__LLM_ENSURE_HELP(); };
          if (window.requestIdleCallback) requestIdleCallback(run, { timeout: 2000 });
          else setTimeout(run, 0);
        }
      });
    }).catch(function () {
      if (seq !== navSeq) return;
      location.assign(next);
    });
  }

  window.llmNavigate = function (href) {
    var url = appURL(href);
    if (!url || url.origin !== location.origin || !isAppPath(url)) {
      location.assign(href);
      return;
    }
    go(url, true);
  };

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target && event.target.closest && event.target.closest("a");
    if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
    var url = appURL(link.href);
    if (!url || url.origin !== location.origin || !isAppPath(url)) return;
    // Same URL (active nav): swallow the click — do not full-reload.
    if (url.pathname + url.search === location.pathname + location.search) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    go(url, true);
  });

  window.addEventListener("popstate", function () {
    var url = appURL(location.href);
    if (!url || !isAppPath(url)) return;
    go(url, false);
  });
})();

// Shared locale-picker modal used by dashboard.js and editor.js.
// catalog: Array<{code, name}>  taken: Object<code, bool>  onAdd(code): void
window.localePicker = function localePicker(catalog, taken, onAdd) {
  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }
  function mk(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }
  var filtered = catalog.filter(function (r) { return !taken[r.code]; });
  var selected = "";
  var modal = mk("div", "modal locale-pick-modal");
  var form = mk("div", "modal-body blueprint-card");
  form.appendChild(mk("h2", "", uiT("modalTitle", "Add locale")));
  var filterLabel = mk("label", "field", uiT("shell_filter", "Filter"));
  var filter = document.createElement("input");
  filter.type = "search";
  filter.placeholder = uiT("shell_locale_search_ph", "Search by name or code…");
  filter.setAttribute("autocomplete", "off");
  filterLabel.appendChild(filter);
  form.appendChild(filterLabel);
  var list = mk("div", "locale-pick-list");
  list.setAttribute("role", "listbox");
  form.appendChild(list);
  var err = mk("p", "search-error", "");
  err.hidden = true;
  form.appendChild(err);
  var actions = mk("div", "ops-actions");
  var cancel = mk("button", "btn", uiT("wf_cancel", "Cancel"));
  cancel.type = "button";
  var add = mk("button", "btn btn-primary", uiT("shell_add", "Add"));
  add.type = "button";
  add.disabled = true;
  actions.appendChild(cancel);
  actions.appendChild(add);
  form.appendChild(actions);
  modal.appendChild(form);
  document.body.appendChild(modal);
  filter.focus();

  function paintList() {
    var q = (filter.value || "").trim().toLowerCase();
    list.replaceChildren();
    var shown = 0;
    filtered.forEach(function (row) {
      var hay = (row.name + " " + row.code).toLowerCase();
      if (q && hay.indexOf(q) === -1) return;
      shown += 1;
      var item = mk("button", "locale-pick-item", "");
      item.type = "button";
      item.setAttribute("role", "option");
      if (row.code === selected) item.classList.add("is-selected");
      item.appendChild(mk("span", "locale-pick-name", row.name || row.code));
      item.appendChild(mk("span", "locale-pick-code", row.code));
      item.addEventListener("click", function () {
        selected = row.code;
        add.disabled = false;
        paintList();
      });
      list.appendChild(item);
    });
    if (!shown) list.appendChild(mk("p", "empty-state", uiT("shell_no_match_locales", "No matching locales.")));
  }

  paintList();
  filter.addEventListener("input", paintList);
  cancel.addEventListener("click", function () { modal.remove(); });
  modal.addEventListener("click", function (e) { if (e.target === modal) modal.remove(); });
  add.addEventListener("click", function () {
    if (!selected) return;
    add.disabled = true;
    err.hidden = true;
    onAdd(selected, function (errorMsg) {
      if (errorMsg) {
        err.hidden = false;
        err.textContent = errorMsg;
        add.disabled = false;
      } else {
        modal.remove();
      }
    });
  });
};

(function () {
  var badge = document.getElementById("review-badge");
  if (!badge) return;
  function refresh() {
    var query = {};
    var sel = document.getElementById("project-select");
    if (sel && sel.value) query.project = sel.value;
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/review/counts", query)
      : Promise.reject(new Error("LLMApi missing"));
    get.then(function (d) {
      if (!d || !d.ok) return;
      badge.hidden = !(d.active > 0);
      badge.textContent = d.active > 0 ? String(d.active) : "";
    }).catch(function () {});
  }
  window.LLMShell = window.LLMShell || {};
  window.LLMShell.refreshReviewBadge = refresh;
  refresh();
})();
