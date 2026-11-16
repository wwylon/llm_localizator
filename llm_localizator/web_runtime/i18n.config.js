// Localization settings, loaded before i18n.js (llm-localizator web runtime).
// Written once by `llm-localizator runtime install`; this file is yours to edit,
// `runtime update` never touches it. Every option is listed in docs/web-runtime.md.
window.I18N_CONFIG = {
  // Where the catalogues are served: <base>/<code>.json. Use `url` instead for an
  // API route, e.g. url: '/api/locales/{locale}'.
  base: '/static/locales',
  storageKey: '__PROJECT___lang',
  // Real locales, in picker order. Frozen layout locales may be listed too.
  locales: __LOCALES__,
  // URL-only QA marker locales (?lang=en-XX): never offered, never persisted.
  qaLocales: ['en-XX'],
  textScale: { zh: 1.15 },
  // sync: true loads catalogues with a blocking request, for UI runtimes that
  // render templates before any promise could resolve (they also want observe).
  // sync: true, observe: true,
  // pathPrefix: true,   // /pl/page.html selects the locale
  // cookie: true,       // let the server see the choice
  // llm-localizator translator overlay: CTRL to inspect, CTRL+click to edit in place.
  // Needs `llm-localizator web` running; open the app with ?translate=1 to load it.
  // Saving from the page also needs [web] overlay_edit = true in .llm-localize.toml.
  overlay: { enabled: true, api: 'http://127.0.0.1:8770', project: '__PROJECT__', flatNs: '' },
};
