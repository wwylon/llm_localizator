(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  var select = document.getElementById("project-select");
  if (!page || page.dataset.page !== "users" || !root || !select) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  var ROLES = ["Admin", "Supervisor", "Translator", "Developer"];
  var ROLE_GUIDE = [
    {
      role: "Admin",
      lines: [
        [true, "users_role_admin_1", "Full access to all languages"],
        [true, "users_role_admin_2", "Invite & manage users"],
        [true, "users_role_admin_3", "Run LLM pipeline operations"],
        [true, "users_role_admin_4", "Configure projects & models"],
      ],
    },
    {
      role: "Supervisor",
      lines: [
        [true, "users_role_sup_1", "Edit & approve assigned languages"],
        [true, "users_role_sup_2", "Run validate, rescore, improve"],
        [true, "users_role_sup_3", "View quality scores & history"],
        [false, "users_role_sup_4", "Cannot manage users"],
      ],
    },
    {
      role: "Translator",
      lines: [
        [true, "users_role_tr_1", "Edit assigned languages only"],
        [true, "users_role_tr_2", "View source strings & context"],
        [false, "users_role_tr_3", "Cannot run LLM operations"],
        [false, "users_role_tr_4", "Cannot see other locales"],
      ],
    },
    {
      role: "Developer",
      lines: [
        [true, "users_role_dev_1", "Scan, discover, doctor, push-strings"],
        [true, "users_role_dev_2", "Validate, export, release-diff"],
        [false, "users_role_dev_3", "Cannot translate or improve"],
        [false, "users_role_dev_4", "Cannot manage users"],
      ],
    },
  ];

  function roleLabel(role) {
    var keys = {
      Admin: "role_admin",
      Supervisor: "role_supervisor",
      Translator: "role_translator",
      Developer: "role_developer",
    };
    return uiT(keys[role] || ("role_" + String(role).toLowerCase()), role);
  }

  var state = {
    users: [],
    invitePath: "/register",
    locales: [],
    meId: null,
    filter: "",
    status: "",
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function project() {
    return select.value || "";
  }

  function initials(name) {
    var parts = String(name || "?").trim().split(/[.\s_-]+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return String(name || "?").slice(0, 2).toUpperCase();
  }

  function relativeTime(iso) {
    if (!iso) return "";
    var then = Date.parse(iso);
    if (!then) return "";
    var sec = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (sec < 60) return uiT("time_just_now", "just now");
    if (sec < 3600) {
      return uiT("time_m_ago", "{n}m ago").replace("{n}", String(Math.floor(sec / 60)));
    }
    if (sec < 86400) {
      return uiT("time_h_ago", "{n}h ago").replace("{n}", String(Math.floor(sec / 3600)));
    }
    if (sec < 86400 * 14) {
      return uiT("time_d_ago", "{n}d ago").replace("{n}", String(Math.floor(sec / 86400)));
    }
    return new Date(then).toLocaleDateString();
  }

  function post(path, body) {
    body = body || {};
    body.project = project();
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function roleSelect(selected) {
    var node = document.createElement("select");
    node.className = "users-role-select";
    ROLES.forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (selected === name) opt.selected = true;
      node.appendChild(opt);
    });
    if (!selected) node.selectedIndex = 2;
    return node;
  }

  function setStatus(msg) {
    state.status = msg || "";
    var node = root.querySelector("[data-users-status]");
    if (node) node.textContent = state.status;
  }

  function openInvite() {
    var modal = el("div", "modal");
    var form = el("div", "modal-body blueprint-card");
    form.appendChild(el("h2", "", uiT("usr_invite_title", "Invite user")));
    form.appendChild(el(
      "p", "empty-state",
      uiT("usr_invite_hint", "No email is sent. Copy this registration link and share it. New accounts appear under Pending approval.")
    ));
    var url = location.origin + (state.invitePath || "/register");
    var label = el("label", "field", uiT("usr_invite_url", "Invite URL"));
    var input = document.createElement("input");
    input.type = "text";
    input.readOnly = true;
    input.value = url;
    label.appendChild(input);
    form.appendChild(label);
    var actions = el("div", "ops-actions");
    var cancel = el("button", "btn", uiT("wf_cancel", "Cancel"));
    cancel.type = "button";
    cancel.addEventListener("click", function () { modal.remove(); });
    var copy = el("button", "btn btn-primary", uiT("usr_copy_invite", "Copy invite URL"));
    copy.type = "button";
    copy.addEventListener("click", function () {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () {
          setStatus(uiT("usr_invite_copied", "Invite URL copied."));
          modal.remove();
        });
      } else {
        input.select();
        setStatus(url);
      }
    });
    actions.appendChild(cancel);
    actions.appendChild(copy);
    form.appendChild(actions);
    modal.appendChild(form);
    document.body.appendChild(modal);
  }

  function saveUser(user, role, locales) {
    return post("/api/auth/users/approve", {
      id: user.id,
      role: role,
      locales: locales,
    }).then(function (result) {
      setStatus(result.ok ? uiT("usr_saved", "Saved.") : (result.error || uiT("usr_failed", "Failed.")));
      if (result.ok) load();
    });
  }

  function paintLocaleCell(user, roleNode) {
    var cell = el("div", "users-locales");
    var isAdmin = (roleNode ? roleNode.value : user.role) === "Admin";
    if (isAdmin) {
      cell.appendChild(el("span", "users-muted", uiT("usr_all_languages", "All languages")));
      return cell;
    }
    var locales = (user.locales || []).slice();
    function refresh() {
      cell.replaceChildren();
      locales.forEach(function (code) {
        var chip = el("span", "locale-chip", code);
        var remove = el("button", "locale-chip-x", "×");
        remove.type = "button";
        remove.title = uiT("usr_remove_locale", "Remove {code}").replace("{code}", code);
        remove.addEventListener("click", function () {
          locales = locales.filter(function (c) { return c !== code; });
          user.locales = locales;
          refresh();
          saveUser(user, roleNode.value, locales);
        });
        chip.appendChild(remove);
        cell.appendChild(chip);
      });
      var available = state.locales.filter(function (code) {
        return locales.indexOf(code) === -1;
      });
      if (available.length) {
        var add = document.createElement("select");
        add.className = "users-add-locale";
        var placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = uiT("usr_add", "+ add");
        add.appendChild(placeholder);
        available.forEach(function (code) {
          var opt = document.createElement("option");
          opt.value = code;
          opt.textContent = code;
          add.appendChild(opt);
        });
        add.addEventListener("change", function () {
          if (!add.value) return;
          locales.push(add.value);
          user.locales = locales;
          refresh();
          saveUser(user, roleNode.value, locales);
        });
        cell.appendChild(add);
      }
    }
    refresh();
    if (roleNode) {
      roleNode.addEventListener("change", function () {
        if (roleNode.value === "Admin") {
          cell.replaceChildren(el("span", "users-muted", uiT("usr_all_languages", "All languages")));
        } else {
          refresh();
        }
        saveUser(user, roleNode.value, locales);
      });
    }
    return cell;
  }

  function paintPending(list) {
    var wrap = el("div", "users-section");
    wrap.id = "pending";
    wrap.appendChild(el(
      "div", "users-section-label",
      uiT("usr_pending_count", "Pending approval — {n}").replace("{n}", String(list.length)),
    ));
    var stack = el("div", "users-pending-stack");
    list.forEach(function (user) {
      var row = el("div", "users-pending-row");
      var left = el("div", "users-person");
      left.appendChild(el("div", "users-avatar", initials(user.username)));
      var meta = el("div", "");
      meta.appendChild(el("div", "users-name", user.username));
      meta.appendChild(el(
        "div", "users-meta",
        uiT("usr_requested", "requested {when}").replace(
          "{when}",
          relativeTime(user.created_at) || uiT("usr_recently", "recently"),
        ),
      ));
      left.appendChild(meta);
      row.appendChild(left);

      var right = el("div", "users-pending-actions");
      right.appendChild(el("span", "users-badge is-pending", uiT("usr_pending", "Pending")));
      var role = roleSelect(user.role);
      right.appendChild(role);

      var pendingLocales = (user.locales || []).slice();
      var localeBox = el("div", "users-locales");
      function paintPendingLocales() {
        localeBox.replaceChildren();
        if (role.value === "Admin") {
          localeBox.appendChild(el("span", "users-muted", uiT("usr_all_languages", "All languages")));
          return;
        }
        pendingLocales.forEach(function (code) {
          var chip = el("span", "locale-chip", code);
          var remove = el("button", "locale-chip-x", "×");
          remove.type = "button";
          remove.title = uiT("usr_remove_locale", "Remove {code}").replace("{code}", code);
          remove.addEventListener("click", function () {
            pendingLocales = pendingLocales.filter(function (c) {
              return c !== code;
            });
            paintPendingLocales();
          });
          chip.appendChild(remove);
          localeBox.appendChild(chip);
        });
        var available = state.locales.filter(function (c) {
          return pendingLocales.indexOf(c) === -1;
        });
        if (available.length) {
          var add = document.createElement("select");
          add.className = "users-add-locale";
          var ph = document.createElement("option");
          ph.value = "";
          ph.textContent = uiT("usr_add", "+ add");
          add.appendChild(ph);
          available.forEach(function (code) {
            var opt = document.createElement("option");
            opt.value = code;
            opt.textContent = code;
            add.appendChild(opt);
          });
          add.addEventListener("change", function () {
            if (!add.value) return;
            pendingLocales.push(add.value);
            paintPendingLocales();
          });
          localeBox.appendChild(add);
        }
      }
      role.addEventListener("change", paintPendingLocales);
      paintPendingLocales();
      right.appendChild(localeBox);

      var approve = el("button", "btn btn-primary", uiT("usr_approve", "Approve"));
      approve.type = "button";
      approve.addEventListener("click", function () {
        post("/api/auth/users/approve", {
          id: user.id,
          role: role.value,
          locales: role.value === "Admin" ? [] : pendingLocales,
        }).then(function (result) {
          setStatus(result.ok ? uiT("usr_approved", "Approved.") : (result.error || uiT("usr_failed", "Failed.")));
          if (result.ok) load();
        });
      });
      var deny = el("button", "btn", uiT("usr_deny", "Deny"));
      deny.type = "button";
      deny.addEventListener("click", function () {
        post("/api/auth/users/deny", { id: user.id }).then(function (result) {
          setStatus(result.ok ? uiT("usr_denied", "Denied.") : (result.error || uiT("usr_failed", "Failed.")));
          if (result.ok) load();
        });
      });
      right.appendChild(approve);
      right.appendChild(deny);
      row.appendChild(right);
      stack.appendChild(row);
    });
    wrap.appendChild(stack);
    return wrap;
  }

  function paintActive(list) {
    var wrap = el("div", "users-section");
    var head = el("div", "users-section-head");
    head.appendChild(el(
      "div", "users-section-label",
      uiT("usr_active_count", "Active users — {n}").replace("{n}", String(list.length)),
    ));
    var filter = document.createElement("input");
    filter.type = "search";
    filter.className = "users-filter";
    filter.placeholder = uiT("usr_filter_ph", "Filter users…");
    filter.value = state.filter;
    filter.addEventListener("input", function () {
      state.filter = filter.value.trim().toLowerCase();
      var q = state.filter;
      Array.prototype.forEach.call(tbody.querySelectorAll("tr"), function (tr) {
        var name = (tr.getAttribute("data-username") || "").toLowerCase();
        tr.hidden = !!(q && name.indexOf(q) === -1);
      });
    });
    head.appendChild(filter);
    wrap.appendChild(head);

    var table = el("table", "users-table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    [
      [uiT("usr_col_user", "User"), ""],
      [uiT("usr_col_role", "Role"), ""],
      [uiT("usr_col_access", "Language access"), ""],
      [uiT("usr_col_last", "Last active"), ""],
      ["", ""],
    ].forEach(function (row) {
      hr.appendChild(el("th", row[1], row[0]));
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");

    list.forEach(function (user) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-username", user.username || "");
      if (state.filter && String(user.username || "").toLowerCase().indexOf(state.filter) === -1) {
        tr.hidden = true;
      }
      var isSelf = state.meId && user.id === state.meId;
      var isAdmin = user.role === "Admin";
      var lockSelfAdmin = isSelf && isAdmin;

      var userTd = document.createElement("td");
      var person = el("div", "users-person");
      person.appendChild(el(
        "div",
        "users-avatar" + (isAdmin ? " is-accent" : ""),
        initials(user.username)
      ));
      var meta = el("div", "");
      var nameLine = el("div", "users-name", user.username);
      if (isSelf) {
        nameLine.appendChild(document.createTextNode(" "));
        nameLine.appendChild(el("span", "users-muted", "(you)"));
      }
      meta.appendChild(nameLine);
      meta.appendChild(el("div", "users-meta", "id " + String(user.id).slice(0, 8)));
      person.appendChild(meta);
      userTd.appendChild(person);
      tr.appendChild(userTd);

      var roleTd = document.createElement("td");
      var roleNode = null;
      if (lockSelfAdmin) {
        roleTd.appendChild(el("span", "users-badge is-admin", uiT("nav_admin", "Admin")));
      } else {
        roleNode = roleSelect(user.role);
        roleTd.appendChild(roleNode);
      }
      tr.appendChild(roleTd);

      var localeTd = document.createElement("td");
      if (lockSelfAdmin) {
        localeTd.appendChild(el("span", "users-muted", uiT("usr_all_languages", "All languages")));
      } else if (roleNode) {
        localeTd.appendChild(paintLocaleCell(user, roleNode));
      } else {
        localeTd.appendChild(el("span", "users-muted", uiT("usr_all_languages", "All languages")));
      }
      tr.appendChild(localeTd);

      var lastTd = document.createElement("td");
      lastTd.appendChild(el("span", "users-muted", "—"));
      tr.appendChild(lastTd);

      var actTd = document.createElement("td");
      actTd.className = "users-actions";
      if (isSelf) {
        actTd.appendChild(el("span", "users-muted", "—"));
      } else {
        var remove = el("button", "btn", uiT("pc_remove", "Remove"));
        remove.type = "button";
        remove.addEventListener("click", function () {
          post("/api/auth/users/remove", { id: user.id }).then(function (result) {
            setStatus(result.ok ? uiT("usr_removed", "Removed.") : (result.error || uiT("usr_failed", "Failed.")));
            if (result.ok) load();
          });
        });
        actTd.appendChild(remove);
      }
      tr.appendChild(actTd);
      tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    wrap.appendChild(table);
    if (!list.length) {
      wrap.appendChild(el("p", "empty-state", uiT("usr_none", "No active users yet.")));
    }
    return wrap;
  }

  function paintGuide() {
    var grid = el("div", "users-role-guide");
    ROLE_GUIDE.forEach(function (role) {
      var card = el("div", "users-role-card");
      var roleTitle = el("div", "users-role-title", roleLabel(role.role));
      card.appendChild(roleTitle);
      var ul = el("ul", "users-role-list");
      role.lines.forEach(function (line) {
        var li = el("li", line[0] ? "is-yes" : "is-no");
        li.appendChild(el("span", "users-role-mark", line[0] ? "✓" : "—"));
        li.appendChild(document.createTextNode(uiT(line[1], line[2])));
        ul.appendChild(li);
      });
      card.appendChild(ul);
      grid.appendChild(card);
    });
    if (window.LLMHelp && grid.firstChild) {
      var roleHelp = window.LLMHelp.helpBtn("users:roles");
      grid.firstChild.querySelector(".users-role-title").appendChild(roleHelp);
    }
    return grid;
  }

  function paint() {
    root.replaceChildren();
    var pending = state.users.filter(function (u) { return u.status === "pending"; });
    var active = state.users.filter(function (u) {
      return u.status === "approved" || (u.status !== "pending" && u.status !== "denied");
    });

    if (state.accountProject) {
      root.appendChild(el(
        "p", "users-account-note",
        uiT(
          "users_account_note",
          "Accounts are shared for this server (workspace: {name}). The project switcher only changes catalogues.",
        ).replace("{name}", state.accountProject),
      ));
    }

    if (pending.length) {
      var banner = el("div", "users-banner");
      banner.appendChild(el(
        "span", "",
        uiT(
          pending.length === 1 ? "usr_banner_one" : "usr_banner_many",
          pending.length === 1
            ? "1 user pending approval — review their access requests below."
            : "{n} users pending approval — review their access requests below.",
        ).replace("{n}", String(pending.length)),
      ));
      var jump = el("a", "", uiT("usr_view_pending", "View pending →"));
      jump.href = "#pending";
      banner.appendChild(jump);
      root.appendChild(banner);
      root.appendChild(paintPending(pending));
    }

    root.appendChild(paintActive(active));
    root.appendChild(paintGuide());
    var statusNode = el("p", "empty-state", state.status);
    statusNode.setAttribute("data-users-status", "1");
    root.appendChild(statusNode);
  }

  function loadLocales() {
    var name = project();
    if (!name) return Promise.resolve([]);
    return fetch("/api/overview-lite?project=" + encodeURIComponent(name))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        state.locales = (data && (data.activeLocales || data.targets)) || [];
        return state.locales;
      })
      .catch(function () {
        state.locales = [];
        return state.locales;
      });
  }

  function loadMe() {
    var headers = {};
    if (window.__LLM_TOKEN) headers["X-LLM-Token"] = window.__LLM_TOKEN;
    return fetch("/api/auth/me", { headers: headers, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (me) {
        state.meId = me && me.user ? me.user.id : null;
        state.isAdmin = !!(me && me.authenticated && me.role === "Admin");
        var inviteBtn = document.getElementById("invite-open");
        if (inviteBtn) inviteBtn.hidden = !state.isAdmin;
      })
      .catch(function () {
        state.meId = null;
        state.isAdmin = false;
      });
  }

  function load() {
    var name = project();
    if (!name) {
      root.replaceChildren(el("p", "empty-state", uiT("ed_select_project", "Select a project…")));
      return;
    }
    root.replaceChildren(el("p", "empty-state", uiT("usr_loading", "Loading users…")));
    Promise.all([loadLocales(), loadMe()]).then(function () {
      if (!state.isAdmin) {
        root.replaceChildren(el("p", "empty-state", uiT("set_admin_required", "Admin required.")));
        return;
      }
      return post("/api/auth/users", {});
    }).then(function (data) {
      if (!data) return;
      if (!data.ok) {
        root.replaceChildren(el("p", "empty-state", data.error || uiT("set_admin_required", "Admin required.")));
        return;
      }
      state.users = data.users || [];
      state.invitePath = data.invitePath || "/register";
      state.accountProject = data.accountProject || "";
      paint();
    }).catch(function () {
      root.replaceChildren(el("p", "empty-state", uiT("setup_request_failed", "Request failed.")));
    });
  }

  (function () {
    var host = document.getElementById("users-head-actions");
    if (host && window.LLMHelp && !host.querySelector(".help-trigger")) host.appendChild(window.LLMHelp.helpBtn("users:general"));
  })();
  var inviteBtn = document.getElementById("invite-open");
  if (inviteBtn) {
    inviteBtn.addEventListener("click", openInvite);
  }

  select.addEventListener("change", function () {
    if (select.value) load();
  });
  if (select.value) load();
})();
