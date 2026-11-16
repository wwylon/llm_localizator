# ADR-118 — Shipped web runtime, `runtime` and `check-keys`

**Status:** accepted (2026-11-05)

Three consumer apps each carried their own
`i18n.js`. Two were byte-identical. The third was a fork with a
synchronous load, a `/xx/` path prefix, a cookie, and a MutationObserver for its
template runtime. Fixes went out by patching three copies with scripts. Two
consumer tests then broke on wiring details nobody checked: keys used in code but
missing from en.json, and an en-XX catalogue left stale after en.json grew.

Decision:
- **One versioned runtime** lives in the package at
  `llm_localize/web_runtime/i18n.js`, with `llm-localize web runtime vX.Y.Z` in
  its header. The fork's differences became options in `window.I18N_CONFIG`:
  `sync`, `observe`, `pathPrefix`, `cookie`, `prefsKey`, `url`, `navigator`,
  `applySource`, `skipSelector`, `rtl` and `textScale`. The defaults reproduce
  the two identical copies' behaviour, with two intended changes:
  - an element with child elements is no longer rewritten (the fork's rule);
  - `#` in a plural is replaced only at its own nesting level.

  `selectordinal` and `i18n.has` / `dir` / `version` / `pluralCategory` were added.
- **Consumer copy is ours, config is theirs.** `llm-localize runtime install`
  copies the file to `[web] runtime_path`, and writes an `i18n.config.js`
  template only when none exists. `update` replaces only our file, and refuses a
  file without our header unless `--force` is given. `check` exits 1 when the
  copy is missing, outdated or locally edited.
- **`check-keys`** is the no-LLM wiring test consumers run in their own CI:
  - literal keys in `[scan] src_dirs` against the source catalogue;
  - unused keys, with template and concatenation prefixes counted as covering
    the keys under them;
  - QA-locale staleness, by regenerating `pseudo` output in memory and comparing
    it with the file, not by counting keys.

  Exit codes: 0 clean, 1 findings, 2 configuration.
- Both commands are **CLI-only**. `runtime` writes into the consumer repo, which
  the web UI never does. `check-keys` is a CI check. Neither is in `/api/ops`
  (the ADR-14 parity exception, same as `web` and `mcp`).
- Tests: `node --test tests/web_runtime/i18n.test.mjs` runs the runtime in a vm
  context with a fake window. It covers ICU, pl/ar plural categories, QA rules,
  locale order, RTL and zoom, sync loading, DOM rules and overlay gating. The ops
  are covered by pytest.

Consumers are not migrated here. Replacing their copies needs the owner's
go-ahead: run `runtime install --force` per repo, and for an app like the fork set
`sync: true, pathPrefix: true, cookie: true, prefsKey: 'app.prefs',
navigator: false, applySource: false, skipSelector: 'x-dc',
url: '/api/locales/{locale}'`.
