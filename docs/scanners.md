# Source scanners

Scanners read *source code*, not catalogues. They answer two questions no
catalogue check can:

- **which call site uses which key**, so a translator gets "this appears on the
  club roster screen" instead of a bare string;
- **which user-visible strings are hardcoded**, never reaching the catalogue at
  all — and a string that is not in the catalogue can never be translated.

A scanner is inherently framework-specific, which is exactly why it sits behind
an interface rather than in `core`.

## Operator / agent workflow (hardcoded hunt)

**Run from the project that owns the source.** The consumer agent in
that project runs the hunt and wires `t()` / `uiT` / `data-i18n` in that
checkout. The llm_localizator agent owns dogfood UI, scanner sinks, and this
machinery — it does not rewrite consumer trees (ADR-32). Report scanner gaps as
GitHub issues.

Short paste for coding agents: [agents.md](agents.md) § UI QA.

### Which English-leak path?

| Path | Catches | Command / harness |
|------|---------|-------------------|
| **Static** | Literals at known UI sinks | `llm-localizator agent-hardcoded` (prefer over bare `scan` for agent work) |
| **en-XX visual** | Anything the browser still paints as Latin after catalogue → `X`s | `pseudo --locale en-XX` + browse/crawl ([ADR-110](decisions/ADR-110-qa-marker-locales.md)) |
| **Layout / visual-findings** | Screenshot QA including reason `en_leak` | Consumer Playwright → `ingest-visual` ([visual-findings.md](visual-findings.md)) — **not** the same as en-XX |

Do not stop after a clean static report alone when the product has a review UI.

### Static loop

```text
1. llm-localizator agent-hardcoded --split auto --out-dir reports/hardcoded --refresh
   (default = high+medium; aim for 0 part-*.md)
2. Optional low pass: --show-low → separate out-dir; scan-decide ignore noise
3. Wire source to uiT / data-i18n / t() — scanner never rewrites files (ADR-32)
4. scan-decide accept|ignore → patch / apply --confirm (EN keys only)
5. translate targets via TQ; adopt after any hand catalogue edit
6. Re-run step 1
```

CI cheap gate: `llm-localizator scan --strict` (no agent split/cache semantics).
Agent paste-ready report: always `agent-hardcoded`.

### Visual loop (en-XX)

For the engine's own UI (dogfood) it needs `[web] qa_locales = ["en-XX"]` and a
**web restart**. Consumers do not: they use `[qa]` and `hardcoded-hunt --serve`
(below). The marker locale is never a translate target. The agent-facing loop is
`llm-localizator help agent` § 4.

```text
1. llm-localizator hardcoded-hunt   # dogfood: pseudo + crawl/intersect + static refresh
   # or manually:
   #   pseudo --locale en-XX   (re-run after every EN catalogue growth)
   #   Browse /en-XX/… or: python experiments/hardcoded_visible/crawl.py
   #   agent-hardcoded --refresh + python experiments/hardcoded_visible/intersect.py
2. Wire from leftovers.json (prefer page+selector over ripgrep_only)
3. pseudo again → TQ translate → clear qa_locales before production ship
```

Check readiness first: `llm-localizator agent-hardcoded --status` (JSON `next[]`,
en-XX lag). Dogfood crawl lives under `experiments/hardcoded_visible/`
(Playwright outside the package, ADR-27).

