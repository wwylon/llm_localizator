# Web runtime (`i18n.js`)

llm-localizator ships one small browser runtime for consumers whose UI is plain
JavaScript, HTML templates, or a template runtime that renders before any promise
resolves. It reads the flat JSON catalogues llm-localizator writes, formats a subset
of ICU, applies `data-i18n*` attributes, sets `lang` / `dir`, scales CJK text,
handles the URL-only QA marker locale (`en-XX`), and loads the translator overlay
on localhost. Decision record: [ADR-118](decisions/ADR-118-shipped-web-runtime.md).

React / Next.js apps that already use `next-intl` or similar do not need it.

## Install

```toml
# .llm-localize.toml
[web]
runtime_path = "web/static/js"   # a directory (i18n.js goes inside) or a .js path
```

```bash
llm-localizator runtime install myproject   # writes i18n.js, and i18n.config.js once
llm-localizator runtime check myproject     # exit 1: missing, edited, or outdated
llm-localizator runtime update myproject    # replace the copy with the shipped version
```

`i18n.js` is ours: it starts with `llm-localizator web runtime vX.Y.Z` and is
replaced as a whole by `update`. Do not edit it; `check` reports a local edit as
`modified`. `install` refuses to overwrite a file without that header unless you
pass `--force`.

`i18n.config.js` is yours. `install` writes it from a template only when it does
not exist, and `update` never touches it. Load it first:

```html
<script src="/static/js/i18n.config.js"></script>
<script src="/static/js/i18n.js"></script>
```

Put `llm-localizator runtime check <project>` and `llm-localizator check-keys <project>`
in the consumer's CI or test suite; both exit non-zero on findings.

## Options (`window.I18N_CONFIG`)

| Option | Default | Meaning |
|--------|---------|---------|
| `base` | `'/static/locales'` | Catalogue directory; files are `<base>/<code>.json` |
| `url` | — | URL template instead of `base`, e.g. `'/api/locales/{locale}'` |
| `source` | `'en'` | Source locale, and the fallback for keys a locale lacks or leaves empty |
| `locales` | `[source]` | Real locales in picker order (`i18n.locales`) |
| `qaLocales` | `['en-XX']` | URL-only QA marker locales (ADR-110) |
| `storageKey` | `'app_lang'` | localStorage key (and cookie name) for the user's choice |
| `cookie` | `false` | Also read and write the choice as a cookie, so the server can see it |
| `prefsKey` | — | localStorage JSON object whose `.lang` also holds the choice |
| `navigator` | `true` | Fall back to `navigator.language` (`pl-PL` matches `pl`) |
| `pathPrefix` | `false` | `/<code>/page.html` selects the locale; `setLocale` keeps the prefix |
| `sync` | `false` | Load catalogues with a blocking request before the script returns |
| `observe` | same as `sync` | Patch `data-i18n*` nodes as they are inserted (MutationObserver) |
| `applySource` | `true` | Apply the DOM in the source locale too (set `false` when markup is already English) |
| `skipSelector` | — | Never touch nodes inside this selector (e.g. raw template sources) |
| `rtl` | `['ar','he','fa','ur','ckb','ps','dv','yi','sd','ug']` | Base codes that get `dir="rtl"` |
| `textScale` | `{zh:1.15, ja:1.1, ko:1.1}` | Body zoom per base code, for px-based CSS |
| `overlay` | — | `{enabled, api, project, flatNs, localOnly}`: the translator overlay |

Locale choice, in order: path prefix → `?lang=` → cookie → localStorage → prefs →
navigator → source.

**QA locales** come only from the URL (`?lang=en-XX` or `/en-XX/…`). They are held
for the tab in sessionStorage so links keep working, never written to
localStorage, cookie or prefs, and never listed in `i18n.locales`. Picking a real
language clears them. Regenerate the catalogue with
`llm-localizator pseudo <project> --locale en-XX`; `check-keys` reports it stale
when the English keys or text change.

**Overlay.** Loaded only when `overlay.enabled`, the page is on localhost
(unless `localOnly: false`), and the page was opened once with `?translate=1`
(remembered; `?translate=0` turns it off). It needs `llm-localizator web` at
`overlay.api`; saving from the page also needs `[web] overlay_edit = true`.

## API

| Member | |
|--------|---|
| `i18n.t(key, vars?)` | Formatted message; the key itself when no catalogue has it |
| `i18n.has(key)` | Whether the current or source catalogue has the key |
| `i18n.format(msg, vars)` | Format an ICU message directly |
| `i18n.applyDOM(root?)` | Apply `data-i18n*` under `root` (call after rendering markup) |
| `i18n.setLocale(code)` | Store a real locale and reload into it; QA codes are ignored |
| `i18n.locale`, `i18n.dir`, `i18n.isQa`, `i18n.locales`, `i18n.source`, `i18n.version` | State |
| `i18n.pluralCategory(n, ordinal?)` | `Intl.PluralRules` category for the current locale |
| `i18n.whenReady()` | Promise resolved once catalogues are loaded (already resolved with `sync`) |

## Wiring rules

These are the rules `check-keys`, the scanner and the translator rely on.

1. **Literal keys.** Call `i18n.t('area.thing')` with a string literal, or put the
   key in `data-i18n="area.thing"`. `check-keys` verifies every literal key exists
   in the source catalogue. A computed key (`i18n.t(name)`) cannot be checked; if
   you need one, keep a literal prefix (`` i18n.t(`filter.kind.${kind}`) `` or
   `i18n.t('filter.kind.' + kind)`) so the keys under it are not reported unused.
2. **Attributes.** User-visible attributes get their own key:
   `data-i18n-title`, `data-i18n-placeholder`, `data-i18n-aria-label`,
   `data-i18n-alt`. Keep the English text in the markup as well.
3. **Innermost element.** A `data-i18n` element with child elements is never
   rewritten, so an icon next to a label is safe. Put the key on the text's own
   `<span>`.
4. **ICU for counts and choices.** Never build `n + ' files'` or pick between two
   keys by count. Write `{n, plural, one {# file} other {# files}}` in en.json;
   Polish and Arabic need more categories, and the translator supplies them.
   Use `select` for gender or kind, `selectordinal` for 1st/2nd.
5. **Whole sentences.** One key per sentence or label, with `{placeholders}` for
   the variable parts. Never concatenate translated fragments
   (`t('a') + name + t('b')`): word order differs between languages.
6. **What stays literal.** Brand and product names, code identifiers, units the
   UI shows as symbols, user data, log lines and developer-only debug text. If a
   string is visible to users and is not one of these, it needs a key; `en-XX`
   shows the leftovers as readable English among the `XXXX`.
7. **Dynamic markup.** After inserting markup that carries `data-i18n*`, call
   `i18n.applyDOM(node)`, or set `observe: true`.

## `check-keys`

```bash
llm-localizator check-keys myproject          # exit 1 on missing keys or stale en-XX
llm-localizator check-keys myproject --strict # also exit 1 on unused keys
llm-localizator check-keys myproject --json
```

It scans `[scan] src_dirs` (minus `[scan] exclude` and the scanner's skipped
directories) for `i18n.t('…')`, dotted `t('…')`, `data-i18n*="…"`,
`setAttribute('data-i18n…', '…')` and `'data-i18n…': '…'` properties. Block and
HTML comments are ignored, and so is the installed runtime. It reports:

- **missing**: a used key the source catalogue lacks (with `file:line`);
- **unused**: a source key nothing uses and no dynamic prefix covers;
- **stale**: a QA locale (`[web] qa_locales`, or `en-XX` when its file exists)
  whose keys or text differ from what `pseudo` would write now.
