(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || !root) return;
  var kind = page.dataset.page;

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
    if (select && select.value) return select.value;
    try {
      var saved = localStorage.getItem("llm_project");
      if (saved) return saved;
    } catch (e) {}
    return "";
  }

  function post(path, body) {
    body = body || {};
    var name = project();
    if (name) body.project = name;
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    }).then(function (response) {
      return response.json().then(function (data) {
        return { status: response.status, data: data };
      });
    });
  }

  function field(label, type, id) {
    var wrap = el("label", "field", label);
    var input = document.createElement("input");
    input.type = type;
    input.id = id;
    input.autocomplete = type === "password" ? "current-password" : "username";
    wrap.appendChild(input);
    return { wrap: wrap, input: input };
  }

  if (kind === "login" || kind === "register") {
    root.appendChild(el(
      "h1", "",
      kind === "login"
        ? uiT("auth_sign_in", "Sign in")
        : uiT("auth_create_account", "Create account"),
    ));
    var sub = el("p", "auth-sub", "");
    if (kind === "login") {
      sub.appendChild(document.createTextNode(uiT("auth_no_account", "Don't have an account? ")));
      var a = el("a", "", uiT("auth_create_one", "Create one →"));
      a.href = "/register";
      sub.appendChild(a);
    } else {
      sub.appendChild(document.createTextNode(uiT("auth_already", "Already registered? ")));
      var b = el("a", "", uiT("auth_sign_in_arrow", "Sign in →"));
      b.href = "/login";
      sub.appendChild(b);
    }
    root.appendChild(sub);
    var status = el("p", "empty-state", "");
    var user = field(uiT("auth_username", "Username"), "text", "auth-user");
    var pass = field(uiT("auth_password", "Password"), "password", "auth-pass");
    var btn = el(
      "button", "btn btn-primary",
      kind === "login"
        ? uiT("auth_sign_in_arrow", "Sign in →")
        : uiT("auth_create_account_arrow", "Create account →"),
    );
    btn.type = "button";
    root.appendChild(user.wrap);
    root.appendChild(pass.wrap);
    root.appendChild(btn);
    root.appendChild(status);
    btn.addEventListener("click", function () {
      status.textContent = uiT("auth_working", "Working…");
      var path = kind === "login" ? "/api/auth/login" : "/api/auth/register";
      post(path, {
        username: user.input.value,
        password: pass.input.value,
      }).then(function (result) {
        if (!result.data.ok) {
          status.textContent = result.data.error || uiT("auth_failed", "Failed.");
          return;
        }
        if (result.data.pending || (result.data.user && result.data.user.status === "pending")) {
          location.href = "/pending";
          return;
        }
        location.href = result.data.first ? "/setup" : "/app";
      }).catch(function () {
        status.textContent = uiT("setup_request_failed", "Request failed.");
      });
    });
    return;
  }

  if (kind === "pending") {
    var note = el("p", "empty-state", uiT("dash_loading", "Loading…"));
    root.appendChild(note);
    fetch("/api/auth/me" + (project() ? ("?project=" + encodeURIComponent(project())) : ""), {
      credentials: "same-origin",
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (!data.authenticated) {
        note.textContent = uiT("auth_sign_in_pending", "Sign in to see your approval status.");
        var go = el("a", "", uiT("auth_sign_in", "Sign in"));
        go.href = "/login";
        root.appendChild(go);
        return;
      }
      if (data.pending || (data.user && data.user.status === "pending")) {
        note.textContent = uiT(
          "auth_pending_msg",
          "Your account is pending Admin approval. You can browse this page but cannot save translations yet.",
        );
        return;
      }
      if (data.user && data.user.status === "denied") {
        note.textContent = uiT("auth_denied", "Your registration was denied.");
        return;
      }
      note.textContent = uiT("auth_approved", "Your account is approved.");
      var home = el("a", "", uiT("auth_open_dashboard", "Open dashboard"));
      home.href = "/app";
      root.appendChild(home);
    }).catch(function () {
      note.textContent = uiT("auth_session_fail", "Could not load session.");
    });
  }
})();