**Consumers** describe their UI once in a `[qa]` block
([configuration.md](configuration.md#qa)): base URL, pages, how a page is put
into a locale (`query`, `path` or `storage`), an optional start command and
clicks. Then `llm-localizator hardcoded-hunt <project>` (or
`crawl.py --project <name>`) writes the report under
`~/.llm_localize/data/<name>/qa/<ts>/`, never into the consumer repo:

- `leftovers.json`: Latin text still painted under en-XX, each marked
  `literal` when the text is a literal in `[scan] src_dirs`;
- `dynamic_text.json`: the leftovers that are **not** literals anywhere in the
  source (server or API text, runtime-assembled strings). The static scanner
  cannot see these, so they are the crawl's own findings;
- `layout.json` and `<locale>/*.png`: per layout locale (default ar/zh), whether
  `dir` is right and which text elements are clipped or off screen, with a
  full-page screenshot per page.

`hardcoded-hunt` does not start the consumer's server unless you pass `--serve`.
Without `[qa]`, the older flags still work
(`--locale-mode storage --storage-key <key>`, `crawl.py --preset taskqueue`). A consumer may keep its own browse-review capture
for layout QA. Checklist:
[consumer-localization-checklist.md](consumer-localization-checklist.md).

### Done criteria

- Zero high/medium parts under `reports/hardcoded/` (or only ignored decisions).
- Under en-XX, no unexpected Latin chrome. **Allowed Latin:** locale codes,
  CLI command ids, Intl language names, model ids, brand, intentional API text.
- EN and en-XX chrome key parity after pseudo. Help articles: if the project
  uses `locales/help/*.json`, en-XX help must exist too (chrome `pseudo` does
  not rewrite nested help).

### Help content formats (not one shape)

| Format | Example | Translate / hunt note |
|--------|---------|------------------------|
| Nested JSON `{title,body}` | dogfood `web/locales/help/` | Separate collection; pseudo chrome ≠ help file |
| Markdown tree | e.g. `content/help/` | Documents/`*.md` path when declared |
| HTML pages | arena `*/arena/web/help/*.html` | Declare an html collection; documents translate accepts `.html` / `.htm` (ADR-113) |

### Anti-patterns

- Hand-writing pl/de/ar instead of TQ translate
- Assuming the scanner will rewrite source
- Stale en-XX (EN grew; marker missing keys → English fallbacks look “hardcoded”)
- Treating `ripgrep_only` intersect rows as ground truth
- Adding `en-XX` to `[locales].targets` or shipping with `qa_locales` set

Sink promotion checklist and detector layers: sections below.

## The interface

```python
class Scanner(abc.ABC):
    @property
    @abc.abstractmethod
    def file_glob(self) -> str: ...            # e.g. "**/*.tsx"

    @abc.abstractmethod
    def scan_file(self, path: Path, lines: list[str], result: ScanResult) -> None: ...
```

The base class handles directory walking. Hard skips stay skipped even if
`[scan] unskip` names them: `node_modules`, `.next`, `__tests__`, `dist`,
`build`, `.turbo`, `.git`, plus `*.test.*`, `*.spec.*`, `*.stories.*`, and
`*.d.ts`. Soft skips are documentation and dev tooling: `docs`,
`documentation`, `scripts`, `storybook`, `__mocks__`, `fixtures`, `examples`,
`e2e`, `cypress`, `playwright`, `.github`, `experiments`, and the files
`README.*`, `CHANGELOG.*`, `CONTRIBUTING.*`. `[scan] unskip` puts a soft-skipped
path back. `[scan] exclude` only adds skips; it cannot undo a built-in one.
A path segment named `help` is not special — a product screen stays unless it
hits one of those names. `content/help` is a collection, not a scan root.

Human languages share one prose check (`llm_localizator/scan/prose.py`). A letter
is any Unicode letter. A literal is prose when it has a space or sentence
punctuation, two or more letters of an unsegmented script (CJK, Thai), or any
non-Latin letter. A single Latin word such as `Bridge` stays silent. Source
frameworks stay separate modules. Do not add a parser per human language.

## `next-intl` (also used for `react-intl`)

Recognises `useTranslations('ns')` and `getTranslations('ns')` to learn a file's
namespaces, then `t('key')` for call sites.

Namespace resolution: a known namespace wins, including `admin/users` written
as `t('admin.users.signIn')`. Otherwise a dotted key still splits on the first
dot (`t('play.claim')` → `play` / `claim`). A bare key uses the file's
namespace when there is exactly one. When a file declares several and the key
has no prefix, **the usage is skipped** — a guess would produce a wrong
backreference, which is worse than none. `raw-js` covers `i18n.t()` and
`data-i18n`.

## Hardcoded-string detection is deliberately conservative

A false positive costs a developer real time chasing a non-bug, so anything
ambiguous is left alone. Raise **recall with UI-sink context**, not by
loosening the shared prose gate alone.

Detection is a **dual loop**: a static sink report (`agent-hardcoded`) plus a
**visual leftover hunt** under `en-XX` (ADR-110). The static pass finds
literals at known call sites; the visual pass finds what the browser still
paints as Latin after every catalogue value is rewritten to `X`s.

### How detection improved (dogfood timeline)

| Layer | What changed | Why |
|-------|--------------|-----|
| **Sinks** | Grew `UI_HELPER_SINKS` and `el(...)` coverage in steps (`_SCAN_VERSION` 5→9) | Toolbar / status / SSR chrome never hit `button`/`confirm` alone; v9 adds multiline `el()` + label-array `.forEach`/`.map` |
| **Confidence** | Default = high+medium; `--show-low` for bare literals | Keeps the default report actionable; low is for ignore batches |
| **Negatives** | `scan/negatives.py` + corpus `must_not` | Event names, wire enums, already-routed `uiT` stay silent |
| **Decisions** | `scan-decide` loads low hits (`show_low=True`) | Protocol/API/docs noise can be ignored without polluting the default report |
| **Visual** | `pseudo --locale en-XX` + crawl/intersect | Catches missing keys, API English, and sinks the regex never saw |
| **Wire** | Prefer `uiT(key, "…")` / `data-i18n` / guide `detail_key` | Catalogue + marker locale; scanner never rewrites source (ADR-32) |

| **Literal context** (v11–13) | `scan/js_context.py` reads every JS/TS/JSX literal once and decides from context: object keys, comparisons, `t()` args and fallbacks, selectors, CSS, headers, units, prompts and translation tables are skipped; dialogs, UI property names (`label:`, `title=`), `createElement` children and prose in value positions are reported. HTML templates are rejoined across `${}`; inline `<script>` blocks and own-line markup text are scanned | Measured on the scanner bench: real UIs keep most copy in plain literals, not in named sinks (macro recall 0.16 → 0.71 at precision 0.82) |

**Measure before and after a rule change** with the scanner bench
(`experiments/scanner_bench/`, README there): ten sibling projects, oracle
and adjudication labels, recall/precision per confidence tier, missed-string
clusters. An iteration is accepted only if macro recall rises and no project
loses more than 2 points of precision.

**`_SCAN_VERSION`** (in `ops/agent_hardcoded.py`) must bump whenever a sink or
prose rule change should invalidate the per-file scan cache. Add a
`must_hit` / `must_not` corpus case in the same change.

### Decision layers

1. **Extract** — language-specific literals / JSX text / `el(...)` args.
2. **Context site** — is this a UI sink (`button`, `confirm(`, `aria-label`, …)?
3. **Prose gate** — `is_prose` (space / sentence punct / non-Latin / CJK).
4. **Widget single-word** — capitalised Latin word **only** at a known sink.
5. **Negatives** (`scan/negatives.py`) — routed `t(` / `i18n.t` / `uiT` /
   `data-i18n`; DOM event names (`change`, `click`, …); listener first-args
   (`addEventListener("…")`); non-user attrs (`type="button"`, `role=`);
   wire enums (`human`, `machine`, HTTP methods); lowercase CSS class lists
   (`btn btn-primary`); `_CODE_LIKE`; directives.
6. **Confidence** — `high` = clear sink + prose; `medium` = widget word,
   helper/SSR chrome, or weaker site; `low` = bare literal. Default reports
   show high+medium; `--show-low` includes low. `--split auto` writes
   agent-sized `part-*.md` **and** `part-*.json` (ADR-105).

Ignored without a sink:

- lines already containing `t(` / `uiT(` / `data-i18n`
- `<code>`, `<pre>`, `<script>`, `<style>`, `<svg>` content
- comments; interpolations (`{value}`); `_CODE_LIKE`
- **a single Latin word** away from a widget sink
- DOM events / listener API first-args / wire enums (even if a future
  widget-word rule would otherwise promote them)

Flagged, in any writing system (when context allows):

- multi-word prose or sentence punctuation
- non-Latin / CJK / Thai per `is_prose`
- `placeholder`, `title`, `alt`, `aria-label` attributes
- **raw-js:** `el("button"|"div"|"section"|…, class, TEXT)` (complete third
  arg; **multiline** `el(` calls via a whole-file pass; short `"No " + x`
  concat prefixes are skipped, multi-word concat prefixes are flagged),
  flat `["Header A", "Header B"].forEach` / API-tuple
  `[["user", "By translator"]].forEach` label arrays (skipped when the
  callback body already calls `uiT` / `i18n.t`, or the tuple key looks like
  `snake_case` catalogue id), `createTextNode("…")`, helper sinks
  `card` / `field` / `panel` / `section` / `setStatus` / `showError` /
  `say` / `action` (`UI_HELPER_SINKS`), quoted
  `.textContent=` / `.innerHTML=` (backtick or quotes),
  `confirm|alert|prompt("…")`
- **SSR / Python HTML fragments** (literal scan): `>System settings<` chrome
  at **medium** confidence so default `agent-hardcoded` shows them

Corpus promotion: `tests/scan/corpus/js/{must_hit,must_not}/` and
`tests/scan/corpus/py/must_hit/` — FP on must_not must stay 0 before enabling
a new sink in the default dogfood report.

### Promoting a new sink (checklist)

1. Add the call pattern in `scan/raw_js.py` (or the relevant scanner).
2. Add `must_hit` + `must_not` corpus cases; keep FP on must_not at 0.
3. Bump `_SCAN_VERSION` in `ops/agent_hardcoded.py`.
4. Wire dogfood leftovers through `uiT` / `data-i18n` (or SSR `data-i18n`).
5. Refresh: `agent-hardcoded` (default and `--show-low`) and, if chrome
   changed, `pseudo --locale en-XX` so the marker catalogue matches EN.

### Visual leftover hunt (pseudo locales)

Static sinks never see every painted string. A **marker locale** turns the
catalogue into unmistakable placeholders so leftover English stands out in the
running UI.

| Locale / style | Effect | Use |
|---|---|---|
| `en-XA` (default `accents`) | Accented letters + pad | Length / overflow stress |
| `en-XX` (`--style xxxx`) | Same-length `X` runs; placeholders kept | Browse UI: readable Latin English = hardcoded or missing key |

**Opt-in (ADR-110).** Marker locales are **not** `[locales].targets`. Enable
routing + the language-picker entry only when you need the hunt:

```toml
[web]
qa_locales = ["en-XX"]   # dogfood / local QA
# qa_locales = []        # production default — picker and /en-XX/… stay off
```

```text
1. Set [web] qa_locales = ["en-XX"] and restart `llm-localizator web`.
2. llm-localizator pseudo --locale en-XX
   (re-run after every EN catalogue growth — stale en-XX falls back to Latin)
3. Crawl painted leftovers (Playwright stays outside package runtime, ADR-27):
     python experiments/hardcoded_visible/crawl.py
   or open /en-XX/app… manually. Xs = catalogued; Latin letters = leftover.
4. Intersect with the static report + ripgrep:
     llm-localizator agent-hardcoded --split auto --out-dir reports/hardcoded --refresh
     python experiments/hardcoded_visible/intersect.py
5. Wire uiT / data-i18n / guide detail_key from intersect.md; translate pl;
   re-pseudo; rescan. Promote new sinks only when must_not stays clean.
6. Before shipping a consumer: clear qa_locales (or omit the key).
```

**Reading Latin under `en-XX`.** Not every leftover is a missing sink:

| Latin still visible | Likely cause | Fix |
|---------------------|--------------|-----|
| Wired `uiT("k", "English")` | Key absent from `en-XX.json` (stale pseudo) | Re-run `pseudo --locale en-XX` |
| Bare string in JS/SSR | Hardcoded | Route through `uiT` / `data-i18n` |
| Guide / ops API blurb | Server English | Prefer `detail_key` + `detail_vars` (or catalogue) |
| `Polish` / dates / CLI / brand | Intentional dynamic or proper noun | Leave, or template the label only |

`uiT` under `en-XX` / `en-XA` does **not** fall back to the English catalogue
(`ui-locale.js`); if the marker dict lacks the key it returns the key, then
`uiT` shows the English second argument — that looks like a leftover until
pseudo is refreshed.

Outputs land under `reports/hardcoded_visible/` (`leftovers.json`,
`intersect.json`). Operator notes: `experiments/hardcoded_visible/README.md`.
Agent loop: [agents.md](agents.md) § Introducing `en-XX`.

`scan` writes usage artefacts. `agent-hardcoded` writes nothing into source
(ADR-32). `--llm` is an optional third pass on ambiguous candidates, off by
default. Hits are tagged `regex` or `llm`.

`tests/scan/test_next_intl.py` and `tests/scan/test_raw_js.py` pin false-
positive cases so a future regex tweak cannot quietly start crying wolf.

## What the scanner covers and misses

Measured on third-party projects labelled by blind oracle agents (`experiments/scanner_bench/`); every held-out project and its
per-language numbers are in the generated `experiments/scanner_bench/TIER_REVIEW.md`. Recall (share of real UI strings found at
high+medium confidence) and precision vary from near 0 to 1.0 per project, depending on the ecosystem and where the text is kept.
Treat the output as a worklist to review, not a verdict.

**Tiers.** A language is **supported** only when at least three held-out projects (never used to tune the scanner) reach
recall >= 0.60 and precision >= 0.70 on that language's files, outnumbering the held-out projects below that bar; a supported
language is demoted when the projects below the bar outnumber those at it. After the last held-out set (2026-11-17, pools A-I, evidence
from v37–v58) that holds for JavaScript, TSX, HTML, Vue, Svelte, Astro, ERB (Rails views), XML UI files (Android layouts, storyboards, XAML,
FXML, Qt `.ui`) and Godot scenes (`.tscn`/`.tres`). TypeScript went back to basic (7 projects at the bar, 8 below). Python and Dart went back to basic: per-language held-out numbers for `.py` and `.dart` files are below the bar
(Python 0 of 10 projects; earlier whole-project scores were carried by Jinja templates).
Everything else that runs is **basic**: the shared literal detector with per-ecosystem UI sinks (`scan/ecosystems.py`), so it finds
text handed to known UI calls (medium or high confidence) and other prose (low). Languages with no scanner are reported as
"NOT scanned". The `agent-hardcoded` header lists every language it scanned with its tier. Why some stay basic, from the
held-out runs: Kotlin/Android (UI text is almost all `stringResource`; the remaining hits are previews and animation labels),
C# (`MessageBoxViewModel` properties and WPF initializers are still partly missed), Rust (clap doc comments, bare-word table
headers), C++ (no held-out app cloned), Swift (two held-out apps pass, three are required).

**Latest rounds (scanner v57, v58, v61, v64 and v67).** Pool F (2026-11-14, 30 projects) scored macro precision 0.65 and macro recall 0.59 at high+medium
confidence; pool G (2026-11-16, 19 projects, chosen for HAML, Astro, Go TUIs, QML, Godot, Swift, Discord bots, extensions, Vue,
React/Tauri and Flask/Jinja) scored 0.70 and 0.67. Pool H (2026-11-16, 21 projects: HAML, Go, TypeScript, Swift, Python desktop, Flutter; scanner v57) scored 0.75 and 0.59. Pool I (2026-11-17, 19 projects: Svelte, Vue, Rails, Elixir, QML, Java; scanner v58 and the placeholder-matching rule of benchmark metric 3) scored 0.80 and 0.68. Pool J (2026-11-17, 14 projects: Python desktop, Java UI, Phoenix, Flutter; scanner v61, the first round scored on a scanner not tuned on any of its projects since pool I) scored 0.84 and 0.47. Pool K (2026-11-17, 16 projects: Python desktop, JavaFX and Swing, Vue and EJS, Flutter; scanner v64, labelled blind before any scan) scored 0.79 and 0.51: the first fresh round after the pool J fixes, and the honest figure for v64 (the 0.71 recall measured on pool J after the fixes was development data). Pool L (2026-11-18, 17 projects: Python desktop, Java Swing and JavaFX, React, Svelte, Vue; scanner v67, labelled blind before any scan) scored 0.77 and 0.61: the first fresh round after the v65 to v67 fixes, which were written from pool K misses. Java desktop apps (jeveassets 0.24, algobuddy 0.40) and Python GUIs with their own `t()` catalogue (persian-ocr-app, precision 0.12) are the weak spots; web projects scored well. Over the 136 projects that is macro precision 0.74 and macro recall 0.59: about seven in ten of what it reports is right, and it finds about three in five of the labelled text. Pools H, I, J, K and L were scored with different scanner and matching versions, so read the combined figure as an average, not as one run. Pool I is now development data: later scanner changes (Java, HEEx) were written after seeing its misses, and pool J shows what a fresh round looks like: precision held, recall fell. Plain `.txt` resource files outside template folders (tdsm), Java text blocks and tooltips, and Python desktop text built in helper widgets are the biggest misses.
Pool G changed no tier: HAML reached 4 projects at the bar and 4 below, Go 4 at and 10 below, QML 1 at and 5 below, so they stay basic.
Precision varies a lot by project (0.12 to 1.00), so treat the output as a worklist.

**Held-out by storage pattern (scanner v38, 2026-11-11).** Twelve projects chosen for where their text lives (Electron menus,
QML, Godot, Kivy, Phoenix, Rails/HAML, Go cobra, Discord bots, Chrome extension, OpenAPI/Markdown docs), labelled by agents that
never saw scanner output and scored once. Macro precision 0.91, macro recall 0.34. By file kind, recall: code 0.54, templates
0.58, UI-definition files 0.32, manifests 0.16, content 0.00. So the scanner is precise on unseen projects but finds about a
third of the labelled text outside the mainstream JS/Python/Dart paths. No language gained or lost a tier from this set: no basic
language has three held-out apps at the bar. Known gaps: HAML/Slim/MDX views, Go cobra `Short`/`Long` strings, all-caps and
expression-built QML text, Markdown and YAML prose read at runtime, minified bundles with `\u` escapes. Details and per-project
numbers: `experiments/real_world_verify/SCANNER_FINDINGS.md`.

The per-language table in "Support matrix (generated)" further down is generated; do not edit it by hand
(`python -m tests.scan.matrix.docs_block`).

File types that usually hold UI copy but that no scanner reads (`.pug`, `.haml`, `.slim`, `.mdx`, `.clj`, `.groovy`) are
never skipped silently: `agent-hardcoded` prints a "NOT scanned" line with the counts, returns them as `unsupportedFiles` in
JSON, and `verify` marks stage S4 `unsupported`.

Known limits:

- **Wrapper names.** The scanner knows `t`, `$t`, `$_`, `$format`, `i18n.t`, `i18n.__`, `uiT`, `tr`, `gettext` and their `this.`
  forms. A project-specific wrapper (`translate_text`) is not recognised: its strings are reported as hardcoded, and keys
  passed to it are not counted as used (`validate --unused`, `check-keys`).
- **English-as-key projects** (`i18n.__('save changes')`): such strings are skipped as routed, but not registered as key usage.
- **Fallbacks and mixed text.** `value ?? 'Not available'`, a sentence broken by an inline `<a>`, and f-string fragments are
  often missed or split.
- **Data and names.** Demo content, language names written in their own language (`English`, `Deutsch`), brand names and
  developer-facing API errors are judgement calls; expect some false positives. Mark them with `l10n-ignore` or `dnt`.
- **Vue/Svelte expressions** are replaced by a placeholder before scanning, so a hit may read `Welcome back, {x}!`.

### Support matrix (generated)

<!-- support-matrix:begin -->
| Language | Extensions | Detector | Tier | Conformance matrix |
|---|---|---|---|---|
| astro | `.astro` | astro | supported | n/a |
| content | `.md` `.markdown` `.toml` `.json` `.plist` | content | basic | n/a |
| cpp | `.cpp` `.cc` `.cxx` `.hpp` `.hh` `.hxx` `.h` | literal | basic | 12/12 cells |
| csharp | `.cs` | literal | basic | 12/12 cells |
| dart | `.dart` | literal | basic | 12/12 cells |
| desktop | `.desktop` | propdef | basic | n/a |
| elixir | `.ex` `.exs` | literal | basic | 11/11 cells |
| erb | `.erb` `.ejs` `.jsp` `.gsp` | template | supported | 8/8 cells |
| freemarker | `.ftl` | template | basic | 7/7 cells |
| gdscript | `.gd` | literal | basic | n/a |
| go | `.go` | literal | basic | 12/12 cells |
| godot | `.tscn` `.tres` | propdef | supported | n/a |
| gotmpl | `.gohtml` `.tmpl` `.tpl` | template | basic | 7/7 cells |
| haml | `.haml` | indent | basic | n/a |
| handlebars | `.hbs` `.handlebars` `.mustache` | template | basic | 7/7 cells |
| heex | `.heex` `.leex` `.eex` | template | basic | n/a |
| html | `.html` `.htm` | html | supported | n/a |
| java | `.java` | literal | basic | 11/11 cells |
| javascript | `.js` `.mjs` `.cjs` | js | supported | 12/12 cells |
| jinja | `.twig` `.jinja` `.jinja2` `.j2` `.njk` `.liquid` | template | basic | 8/8 cells |
| kotlin | `.kt` `.kts` | literal | basic | 11/11 cells |
| kv | `.kv` | propdef | basic | n/a |
| lua | `.lua` | literal | basic | 8/8 cells |
| mdx | `.mdx` | mdx | basic | n/a |
| objc | `.m` `.mm` | literal | basic | n/a |
| php | `.php` | literal | basic | 12/12 cells |
| python | `.py` | literal | basic | 12/12 cells |
| qml | `.qml` | propdef | basic | n/a |
| razor | `.cshtml` `.razor` | template | basic | 7/7 cells |
| ruby | `.rb` `.rake` | literal | basic | 12/12 cells |
| rust | `.rs` | literal | basic | 11/11 cells |
| scala | `.scala` `.sc` | literal | basic | 11/11 cells |
| slim | `.slim` | indent | basic | n/a |
| svelte | `.svelte` | sfc | supported | n/a |
| swift | `.swift` | literal | basic | 12/12 cells |
| templ | `.templ` | templ | basic | n/a |
| tsx | `.tsx` `.jsx` | jsx | supported | n/a |
| typescript | `.ts` `.mts` `.cts` | literal | basic | 12/12 cells |
| vue | `.vue` | sfc | supported | n/a |
| xmlui | `.xml` `.xaml` `.ui` `.storyboard` `.xib` `.fxml` | xmlui | supported | n/a |
| not scanned | `.clj` `.groovy` `.jade` `.pug` | none | reported-only | n/a |
<!-- support-matrix:end -->

## Scanner versions

`_SCAN_VERSION` (`ops/agent_hardcoded.py`) is bumped on every scanner change; it invalidates every scan cache. Per-iteration measurements are in `experiments/scanner_bench/README.md` and `LEDGER.jsonl`.

| Version | Change |
|---|---|
| v48 | SwiftUI catalogue keys count as routed only when every Xcode target compiling the file ships `Localizable` (a file shared with a widget extension is still reported) |
| v49 | No output change: shared `scan/views.py` blanking helpers, one-pass dev-block blanking, and linear (not quadratic) duplicate checks in the JS context and SFC passes (M3/M4) |
| v50 | Pool D gaps: Go terminal-UI sinks (lipgloss `Render`, `key.WithHelp`, widget `.Title`/`Header`, `Label:`) and prose in bubbletea/tview/termui projects; Python user-facing exceptions (`BotError`, `UserError` …), slash-command `description=`, bare `send(…)` in bot modules; logger calls through attributes (`self._logger.info`) are developer text; Dart `body:`/`detail:` and switch-arm labels; Swift `headline:`/`detail:`/`summary:`; a one-letter `L("…")` wrapper counts as routed |
| v51 | GDScript (`.gd`) is scanned: Python-style literals with Godot sinks (`.text =` and any `*text`/`*title`/`*label`/`*message` property, `set_text(`, `add_item(`, `set_item_text(`, notifications); `print(` stays developer text (pool E: godotos) |
| v52 | QML text-named `property string` defaults, `model:`/`nameFilters:` lists, `return x \|\| "…"` fallbacks and the first line of a multi-line `text:`; freedesktop `.desktop` `GenericName=`/`Comment=`/`Keywords=` (and multi-word `Name=`); Jinja `.txt` bodies inside a `templates/` folder; web-service errors named after an HTTP status (`InvalidRequest`, `LimitExceeded`, …), `desc=`, `super().__init__(…, status=…)` and `"…".format()` messages; a lowercase code (`InvalidRequest('own')`) is not a message (pool E: quemusic, critiquebrainz) |
| v53 | Jinja/Django templates blank `{% blocktrans %}…{% endblocktrans %}` and `{% blocktranslate %}` bodies: already translated (h2-appointment `.txt` mails) |
| v54 | M2 high-severity fixes: no exponential/cubic regexes (`_NOT_COPY` border branch, templ `_CONTROL`, `_VALUE_TOKEN` and 11 more; `tests/scan/test_regex_budget.py` guards every pattern); `Close`/`Delete`/`Copy`/`OK` labels are no longer dropped as DOM-event or enum tokens (case is compared); C# `@"…"` verbatim strings parse (index was one past the quote); line numbers count only `\n`/`\r\n`/`\r` (no `splitlines` drift on form feeds or U+2028); Razor control-block bodies are scanned, code blocks and statements stay blank, linear time |
| v55 | M2 rest: one per-file routine for `scan` and `agent-hardcoded` (same `t_functions`, relative paths, directives on every file, duplicate `(line, text)` dropped, delegates inherit `[scan]` settings, per-scan caches reset); scan-cache key covers side files (`go.mod`, `package.json`, `.strings`/`.xcstrings`, `project.pbxproj`, `Info.plist`); innermost UI sink before a literal; Mustache `{{name}}` at end of line is a slot; short Svelte/Vue expressions lose their braces; PHP code is not read as HTML; char literals (`'"'`) open no string in Go/C#/Rust; embedded-markup hits get their own line in triple-quoted strings; Markdown content dirs judged below the root; coverage counts only scanned files; log calls ignore parentheses in strings; JS call stack pops only a matching bracket; a full `UI_CALLS` callee beats a non-UI last segment; multi-line MDX `export`; L26–L31 (locale-table keys, `promptText`, apostrophes in `textContent`/`createTextNode`/dialogs, `el()` third-arg concat, `.HTML`) |
| v56 | M4 speed, identical hits on all 146 dev projects: relative paths by string prefix instead of `Path.relative_to`, `path_is_skipped` memoised per walk, lexers and the JS tokenizer jump to the next character that can start a token, one `ast.parse` per Python module, cached `is_prose`, no `resolve()` per file; about a third less scan CPU |
| v57 | Plain-text templates drop `key: {{ value }}` lines with a lowercase key (a machine-readable record such as patchman's `report.txt`); `Reported by: {{ name }}` is still reported |
| v70 | JS: a lowercase severity word (`err`, `info`, `warn`, `success` …) passed as the second or later argument of a toast or notify call is not copy (`showToast(msg, 'err')`). Found on tqdaemon, where about 25 hits were this. No held-out measurement was made for this change, so no precision or recall figure is claimed for it |
| v69 | Python desktop projects: a formatted message (an f-string that starts with a capitalised word and holds a placeholder, such as `f"Error: {exc}"` or `f"Chapters ({n})"`) is screen text unless it is a log or print argument, a URL, a query or a path. Written from the pool H to L Python misses, so those pools are development data |
| v68 | Python: strings inside `re.compile`/`re.sub`/`re.search`... calls and in tuples that pair a pattern with its replacement are developer text, whatever script they are written in; a dict keyed by language codes (`{"en": {...}, "fa": {...}}`) is the project's own catalogue, read through its own lookup. Java: a project's output-pane helpers (`appendProgress("...")`, `appendOutput`, `appendConsole`) and `showAlert`/`showDialog`/`showConfirm`-style helpers (first argument). Written from pool L misses, so pool L is development data from here on (pool M will be the fresh check) |
| v67 | Captions passed to Jinja macros (`{{ web_button("id", "Login", placeholder="Password") }}`: a capitalised string argument, not ids, paths or `url_for`/`include`); Java `return "Top Right";` inside a display-name method (`toString`, `getName`, `getLabel`...); Slicer-style Python Qt modules (`import qt`, `slicer`, `ctk`) count as GUI modules. Not done on purpose: messages of project-defined exceptions outside GUI projects (they are developer text there) |
| v66 | Python: sentences held in `msg`/`message`/`detail`-style variables, `return True, "message"`, `*_tooltip=`/`*_label=` keywords, `options=[...]` lists, and in GUI modules caption variables (`desc`, `tooltip`) and caption attributes (`page.title = ...`, `control.value = ...`), `content=` on widgets. Benchmark metric 4: a bare `…` in a hit counts as a slot, so JS and TS template literals match their `{x}` labels (a measurement fix: the scanner already reported them) |
| v65 | Misses of fresh pool K: Flet widgets (`ft.Text`, `ft.ElevatedButton`), and `label=`/`tooltip=`/`placeholder=`/`hint_text=` keyword text on any call in a Python GUI project (`SettingField(label="Port", ...)`; `ArgumentParser` and `Field` descriptions stay out); JSON files that define screens or forms (at least five `label`, `heading`, `placeholder`, widget `name` or `options` captions; translation catalogues in `locales/` folders stay out); `mkdocs.yml` site name, description and navigation labels |
| v64 | Python desktop GUI projects (a dependency or import of Tk, Qt, wx, Kivy or Toga): `set_status`/`update_status`/`show_error`-style helpers, errors raised with a project-defined class and a sentence, and code-to-label tables (`{"dol": "App"}`); Qt dialog statics (`QInputDialog.getText`, `QFileDialog.getSaveFileName`) and `addRow`; Java enum constants with display names, widget-factory helpers (`getDirectorySelectWidget(...)`) and progress-monitor task names. Repository documentation (root `README`, `CODE_OF_CONDUCT` and the like) stays unscanned: the rubric labels it `dev` |
| v63 | A string on the line after an opening `Text(` (or any UI sink call split over lines) is judged with that sink; AppStream `*.metainfo.xml` and `*.appdata.xml` store text (`summary`, `name`, `p`, `li`, `caption`) is scanned |
| v62 | Misses of the fresh pool J: Qt `QCoreApplication.translate(ctx, text)` (pyuic output), `QMessageBox.warning(self, title, text)` and Tk `messagebox.showerror`, `show_success`-style helpers; Java `updateStatus`/`showStatus`/`showErrorDialog`/`sendError`, file-chooser filters and titled borders; plain `.txt` text resources in `text/`, `texts/`, `strings/`, `messages/`, `help/` and `tooltips/` folders. Development check on pools J, I and H: recall 0.47 to 0.61, 0.68 to 0.71 and 0.68 to 0.69; precision 0.84 to 0.80, 0.80 to 0.81 and 0.82 to 0.82 (pool J is now development data) |
| v61 | Phoenix templates (`.heex`, `.leex`, `.eex`) are scanned: EEx tags like ERB and `{expr}` interpolation; before this the visible text of Elixir web projects was not scanned at all |
| v60 | Java UI (Swing, JavaFX, Vaadin): any widget class named for what it shows (`new ModernButton("Create")`) and the placeholder, header and helper-text setters are sinks; development check on pool I: Java recall 0.10 to 0.23 (nanoleaf), 0.40 to 0.43 (spring-ai) |
| v59 | ERB promoted to the supported tier (tier review over pools A-I: 5 held-out projects at the bar, 2 below); no scanner behaviour change |
| v58 | Python desktop GUIs (Tk, Qt, wx, Kivy, Toga): widget captions, menu entries, window titles, tooltips and list items are medium-confidence copy, only in modules that import a GUI toolkit; Dart text constants (`static const String agenda_text = "…"`); one file's scanner error is recorded under `skipped` instead of aborting the scan |
| v47 | Set-B fixes: Go CLI terminal output (`fmt.Print*`, coloured text, the project's output helpers) in CLI projects, with format-only strings dropped and doc generators / `hack/` skipped (B23); C# `[Description]` enum labels, `ValidationResult` messages and status/progress event args (B24); QML date-format arguments; `thirdparty/` skipped (B26) |
| v46 | Set-A fixes: project translate helpers in QML (`I18n.t("k", "Fallback")`) are routed (B17); Qt/QML Python backends report their status text (B18); `strings.dart`-style files hold copy (B19); WidgetKit `.configurationDisplayName`/`.description`, and SwiftUI keys count as routed only when the file's Xcode target ships `Localizable` (B20) |
| v45 | Astro components (TS frontmatter + JSX body) and MDX pages (Markdown + JSX blocks) are scanned; SVG path data and comma-separated keyword lists are not copy (B2) |
| v44 | Set-C fixes: skip `migrations/` (B12); Godot `editor_*` keys are not text (B13); plain-text and Markdown templates (`.text.erb`, `.md.erb`) read as content (B14); Python `ValidationError`, admin action descriptions, management-command help (B15) |
| v43 | SwiftUI `LocalizedStringKey` literals whose key the project catalogue translates are routed (B6, ADR-150) |
| v42 | Markdown under `resources/` and `templates/` is content; opt-in `[scan] content_globs` (YAML text keys, OpenAPI `summary`) (B7) |
| v41 | Escaped non-Latin text in minified JS bundles; CSS selector lists are not copy (B8) |
| v40 | QML text-binding expressions (ternaries, concatenation, `return` blocks, all-caps labels); Godot exported text properties (B4, B5) |
| v39 | HAML/Slim views, ERB `<%= %>` code through the Ruby pass, Rails view-helper sinks; Go CLI help and errors in CLI projects (B1, B3) |
| v10–v38 | Cumulative, newest first: chat-bot messages and command help (send, Embed, add_field, docstrings), UI-helper calls (toast, dialog), Ruby description heredocs and errors.add, Go fmt.Errorf and errors.New; content and manifest files (Markdown pages, TOML menus, VS Code and web manifests, Info.plist); bare literals in Cyrillic, Arabic, Hebrew, Greek, Thai and Devanagari are medium; Go struct tags (help, group, placeholder), Python UI keyword arguments (verbose_name, help_text, describe); property-line UI definitions (QML, Kivy .kv, Godot .tscn/.tres) and JavaFX FXML; short capitalised labels and abbreviations at UI sinks and in text elements (Ad, PM, IPv4), simple {name} holes inside JS messages; real-string survey fixes: inline-markup messages, lone lower-case words after UI calls and in text elements, slash-joined labels, capped template spans; human-language robustness: Unicode label words (Błąd, Uložit, İptal, Lưu), combining marks, one-ideograph labels, NFC, Greek question mark, any-space prose, template expressions in .html text; animation labels and named previews, sample-data dirs, lowercase keyword constants, .expect/panic messages, Rust lifetimes and clap doc comments, notification and C# message sinks, Swift named arguments; Rust test modules and ratatui/error sinks, Dart widget fields, C# initializer sinks, XAML value elements, regex fragments, HTML pages inside string literals (Go raw strings); dev-only code filtered for literal languages (previews, annotations, wrapped log calls, identifier constants, enum raw values, comment: args, test source sets), interpolation-aware Swift/Kotlin strings, escaped newlines, richer Swift sinks; server-side template engines (erb, ejs, jsp, hbs, twig, jinja, njk, liquid, gohtml, razor, ftl, blade) via scan/templates.py; UI sinks per ecosystem (scan/ecosystems.py) lift literal-language text to medium/high; literal languages: English-as-key routed calls (gettext, NSLocalizedString, tr, __, Localizer[]), log statements, SQL, text blocks, PHP heredoc; Go templ components (scan/templ.py); skip the project's own locale catalogue files (lang/en/*.js, locales/es.js, ...); Pug pipe text in Vue templates, python return (False, "msg") tuples; python server sinks (HTTPException, flash, config defaults), log/raise silenced, one-word aria-label/title, text after inline elements, sr-only; routed i18n.__ and friends, analytics sinks, key codes, shortcuts, markup comments; Vue/Svelte single-file components split into markup + script (scan/sfc.py); + snake_case and lowercase phrases in label tags, wrapped prose with "; " (B4 iter 2) |

## Source text in different human languages

The text in the code is not always English. The scanner treats every Unicode letter as a letter and checks each writing system's
peculiarities in `tests/scan/matrix/human_spec.py`: 34 language variants in 8 groups, each as a one-word label, an action, a
sentence, a question and a greeting, in 17 code hosts (HTML, JS, TSX, Vue, Python, Kotlin, Swift, Java, C#, Dart, Go, PHP, Ruby, Rust,
XAML, ERB). Every phrase must be found as reliably as the English one, and developer-only text (comments, log calls) in the same
languages must stay silent.

| Group | Languages in the matrix | What is peculiar |
|---|---|---|
| Latin, ASCII | English, Dutch, Swedish | capitalised words, spaces, ASCII punctuation |
| Latin with diacritics | Spanish, French, German, Polish, Czech, Turkish, Vietnamese | accented capitals (Ł, Ś, İ, Ü), inverted `¿ ¡`, French spaced marks, noun capitals; a one-word label such as "Błąd" or "Uložit" must count |
| Cyrillic, Greek, Armenian, Georgian | Russian, Ukrainian, Greek, Armenian, Georgian | Greek question mark is `;`, Armenian full stop `։`, Georgian has no case |
| Right-to-left | Arabic, Persian, Urdu, Hebrew | no case, `؟ ،`, optional diacritics, zero-width joiners |
| Indic | Hindi, Bengali, Tamil | combining vowel signs are part of the word, `।` as full stop |
| CJK | Chinese (both), Japanese, Korean | no spaces, full-width punctuation, one-character labels (`删`, `예`), suffixes after an interpolation |
| Southeast Asian, unsegmented | Thai, Lao, Khmer, Burmese | no spaces between words, combining marks, little sentence punctuation |
| Ethiopic | Amharic | own full stop `።` |

**Real strings.** Besides the synthetic matrix, `experiments/language_survey/` feeds about 370,000 real translated UI strings
(147 languages, taken from eight localized apps) through six hosts by shape (one word, short, sentence, question, inline markup) and
counts what the scanner reports at medium or high confidence. The strings are split into a tuning half and a hold-out half by a hash of
the text; fixes look only at the tuning half. At scanner v33 the miss counts fell from 244 to 134 (tuning) and from 288 to 178
(hold-out) per sample of 20 strings per shape, with the same relative gain on both halves. What is left is mostly two-letter
abbreviations and English leftovers inside non-English catalogues. Writing-system findings are in
`experiments/language_survey/GUIDE.md`; per-language and per-ecosystem advice is in `llm-localizator help human|agent --lang CODE` and
`--code TOPIC` (ADR-139).

Also checked: a native sentence with an interpolation next to it, a Latin token inside native text (`保存更改 Wi-Fi`), native digits, decomposed
(NFD) Unicode, and a lone ideograph. Not yet checked: vertical text, bidirectional marks inside identifiers, languages written in more
than one script in one string beyond Japanese, and source text of real apps in most of these languages.

## Usage artefacts

`scan` writes `<out_dir>/<namespace>.json`:

```json
{
  "signIn": [
    { "file": "apps/web/features/auth/LoginForm.tsx", "line": 42, "component": "LoginForm" }
  ]
}
```

The translation pipeline reads these back and puts the first call site into the
prompt as context.

## Adding a scanner

A new programming language is not a new scanner. Ordinary source files are a
row in `llm_localizator/core/languages.py`. The checklist is
[adding-a-parser.md](adding-a-parser.md). A new file under `llm_localizator/scan/`
is only for a framework call-site parser (`t()`, `i18n.t()`).

One module per source framework, not per human language. Checklist:

1. New file under `llm_localizator/scan/` implementing `Scanner`, with a
   `routing_note` that tells an agent how to call `t()`.
2. Register the name in `llm_localizator/scan/__init__.py`.
3. One fixture in `tests/scan/`. No network, no subprocess, no model.
4. Point `[scan] adapter` at the name. The web adapter dropdown lists
   registered names; there is no new tab per language.

```python
# llm_localizator/scan/__init__.py
_SCANNERS = {"next-intl": NextIntlScanner, "vue-i18n": VueI18nScanner}
```

```toml
[scan]
adapter = "vue-i18n"
src_dirs = ["src"]
```

## Adding a preview renderer

Preview is a view of stored text, not a second copy. Checklist, same shape:

1. New file under `llm_localizator/render/` with `preview(text, locale) -> safe HTML`.
2. Register the name in `llm_localizator/render/__init__.py`.
3. One fixture. No network, no subprocess, no Pandoc, no browser.

Shipped: `icu`, `markdown`, `html`. A later format does not change the key
table, export, or translate.

## Unused keys (V41)

`llm-localizator validate --unused` runs the configured scanner and reports source keys that no code
references. A key like `item_one` counts as used when `item` is. Keys built at run time
(`t(`status.${x}`)`) cannot be seen; list them in `[scan] unused_allow`. It is a warning, and
`--strict` turns it into a failure for CI. Without `[scan] adapter` and `src_dirs` it prints a note
and skips the check.

## Control comments (ADR-106)

Code can steer the hardcoded-string scan in its own comments: `l10n-ignore` (same line), `l10n-ignore-next-line`, `l10n-ignore-start`/`l10n-ignore-end`, `l10n-ignore-file` (first 10 lines), and attributes `key=`, `note=`, `max-length=`, `dnt`, `namespace=`. `l10n: user-facing` on a line (or the line above) force-includes the first string literal on the next line as a high-confidence hit when the heuristics rejected it. The engine only reads these comments; it never writes source.
