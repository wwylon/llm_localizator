/* Font scale + color scheme prefs (Track B) — icon + option menu. */
(function (global) {
  "use strict";

  function uiT(key, fallback) {
    return (global.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function fonts() {
    return [
      { value: "current", label: uiT("appear_font_current", "Current") },
      { value: "bigger", label: uiT("appear_font_bigger", "Bigger") },
      { value: "biggest", label: uiT("appear_font_biggest", "Biggest") },
    ];
  }
  function themes() {
    return [
      { value: "light", label: uiT("appear_theme_light", "Light") },
      { value: "dark", label: uiT("appear_theme_dark", "Dark") },
    ];
  }
  var ICON_FONT =
    '<svg class="ui-chrome-icon" viewBox="0 0 16 16" aria-hidden="true">' +
    '<path d="M3 13L7 3h2l4 10h-2.1l-.8-2.2H5.9L5.1 13H3zm3.3-3.8h3.4L8 5.4 6.3 9.2z" ' +
    'fill="currentColor"/></svg>';
  var ICON_THEME =
    '<svg class="ui-chrome-icon" viewBox="0 0 16 16" aria-hidden="true">' +
    '<path d="M8 2.2a5.8 5.8 0 100 11.6A5.8 5.8 0 008 2.2zm0 1.2a4.6 4.6 0 014.55 3.9A4.7 4.7 0 018 12.6V3.4z" ' +
    'fill="currentColor"/></svg>';

  function read(key, fallback) {
    try {
      return global.localStorage.getItem(key) || fallback;
    } catch (err) {
      return fallback;
    }
  }

  function write(key, value) {
    try { global.localStorage.setItem(key, value); } catch (err) { /* ignore */ }
  }

  function currentFont() {
    var font = read("llm_ui_font", "current");
    return fonts().some(function (f) { return f.value === font; }) ? font : "current";
  }

  function currentTheme() {
    var theme = read("llm_ui_theme", "light");
    return themes().some(function (t) { return t.value === theme; }) ? theme : "light";
  }

  function apply() {
    var font = currentFont();
    var theme = currentTheme();
    document.documentElement.setAttribute("data-font", font);
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme === "dark" ? "dark" : "light";
    var fontBtn = document.getElementById("ui-chrome-font");
    if (fontBtn) {
      var fontLabel = (fonts().filter(function (f) { return f.value === font; })[0] || {}).label || font;
      fontBtn.title = uiT("appear_font_title", "Font: {name}").replace("{name}", fontLabel);
    }
    var themeBtn = document.getElementById("ui-chrome-theme");
    if (themeBtn) {
      var themeLabel = (themes().filter(function (t) { return t.value === theme; })[0] || {}).label || theme;
      themeBtn.title = uiT("appear_theme_title", "Theme: {name}").replace("{name}", themeLabel);
    }
    if (global.LLMChrome) {
      var fontPop = fontBtn && fontBtn.parentElement
        ? fontBtn.parentElement.querySelector(".ui-chrome-menu")
        : null;
      var themePop = themeBtn && themeBtn.parentElement
        ? themeBtn.parentElement.querySelector(".ui-chrome-menu")
        : null;
      if (fontPop) global.LLMChrome.markSelected(fontPop, font);
      if (themePop) global.LLMChrome.markSelected(themePop, theme);
    }
  }

  function inject() {
    if (!global.LLMChrome || !document.getElementById("lang-sel-mount")) return;
    if (!document.getElementById("ui-chrome-font")) {
      global.LLMChrome.addControl({
        id: "ui-chrome-font",
        label: uiT("appear_font_size", "Font size"),
        order: 2,
        icon: ICON_FONT,
        build: function (pop) {
          global.LLMChrome.fillMenu(pop, fonts(), currentFont(), function (value) {
            write("llm_ui_font", value);
            apply();
          });
        },
        onOpen: function (pop) {
          global.LLMChrome.markSelected(pop, currentFont());
        },
      });
    }
    if (!document.getElementById("ui-chrome-theme")) {
      global.LLMChrome.addControl({
        id: "ui-chrome-theme",
        label: uiT("appear_color_scheme", "Color scheme"),
        order: 3,
        icon: ICON_THEME,
        build: function (pop) {
          global.LLMChrome.fillMenu(pop, themes(), currentTheme(), function (value) {
            write("llm_ui_theme", value);
            apply();
          });
        },
        onOpen: function (pop) {
          global.LLMChrome.markSelected(pop, currentTheme());
        },
      });
    }
    apply();
  }

  apply();
  function boot() {
    var ready = (global.uiLocale && typeof global.uiLocale.whenReady === "function")
      ? global.uiLocale.whenReady()
      : Promise.resolve();
    ready.then(function () {
      inject();
      apply();
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  document.addEventListener("llm-ui-locale", function () {
    apply();
    var fontBtn = document.getElementById("ui-chrome-font");
    var themeBtn = document.getElementById("ui-chrome-theme");
    if (fontBtn) {
      fontBtn.setAttribute("aria-label", uiT("appear_font_size", "Font size"));
      fontBtn.setAttribute("title", uiT("appear_font_size", "Font size"));
    }
    if (themeBtn) {
      themeBtn.setAttribute("aria-label", uiT("appear_color_scheme", "Color scheme"));
      themeBtn.setAttribute("title", uiT("appear_color_scheme", "Color scheme"));
    }
  });

  global.LLMAppearance = { apply: apply, inject: inject };
})(window);
