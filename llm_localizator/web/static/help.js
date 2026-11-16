(function (root) {
  var HELP = {};
  var ready = null;

  function uiT(key, fallback) {
    return (root.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function locale() {
    if (root.uiLocale && root.uiLocale.current) return root.uiLocale.current;
    if (root.__LLM_UI_LOCALE) return root.__LLM_UI_LOCALE;
    return "en";
  }

  function loadHelp(loc) {
    var qa = loc === "en-XX" || loc === "en-XA";
    return fetch("/locales/help/" + encodeURIComponent(loc) + ".json")
      .then(function (r) {
        if (!r.ok) throw new Error("help " + loc);
        return r.json();
      })
      .catch(function () {
        // QA marker locales must not fall back to English (leftover hunt).
        if (loc === "en" || qa) return {};
        return fetch("/locales/help/en.json").then(function (r) {
          if (!r.ok) return {};
          return r.json();
        }).catch(function () { return {}; });
      })
      .then(function (dict) {
        HELP = dict || {};
        return HELP;
      });
  }

  function ensure() {
    if (!ready) ready = loadHelp(locale());
    return ready;
  }

  // Refresh when UI locale finishes applying.
  if (root.uiLocale && root.uiLocale.set) {
    var prev = root.uiLocale.set.bind(root.uiLocale);
    root.uiLocale.set = function (loc, opts) {
      return prev(loc, opts).then(function () {
        ready = loadHelp(loc);
        return ready;
      });
    };
  }
  ensure();

  function showHelp(key) {
    ensure().then(function () {
      var entry = HELP[key];
      if (!entry) return;
      _showHelpEntry(entry);
    });
  }

  function _showHelpEntry(entry) {
    var overlay = document.createElement("div");
    overlay.className = "help-overlay";
    var modal = document.createElement("div");
    modal.className = "help-modal";
    var head = document.createElement("div");
    head.className = "help-modal-head";
    var title = document.createElement("strong");
    title.textContent = entry.title;
    var close = document.createElement("button");
    close.type = "button";
    close.className = "btn help-close";
    close.textContent = "×";
    close.setAttribute("aria-label", uiT("help_close_aria", "Close help"));
    close.addEventListener("click", function () { overlay.remove(); });
    head.appendChild(title);
    head.appendChild(close);
    modal.appendChild(head);
    var body = document.createElement("div");
    body.className = "help-modal-body";
    var list = null;
    entry.body.split("\n").forEach(function (line) {
      if (!line.trim()) { list = null; return; }
      if (/^\s*•/.test(line)) {
        if (!list) {
          list = document.createElement("ul");
          body.appendChild(list);
        }
        var li = document.createElement("li");
        var text = line.replace(/^\s*•\s*/, "");
        var cut = text.indexOf(" – ");
        if (cut > 0 && cut < 40) {
          var term = document.createElement("strong");
          term.textContent = text.slice(0, cut);
          li.appendChild(term);
          li.appendChild(document.createTextNode(text.slice(cut)));
        } else {
          li.textContent = text;
        }
        list.appendChild(li);
        return;
      }
      list = null;
      var isHead = /:$/.test(line) && line.length < 60;
      var p = document.createElement(isHead ? "h3" : "p");
      p.textContent = line;
      body.appendChild(p);
    });
    modal.appendChild(body);
    overlay.appendChild(modal);
    function onKey(ev) {
      if (ev.key === "Escape") { overlay.remove(); }
    }
    document.addEventListener("keydown", onKey);
    new MutationObserver(function (_m, obs) {
      if (!document.body.contains(overlay)) {
        document.removeEventListener("keydown", onKey);
        obs.disconnect();
      }
    }).observe(document.body, { childList: true });
    overlay.addEventListener("click", function (ev) {
      if (ev.target === overlay) overlay.remove();
    });
    document.body.appendChild(overlay);
  }

  function helpBtn(key) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn help-trigger";
    btn.textContent = "?";
    btn.setAttribute("aria-label", uiT("help_aria", "Help"));
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      showHelp(key);
    });
    return btn;
  }

  function has(key) {
    return Object.prototype.hasOwnProperty.call(HELP, key);
  }

  root.LLMHelp = { showHelp: showHelp, helpBtn: helpBtn, has: has, ensure: ensure };
})(window);
