(function () {
  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  /* Compact sidebar chrome: icon row + popovers (language / font / theme / profile). */
  if (!window.LLMChrome) {
    (function (global) {
      var wired = false;

      function ensureBar() {
        var mount = document.getElementById("lang-sel-mount");
        if (!mount) return null;
        var bar = mount.querySelector(".ui-chrome-bar");
        if (!bar) {
          bar = document.createElement("div");
          bar.className = "ui-chrome-bar";
          mount.insertBefore(bar, mount.firstChild);
        }
        return bar;
      }

      function closeAll(except) {
        document.querySelectorAll(".ui-chrome-item.is-open").forEach(function (item) {
          if (except && item === except) return;
          item.classList.remove("is-open");
          var btn = item.querySelector(".ui-chrome-btn");
          var pop = item.querySelector(".ui-chrome-pop");
          if (btn) btn.setAttribute("aria-expanded", "false");
          if (pop) pop.hidden = true;
        });
      }

      function wireDismiss() {
        if (wired) return;
        wired = true;
        document.addEventListener("click", function () { closeAll(); });
        document.addEventListener("keydown", function (ev) {
          if (ev.key === "Escape") closeAll();
        });
      }

      function refreshEndAlign(bar) {
        if (!bar) return;
        var items = Array.prototype.slice.call(bar.children);
        var end = null;
        var endOrder = -Infinity;
        items.forEach(function (el) {
          el.classList.remove("is-end");
          var o = parseInt(el.style.order || "0", 10);
          if (!end || o >= endOrder) {
            end = el;
            endOrder = o;
          }
        });
        if (end) end.classList.add("is-end");
      }

      function addControl(opts) {
        var bar = ensureBar();
        if (!bar) return null;
        if (document.getElementById(opts.id)) return null;
        wireDismiss();
        var item = document.createElement("div");
        item.className = "ui-chrome-item";
        if (opts.order != null) item.style.order = String(opts.order);
        var btn = document.createElement("button");
        btn.type = "button";
        btn.id = opts.id;
        btn.className = "ui-chrome-btn" + (opts.btnClass ? " " + opts.btnClass : "");
        btn.setAttribute("aria-label", opts.label);
        btn.setAttribute("title", opts.label);
        btn.setAttribute("aria-haspopup", "menu");
        btn.setAttribute("aria-expanded", "false");
        btn.innerHTML = opts.icon;
        var pop = document.createElement("div");
        pop.className = "ui-chrome-pop ui-chrome-menu";
        pop.hidden = true;
        pop.setAttribute("role", "menu");
        pop.setAttribute("aria-label", opts.label);
        pop.addEventListener("click", function (ev) { ev.stopPropagation(); });
        if (opts.build) opts.build(pop, btn, item);
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          var open = item.classList.contains("is-open");
          closeAll();
          if (!open) {
            item.classList.add("is-open");
            btn.setAttribute("aria-expanded", "true");
            pop.hidden = false;
            if (opts.onOpen) opts.onOpen(pop, btn);
          }
        });
        item.appendChild(btn);
        item.appendChild(pop);
        bar.appendChild(item);
        refreshEndAlign(bar);
        return { item: item, btn: btn, pop: pop, close: function () { closeAll(); } };
      }

      /** Flat option buttons inside a chrome menu (no nested select / panel chrome). */
      function fillMenu(pop, choices, current, onPick) {
        pop.textContent = "";
        choices.forEach(function (choice) {
          var value = choice.value != null ? choice.value : choice[0];
          var label = choice.label != null ? choice.label : choice[1];
          var opt = document.createElement("button");
          opt.type = "button";
          opt.className = "ui-chrome-option" + (value === current ? " is-selected" : "");
          opt.setAttribute("role", "menuitemradio");
          opt.setAttribute("aria-checked", value === current ? "true" : "false");
          opt.dataset.value = value;
          opt.textContent = label;
          opt.addEventListener("click", function () {
            onPick(value, opt);
            closeAll();
          });
          pop.appendChild(opt);
        });
      }

      function markSelected(pop, current) {
        if (!pop) return;
        pop.querySelectorAll(".ui-chrome-option").forEach(function (opt) {
          var on = opt.dataset.value === current;
          opt.classList.toggle("is-selected", on);
          opt.setAttribute("aria-checked", on ? "true" : "false");
        });
      }

      global.LLMChrome = {
        ensureBar: ensureBar,
        addControl: addControl,
        closeAll: closeAll,
        fillMenu: fillMenu,
        markSelected: markSelected,
      };
    })(window);
  }

  if (window.uiLocale) return;

  var RTL = { ar: 1, he: 1, fa: 1, ur: 1 };
  // Base production langs. QA markers (en-XX / en-XA) only when the server
  // injects them via window.__LLM_UI_QA_LOCALES (ADR-110 / [web] qa_locales).
  var BASE_LANGS = [
    { code: "en", label: "English" },
    { code: "de", label: "Deutsch" },
    { code: "pl", label: "Polski" },
    { code: "fr", label: "Français" },
    { code: "ar", label: "العربية" },
  ];
  var QA_LANG_LABELS = {
    "en-XX": "XX marker (QA)",
    "en-XA": "XA accent (QA)",
  };
  var qaCodes = Array.isArray(window.__LLM_UI_QA_LOCALES)
    ? window.__LLM_UI_QA_LOCALES.filter(function (c) { return QA_LANG_LABELS[c]; })
    : [];
  var LANGS = BASE_LANGS.concat(qaCodes.map(function (code) {
    return { code: code, label: QA_LANG_LABELS[code] };
  }));
  var LANG_CODES = LANGS.map(function (row) { return row.code; });
  var cache = {};
  // Longer codes before shorter (en-XX before en).
  var LOCALE_PATH_RE =
    /^\/(en-XX|en-XA|en|de|pl|fr|ar)(?=\/app(?:\/|$)|\/login|\/register|\/pending|\/setup)/;
  var ICON_GLOBE =
    '<svg class="ui-chrome-icon" viewBox="0 0 16 16" aria-hidden="true">' +
    '<circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-width="1.25"/>' +
    '<path d="M1.75 8h12.5M8 1.75c-2 2.2-3 4.2-3 6.25s1 4.05 3 6.25c2-2.2 3-4.2 3-6.25s-1-4.05-3-6.25z" ' +
    'fill="none" stroke="currentColor" stroke-width="1.25"/></svg>';

  function ensureLang(code) {
    if (!code || LANG_CODES.indexOf(code) >= 0) return;
    if (!QA_LANG_LABELS[code]) return;
    LANGS.push({ code: code, label: QA_LANG_LABELS[code] });
    LANG_CODES.push(code);
  }

  function isAllowedLocale(code) {
    return !!code && (LANG_CODES.indexOf(code) >= 0 || !!QA_LANG_LABELS[code]);
  }

  function pathLocale() {
    var path = "";
    try { path = (location && location.pathname) || ""; } catch (err) { path = ""; }
    var m = path.match(LOCALE_PATH_RE);
    return m ? m[1] : null;
  }

  function stripLocale(pathname) {
    return (pathname || "").replace(LOCALE_PATH_RE, "") || pathname;
  }

  function withLocale(pathname, locale) {
    var bare = stripLocale(pathname);
    if (!bare || bare.charAt(0) !== "/") bare = "/" + (bare || "");
    if (bare === "/app" || bare.indexOf("/app/") === 0
        || bare === "/login" || bare === "/register"
        || bare === "/pending" || bare === "/setup"
        || bare.indexOf("/login") === 0) {
      return "/" + locale + bare;
    }
    return bare;
  }

  function setCookie(locale) {
    try {
      document.cookie = "llm_ui_locale=" + encodeURIComponent(locale)
        + "; Path=/; SameSite=Lax";
    } catch (err) { /* ignore */ }
  }

  function loadDict(locale) {
    if (cache[locale]) return Promise.resolve(cache[locale]);
    return fetch("/locales/" + encodeURIComponent(locale) + ".json")
      .then(function (response) {
        if (!response.ok) throw new Error("locale " + locale);
        return response.json();
      })
      .then(function (dict) {
        cache[locale] = dict || {};
        return cache[locale];
      })
      .catch(function () {
        cache[locale] = cache.en || {};
        return cache[locale];
      });
  }

  // Blocking first load: page scripts call uiT() while they build their DOM
  // (often before any promise settles), so the catalogue must already be in
  // the cache or English fallbacks get baked in. The browser caches the file.
  function loadDictSync(locale) {
    if (cache[locale]) return;
    try {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", "/locales/" + encodeURIComponent(locale) + ".json", false);
      xhr.send(null);
      if (xhr.status === 200) cache[locale] = JSON.parse(xhr.responseText) || {};
    } catch (err) { /* fall back to the async load */ }
  }

  function resolveInitial() {
    // Path wins over window seed, storage, and cookie (ADR-108).
    // Server-authorized QA markers in the URL / __LLM_UI_LOCALE seed must
    // win even when __LLM_UI_QA_LOCALES was missing (stale process) — otherwise
    // localStorage "pl" silently replaces /en-XX/… after first paint.
    var fromPath = pathLocale();
    if (fromPath && isAllowedLocale(fromPath)) {
      ensureLang(fromPath);
      return fromPath;
    }
    var seeded = window.__LLM_UI_LOCALE;
    if (seeded && isAllowedLocale(seeded)) {
      ensureLang(seeded);
      return seeded;
    }
    try {
      var stored = localStorage.getItem("llm_ui_locale");
      if (stored && LANG_CODES.indexOf(stored) >= 0) return stored;
    } catch (err) { /* ignore */ }
    return "en";
  }

  function UILocale() {
    this.current = resolveInitial();
    setCookie(this.current);
    try { localStorage.setItem("llm_ui_locale", this.current); } catch (err) { /* ignore */ }
    loadDictSync("en");
    if (this.current !== "en") loadDictSync(this.current);
    var self = this;
    // Pages that build chrome via uiT() must wait — otherwise English
    // fallbacks are baked into the DOM before the marker dict arrives.
    this._ready = loadDict("en").then(function () {
      return loadDict(self.current);
    }).then(function () {
      self._apply();
      self.ensureSelector();
      return self.current;
    });
  }

  UILocale.prototype.whenReady = function () {
    return this._ready || Promise.resolve(this.current);
  };

  UILocale.prototype.ensureSelector = function () {
    var mount = document.getElementById("lang-sel-mount");
    if (mount && !document.getElementById("ui-chrome-lang")) {
      this.injectSelector(mount);
    }
  };

  UILocale.prototype.set = function (locale, opts) {
    var self = this;
    opts = opts || {};
    if (LANG_CODES.indexOf(locale) < 0) locale = "en";
    return loadDict(locale).then(function () {
      self.current = locale;
      try { localStorage.setItem("llm_ui_locale", locale); } catch (err) { /* ignore */ }
      setCookie(locale);
      window.__LLM_UI_LOCALE = locale;
      self._apply();
      if (opts.navigate === false) return;
      try {
        var next = withLocale(location.pathname, locale) + location.search + location.hash;
        if (next !== location.pathname + location.search + location.hash) {
          location.assign(next);
        }
      } catch (err) { /* non-browser host */ }
    });
  };

  UILocale.prototype.t = function (key) {
    var dict = cache[this.current] || {};
    if (dict[key] != null) return dict[key];
    // Pseudo QA locales must not fall back to English — leftover hunt
    // needs missing keys to stay unresolved (uiT then uses its fallback).
    if (this.current === "en-XX" || this.current === "en-XA") return key;
    if (cache.en && cache.en[key] != null) return cache.en[key];
    return key;
  };

  /** Catalogue lookup with English fallback for JS-built UI (settings, cards, …). */
  window.uiT = function (key, fallback) {
    var loc = window.uiLocale;
    if (loc && typeof loc.t === "function") {
      var val = loc.t(key);
      if (val != null && val !== key) return val;
    }
    return fallback != null ? fallback : key;
  };

  UILocale.prototype._apply = function () {
    var isRtl = !!RTL[this.current];
    document.documentElement.lang = this.current;
    document.documentElement.dir = isRtl ? "rtl" : "ltr";
    var self = this;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      var val = self.t(key);
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        if (el.placeholder !== undefined) el.placeholder = val;
      } else if (el.tagName === "OPTION") {
        el.textContent = val;
      } else {
        el.textContent = val;
      }
    });
    var langBtn = document.getElementById("ui-chrome-lang");
    if (langBtn) {
      langBtn.setAttribute("data-locale", self.current);
      langBtn.title = uiT("uil_language", "Language:") + " " + self.current;
    }
    var langPop = langBtn && langBtn.parentElement
      ? langBtn.parentElement.querySelector(".ui-chrome-menu")
      : null;
    if (window.LLMChrome && langPop) {
      window.LLMChrome.markSelected(langPop, self.current);
    }
    try {
      document.dispatchEvent(new CustomEvent("llm-ui-locale", {
        detail: { locale: self.current },
      }));
    } catch (err) { /* non-DOM host */ }
  };

  UILocale.prototype.injectSelector = function () {
    var self = this;
    if (!window.LLMChrome) return;
    window.LLMChrome.addControl({
      id: "ui-chrome-lang",
      label: uiT("uil_chrome", "UI language"),
      order: 1,
      icon: ICON_GLOBE,
      build: function (pop) {
        window.LLMChrome.fillMenu(
          pop,
          LANGS.map(function (item) {
            return { value: item.code, label: item.label };
          }),
          self.current,
          function (code) { self.set(code); }
        );
      },
      onOpen: function (pop) {
        window.LLMChrome.markSelected(pop, self.current);
      },
    });
  };

  UILocale.prototype.withLocale = withLocale;
  UILocale.prototype.stripLocale = stripLocale;
  UILocale.prototype.pathLocale = pathLocale;

  window.uiLocale = new UILocale();
})();
