# The web interface

```bash
llm-localizator web            # app http://127.0.0.1:8770 · marketing http://127.0.0.1:8760
llm-localizator web my-app --port 9000 --no-browser
llm-localizator web --no-marketing   # app port only
```

The CLI answers *"is anything wrong?"* well. It answers *"what does this
actually say, and is that right?"* badly — you cannot read a catalogue in a
terminal, and a validation finding is far more useful sitting next to the string
it is about.

`llm-localizator web` binds two loopback servers (ADR-45): the **review app** on
`:8770` and a read-only **marketing** site on `:8760`. Marketing serves `/`,
`/how-it-works`, `/roadmap`, and `/api-docs` (plus `/static/*`); it has no
catalogue APIs and accepts no POST. On the app port, `/` redirects to the
dashboard; the editor is `/app/editor`. `/app/tm` is the translation memory page. `/app/glossary` edits the glossary files the next prompt loads, one domain file at a time. `/app/operations`, `/app/settings`, `/app/analysis`, `/app/stats/usage`, and `/app/stats/progress` are the operator pages. `/app/review` is the review-ticket queue. `/app/project-config` edits prompts, bridge language, glossary sharing and identity ([project-config.md](project-config.md)). `/app/model-eval` lists bakeoff reports. `/login`, `/register`, `/pending`, `/setup`, `/app/admin/users`, and `/app/admin/activity` are the local-account pages (ADR-39, ADR-46). `/app/workflow` edits per-project workflows as block scripts (ADR-63; which workflow applies to a locale: its `locales` scope, else the one named `default`) and has a "?" help modal; `/app/branches` tracks per-git-branch state dirs. Old app-port bookmarks `/landing` (and siblings) 302 to the marketing port. Sidebar chrome is itself localised (`llm_ui_locale`, en/de/pl/fr/ar; Arabic sets `dir=rtl`).

**Help ("?"):** the Operations page also shows a "?" next to the command title with per-command help (keys `operations:<command>`, `run-*` fall back to the base command). every content page has a detailed help modal (`llm_localizator/web/static/help.js`, keys `page:topic`); the modal is wide, bounded and scrolls, and Escape closes it. Pages with several panels have per-section keys (settings cards, setup steps, glossary CSV and dialog, review ticket and new-ticket dialog, project-config tabs, analysis, TM and usage panels). Login, register and pending have none. `tests/test_help_coverage.py` checks that every mounted key is defined, every defined key is mounted, each body is at least 450 characters and each content page loads `help.js`. Add the entry and its mount together.


## Project switcher

Every project registered in `~/.llm_localize/projects.yaml` loads at startup.
A dropdown in the header lets you switch between them with no restart. The URL
does not change; the switcher controls a `?project=` parameter appended to
all API requests.

## Coverage cards

One card per target locale: percentage translated, done / stale / missing
counts. Click a card to set that locale as the primary (editable) column in
the table.

## Namespace selector

A second dropdown selects the namespace. Choose **(all namespaces)** to see
every key in the project in one table (each row carries its `namespace` field
so the save path is unambiguous).

## Compare columns

The **Compare with** bar lets you add one or more locales as read-only columns
next to the primary column. Click a locale pill to add it; click again to
remove. Compare columns show the translation value and a status badge but are
not editable. Useful for checking whether a Polish string diverged from its
German equivalent, or whether a pivot locale stays close to its reference.

## Filters

**Status filter** — restrict the table to rows in a particular state:

| Filter | What it shows |
|---|---|
| all statuses | everything |
| missing | key absent from the target file, or state record absent |
| stale | source has changed since the key was last translated |
| untranslated | value is present but identical to the source string |
| machine | translated by LLM, not reviewed |
| reviewed | translated by LLM and review-validated |
| human | hand-edited in the web UI or marked human by another tool |
| needs better model | model rejected or flagged the key for a larger model |
| **has problems** | any key that has at least one validation finding |
| **low score** | quality score below `[quality] threshold` (default 0.55) |
| **unscored** | present keys (including stale) with no quality score yet |

**Text search** — matches the key, the source string, and the primary
translation.

## The table

| Column | |
|---|---|
| key | dotted key (and namespace prefix in all-namespaces view) |
| source | English source string; context note and `maxChars` budget below |
| *locale* ✎ | editable primary translation |
| *(compare)* | read-only column for each added compare locale |
| **score** | quality score from back-translation / heuristics (sortable; click for worst-first) |
| status | badge for the primary locale |

Scores come from the project's `.llm-scores` (or `[state] scores`) sidecar —
filled by translate, improve, rescore, and human saves. Unscored cells show `—`.
Click the **score** column header to sort (ascending = lowest / worst first).

Validation findings — `V02: missing placeholders ['name']`, etc. — appear
inline below the string they concern.

## Inline editing

Click a translation, type, and blur (or press Ctrl+Enter / Ctrl+S) to save.
Escape reverts the field. Enter in the search box searches; it does not save.
Translation textareas use `dir=auto` for RTL locales. Press `?` for the CAT
shortcut help (blocked while open for other shortcuts except toggling help).
The history tab shows a local Levenshtein distance from the machine version
to the current value; it is not written to `.llm-scores`.

A hand edit passes the same `validate_translation` rules as the model: a
string that drops a placeholder or breaks an ICU structure is refused with the
reason. The edit stays on screen, marked dirty, so it can be corrected.

Placeholders (`{name}`, ICU blocks, `%s` / `%1$d`, `{{name}}`, HTML tags,
`$t(key)` and `:name`) are drawn as coloured chips in the source text, the
source-change diff and translation-memory matches. When the target contains
any, a read-only highlighted copy appears under the textarea. Click a chip to
copy it. The tokeniser (`static/placeholders.js`) is display-only; validation
still happens server-side.

A saved edit is stamped `status: human`, `provider: human`, `model: human`, and
its source hash is refreshed — a stale key stops being stale after a human touch.
Agent / Cursor edits should call save with `"provider": "agent"` (and optional
`model` / `verified_by`) so they stay distinguishable from local Ollama rows
(ADR-19). Filters include `provider_local`, `provider_cloud`, `provider_agent`,
`provider_human`, and `provider_import`.

## Adding a locale

Click **+ Locale** in the header to open the add-locale modal. Enter a locale
code (e.g. `de`, `ja`, `pt-BR`) and optionally a model name, then click
**Add & queue**. This patches `targets = [...]` in the project's TOML and
reloads state. Run `llm-localizator translate` (or queue it via taskqueue) to
fill the new locale.

## Getting started: the dashboard card and the setup wizard

New projects show a **Getting started** card at the top of the dashboard: the
same checklist as `llm-localizator guide` (prepare your machine, create the project,
choose languages, pick and test a model, translate, review). The next step is
highlighted with a button (**Choose languages**, **Pick a model**,
**Run translation**, **Open the editor**) and the equivalent terminal command.
When every required step is done the card disappears. It reads `POST /api/ops/guide`
(read-only; it never calls a model).

**Choose languages** and **Pick a model** open `/setup`, a five-step wizard (Admin only):

1. **Your project** shows what was found (format, keys) and the source language.
2. **Languages**: search the languages the tool knows (`GET /api/locales`), tick
   as many as you like, or add any other code by hand.
3. **Model**: choose from the models installed in Ollama, or type one for another
   provider, then **Test it** to send one short string to it. A paid provider asks first.
4. **About your product**: one sentence that goes into every prompt.
5. **Save** writes `.llm-localize.toml`, then offers **Run first translation**
   (in this process, not through the queue), **Open the editor**, or the dashboard.

Adding a locale later still works from the header (**+ Locale**), below.

## UI language

A language selector sits in the sidebar footer (`#lang-sel-mount`) and stays
visible on SPA navigations and the auth shell. Dictionaries live in
`llm_localizator/web/locales/` (en, de, pl, fr, ar). Canonical URLs are
`/{lang}/app/...` (ADR-108); bare `/app/...` 302s using the `llm_ui_locale`
cookie (JS also keeps `localStorage`). A path prefix wins over storage.
`/api`, `/static`, and `/locales` stay unprefixed. Arabic sets
`document.documentElement.dir` to `rtl`; other UI locales restore `ltr`.
Chrome strings use `data-i18n` / `uiLocale.t()`. The sidebar foot is one
icon row (language, font, theme, profiler): each opens a small popover.
Font (`current` / `bigger` / `biggest`) and theme (`light` / `dark`) persist
in `localStorage.llm_ui_font` / `llm_ui_theme` and apply site-wide via
`html[data-font]` (rem scale from a 13px root) and `html[data-theme]`
(design tokens including `--color-panel`).

## Request profiling

Opt in with `?profile=1`, JSON `"profile": true`, env `LLM_LOCALIZE_WEB_PROFILE=1`,
or `[web] profile = true`, or the sidebar profiler icon. Responses gain
`Server-Timing` and JSON `_timing` (`spans`, `totalMs`, `responseBytes`).
The Profile panel (`localStorage.llmProfile`) shows a ring buffer of
`/api/*` timings sorted by client duration (slowest first), with Export
downloading JSON (`window.LLMProfile.downloadExport()` /
`window.__LLM_REQUESTS`).

## Deliberate limits

**Local only.** Binds `127.0.0.1`, never `0.0.0.0`. A POST needs the
startup token printed at startup (`X-LLM-Token`), or an approved browser
session (`llm_session` cookie / `X-LLM-Session`). Cross-origin save and flag
stay off unless `[web] overlay_edit = true`. QA marker locales (`en-XX` /
`en-XA`) appear in the language picker and `/en-XX/app…` routes only when
`[web] qa_locales` lists them (ADR-110; default empty = production off). See
[agents.md](agents.md) § Introducing `en-XX`. The startup token is not
`LLM_LOCALIZE_CONTENT_TOKEN`. Operator accounts live in `{state}/users.json`
(ADR-39); the first registrant is Admin, later ones stay pending until an
Admin assigns a role. Role denials from `ops/` match on CLI and
`POST /api/ops/<command>` (exit code 77). Translator locale chips restrict
save and message reads. A localhost POST with a valid startup token and no
user session still runs as Admin. `POST /api/push-strings` may update source
(Admin/Developer) but does not translate (ADR-40). Optional
`[notify] webhook` posts a summary after a *mutating* op (read-only ops such as
`status` and `validate` send nothing and write no JSON log line); delivery runs
on a background thread and a failure does not fail the op. The body is an envelope
`{event, project, ts, data}` (the older flat fields stay at the top level too); events include
`translate.done`, `review.pending`, `source.changed` and `review-escalation`. `[notify] format = "slack"`
sends `{"text": ...}` instead, unsigned.

**Authorization table.** Every POST route is listed once in
`web/post_policy.py` (`POST_POLICY`); a test fails when a route is missing.
Policies: `admin` (settings, project-config, web-token, add/remove-locale,
translate-enabled, reload, model-eval; `/api/setup*` are inline Admin checks),
`edit` (catalogue writes: save, flag, verify, revert, validate-key, context,
screenshot-upload, mark-example, mark-intentional, lock, retranslate, import,
glossary, tm/import, push-strings, workflow, branches, review tickets,
save-ui-locale, `/api/ops/*`) and `read` (export, preview, resolve: no write
role, same locale scope). `edit` and `read` need an approved actor and every
locale named in the body (`locale` and every entry of `locales`) must pass the
locale chips. `retranslate`, `import`, `push-strings`, `workflow` and `export`
also check the ADR-39 role matrix. A session user always wins over the startup
token, so a Translator who sends the token is still a Translator. Locale-scoped
reads (`export`, `bundle`, `tm/*`, `analysis`, `review/tickets`,
`translator-bundle`, `translator-lookup`, `history`, `findings`) return 403 for a
signed-in user outside their locales; an unauthenticated GET is not scoped (the
public bundle relies on it). `dispatch_op` with no `actor_role` is denied; trusted
in-process callers pass `ROLE_ADMIN`. Review comments and tickets are authored by
the signed-in username, never by the request body. Invalid locale or namespace in
a write is HTTP 400.

**No build step.** Stdlib `http.server` plus one inlined HTML string. The page
itself loads offline. Ops → status on a remote collection is the exception: that
command calls the content API from this machine.

**Port 8770** (app) and **8760** (marketing), clear of taskqueue's 8765 / 8766,
so all three can run simultaneously.

## Operations drawer

Click **⚙ Ops** in the header to open the operations panel. It exposes the
same commands as the CLI (validate, ingest-visual, status, adopt,
agent-backlog, agent-hardcoded, explain-scan, hardcoded-hunt, discover, sync, translate,
improve, review, estimate-cost, rescore, import, export) via
`POST /api/ops/<command>`. Each form supports dry-run where the CLI does.
Validate’s **Layout** checkbox maps to `--check-layout` (V28). Ingest-visual
loads consumer findings JSONL into `.llm-review` — see
[visual-findings.md](visual-findings.md).

**Adopt** stamps catalogue values that lack state (ADR-19 agent provenance)
without rewriting message JSON. **Agent-backlog** returns a paste-ready prompt
(or JSON) of keys still `missing` / `empty` / `no_state` / `stale`.
**Agent-hardcoded** returns a paste-ready prompt of product strings that never
call `t()`; use CLI `agent-hardcoded --status` (or guide) for scan/en-XX
readiness and `next[]` hints. **Hardcoded-hunt** (dogfood) runs pseudo en-XX +
crawl/intersect + static refresh — long browser work; prefer CLI over a casual
Ops “Run now”. Model off on agent-hardcoded: **Run** prints the markdown and
writes nothing. **Ask local model** is off by default; with taskqueue up, that
pass submits instead of running inline. **Discover** lists proposed collections
and writes nothing.

The agent-hardcoded findings panel lets an Admin or Developer decide (ADR-55): **Accept** or
**Ignore** per hit, the same for every hit shown at the current confidence, **Undo**, and
**Show ignored**. A note under the filter says what accepting does in this project's
`[apply] mode`. Decisions persist across rescans. The dashboard has a **Hardcoded strings**
card with the pending, accepted, applied and ignored counts.

The header collection switcher lists `messages`, configured file trees such as `legal`, locale directories found on disk (a `content/help` tree shows up as `help` without a toml edit), and a remote collection declared as `kind = "remote"`. A file collection is a file list: path, coverage, stale. Open a file to see its `##` sections (same split as `documents`); each section has source, a tall translation field, markdown preview, history, and comments. Identity is `doc:<collection>/<path>` + section index (ADR-109). Save rewrites the joined file. A remote collection has no files; Ops → status reports each unit's source language. See [content-api.md](content-api.md).

Every Operations tab except ingest-visual, agent-hardcoded, and discover has the same collection control. Status, export, and translate apply to a file collection. Status and translate also apply to a remote collection; export does not. The other commands stay on the message catalogue and say so if a file collection is selected.

Message and document editors share a **Preview** panel. ICU strings list
detected placeholders (e.g. `mean`, `count`) as sample fields; `POST /api/preview`
returns filled HTML via `render_message` (optional `mode=samples` for all plural
arms). Markdown and HTML use the same endpoint. Preview never rewrites stored text.

After Ops → adopt / import / migrate-state, overview cards refresh from disk automatically.
If you ran `llm-localizator adopt` from the CLI while the UI was open, click **↺**
in the header (or `POST /api/reload`) so sidecars re-read `.state`.

When `tq` is on PATH (`taskqueueAvailable` on `/api/overview`), translate /
improve / review / rescore **always submit** for non-dry-run work — the UI hides
**Run locally** and shows **Submit to taskqueue**. Translate enqueues **one job
per selected locale** (`localize_ui_messages__vi`, …). Dry-run stays local. If
`tq` is missing, **Run locally** is available with an explicit hint.

Table filters, project, locale, compare selection, namespace, page size, sort,
and the last Operations tab are restored from `localStorage` on reload.

The quick **Translate** popover (▶) always submits **only the current table
locale** (it resets the Operations locale picker before enqueueing).

## Translator mode (in-page overlay)

Toggle **Translator mode** in the header (or use the floating chip after the
overlay loads). State persists in `localStorage` (`llm_translator_mode`). While
active:

| Action | Effect |
|---|---|
| Hold **CTRL** | English source tip follows the cursor on the string under it |
| **CTRL + click** | Edit modal for that string (validate + save on project keys) |

Release CTRL to resume normal page interaction.

Cross-origin **save** and **flag** (a consumer page that loaded the overlay)
stay off unless `[web] overlay_edit = true`. Inspect still works from
localhost. The review page is same-origin and can save. Every POST sends
`X-LLM-Token`; `llm-localizator web` prints the token and writes it to
`{state}/web.token`.

### Inspect mode (CTRL held)

While CTRL is held the page is in **inspect-only** mode:

- Crosshair cursor over catalogue/UI text
- Text selection disabled (`user-select: none`)
- Clicks, sorting, scroll, and focus into inputs blocked via capture-phase handlers
- Floating chip and edit modal remain interactive

Tips appear on mousemove (and immediately when CTRL is pressed if the pointer
is already over bindable text). Edit opens on **mouseup** with CTRL still held
(not on mousedown — that avoids suppressing the click sequence).

### How strings are resolved (priority order)

The overlay walks the DOM stack under the cursor (`elementsFromPoint`) and
resolves in this order:

| Layer | Mechanism | Notes |
|-------|-----------|-------|
| 1 | `[data-llm-ns]` + `[data-llm-key]` | Primary bind — unambiguous, enables edit |
| 2 | `[data-i18n-key="ns.key"]` | Common convention |
| 3 | `[data-i18n="flatKey"]` | Web-UI flat keys → `__web_ui__` namespace |
| 4 | Table row context | Untagged cell in a row → bind from sibling textarea / tagged cell |
| 5 | Client `byTargetText` | Exact match on visible translated text from bundle |
| 6 | `POST /api/resolve` | Debounced (~150 ms) fuzzy fallback when client map misses |

When layer 5 finds **multiple** catalogue keys with the same translation, the tip
lists candidates — **CTRL+click does not open the edit modal** until the bind is
unique (hover a tagged element or disambiguate manually in the table).

Layer 6 is read-only hinting for legacy/untagged consumer DOM; edit still needs
an explicit tag (layers 1–3).

### Review UI coverage (`:8770`)

These surfaces are tagged at render time in `llm_localizator/web/assets.py`:

| Surface | Bind |
|---------|------|
| Table key / source / compare columns | Project `data-llm-ns` + `data-llm-key` per row |
| Translation textarea | Same row bind |
| Table headers, filter `<option>`s, pagination prev/next | Web-UI `data-i18n` → `__web_ui__` |
| Modal / translate popover labels | Tagged in `applyStaticI18n()` |

After a save, the page hot-reloads affected strings without a full refresh.

### Web-UI strings vs project catalogue

| Target | Namespace | Save endpoint | Notes |
|--------|-----------|---------------|-------|
| Chrome strings (filters, headers, …) | `__web_ui__` | `POST /api/save-ui-locale` | Switch UI language away from English before editing |
| Project message keys | configured namespace | `POST /api/save` | Runs `validate-key` before save; updates table via `onCatalogSaved` |

The review UI registers `window.__LLM_TRANSLATOR__` so overlay saves call
`applyTranslation` / `load()` for web-UI strings and `load()` for catalogue rows.

### Consumer apps

Load the overlay via script tag (CORS enabled for local dev origins):

```html
<script src="http://127.0.0.1:8770/overlay.js"
        data-project="my-app"
        data-locale="pl"></script>
```

Register in the host app for hot reload after overlay saves:

```javascript
window.__LLM_TRANSLATOR__ = {
  applyTranslation({ namespace, key, value }) { /* update DOM / i18n store */ },
  locale: () => currentUiLocale,
  catalogLocale: () => currentCatalogLocale,
  project: () => "my-app",
  onCatalogSaved() { /* optional: refresh catalogue view */ },
};
```

For zero-ambiguity tips and CTRL+edit, stamp DOM at render time:

```html
<span data-llm-ns="app" data-llm-key="greet">…</span>
<!-- or data-i18n-key style: -->
<span data-i18n-key="app.greet">…</span>
```

Untagged translated text can still resolve via layers 5–6 when the match is unique.
Auto-stamping from next-intl / React context remains a planned follow-up.

### Bundle loading

On enable, the overlay fetches one or both bundles (deduplicated — concurrent
loads share a single in-flight request):

- `GET /api/translator-bundle?mode=web-ui&locale=` — web UI strings
- `GET /api/translator-bundle?project=&locale=` — project catalogue

Each response includes `entries[]` and `byTargetText{}` (reverse map:
translation → keys). The server ignores client-aborted bundle responses
(no console tracebacks on Windows when the browser cancels duplicate fetches).

### Limitations

- Shadow DOM (closed) is not pierced — tags must live in light DOM.
- Source-locale pages have empty `byTargetText` — rely on explicit tags.
- Very long visible text (>500 chars under cursor) is skipped for reverse lookup.
- Closed shadow roots and duplicate translations require explicit tagging for edit.

## Export and import

Operations → export downloads a handoff. Choose which rows (the same status
filters as the table), the format (`csv`, `xliff`, `json`, or `xlsx`), how many
files to write, and — when that number is 1 — whether the download is one
file or a zip split per locale or per namespace. A count of 2 or more
divides the selected rows into that many files (a zip). Screenshots are
optional and force a zip. `json` is a handoff document
(`format: llm-localizator-handoff`), not a message catalogue.

The log lists each file, filled vs empty per locale, status mix, and the
first keys. Download report saves the full JSON (every key, source, target,
status, and score). A zip also contains `export-report.json`. The handoff
file itself stays a clean CSV, JSON, or XLIFF.

Operations → import reads one or more CSV, JSON, XLIFF, or ZIP files. Select
the locale the file is for. A CSV with no header row is accepted only when
exactly one locale is selected and the columns are still in export order
(the usual case when an external model drops the header). Commas inside a
translation that were left unquoted are rejoined. Keep the header when you can.

Import stamps `provider=import`, `status=human`, and the **localized by**
name as `model`. It does not mark rows verified and it does not keep the old
quality score on text that changed. The log shows what was written, what was
rejected, and the coverage change (`pl: 820/1518 translated → 901/1518`).
Download report saves the full JSON. A file that cannot be parsed, or an
import that writes nothing, stays as an error above the log; catalogues are
not updated for a structurally bad batch.

CLI equivalent:

```bash
llm-localizator export my-app --locales pl --only untranslated --format csv --out handoff.csv
llm-localizator export my-app --locales pl --files 4 --out handoff.zip --report export-report.json
llm-localizator export my-app --locales pl,de --layout per-locale --out handoff.zip
llm-localizator export my-app --locales pl --screenshots --out handoff.zip
llm-localizator import my-app handoff.csv --locales pl --localized-by deepseek --report report.json
```

`GET /api/export` still accepts `format`, `layout`, `only`, `files`, and
`screenshots` and returns the file bytes. `POST /api/export` returns JSON
`{ok, filename, content_type, file_base64, report, lines}` so the Operations
log can show the report. Prefer POST when the namespace list is long.

## API

The page is a thin client over these endpoints:

| Endpoint | |
|---|---|
| `GET /api/projects` | `{projects: [{name}], default}` — all loaded projects |
| `GET /api/overview?project=` | Combined lite + stats (backward compatible) |
| `GET /api/scan/status?project=` | Hardcoded-string scan cache: `cached`, `stale`, `counts`, `decisions` (pending, accepted, applied, ignored, orphaned), `ts` (Admin, Developer) |
| `GET /api/status?project=&group_by=screen` | Coverage grouped by screen (`data.screens`) |
| `GET /api/overview-lite?project=` | Fast: namespaces, `sourceTotal`, `scaleHints`, `taskqueueAvailable` — no coverage walk |
| `GET /api/overview-stats?project=` | Per-locale coverage cards (`locales` array) — loaded idle after lite. Also `budget` for the dashboard Cloud budget card: `capUsd`, `spentUsd`, `remainingUsd` (null without a ceiling), `projectedUsd` (null before day 3 or without spend), `mode`, `localOnly`, `cloudEnabled`, `byMonth` (last six ledger months). Local spend is always zero and is not listed |
| `GET /api/messages?...&detail=minimal\|full` | rows; default **`minimal`** (context/score signals loaded via `/api/messages/row` on focus) |
| `GET /api/messages/row?project=&locales=&namespace=&key=` | full detail for one key |
| `GET /api/findings?project=&locale=&namespace=&keys=&full=` | validation findings; `keys=ns:key,...` for page scope; `full=1` for filter “has problems” |
| `POST /api/save` | `{project, locale, namespace, key, value, provider?, model?, verified_by?}` → `{ok}` or `{ok: false, error}` |
| `POST /api/add-locale` | `{project, locale, model?}` → `{ok}` |
| `GET /api/ui-locales` | `{locales: ["en", "de", "pl", ...]}` — available UI translations |
| `POST /api/export` | JSON body `{locales, namespaces, format, layout, only, screenshots, file_count}` → `{ok, filename, content_type, file_base64, report, lines}` |
| `GET /api/export?project=&locales=&format=csv\|xliff\|json\|xlsx\|zip&files=` | file bytes (`zip` means CSV + screenshots; `files` is the file count) |
| `POST /api/import` | `{project, csv\|xliff\|json, locales, dry_run?, model?}` (or `{xlsx_base64, filename}` for a workbook) → import report |
| `POST /api/ops/import` | same, plus `files: [{name, text}\| {name, base64}]` |
| `GET /api/commands` | CLI command manifest (field names, types, defaults) |
| `POST /api/ops/<command>` | run a CLI-equivalent operation; body matches command flags |
| `POST /api/ops/<command>` + `stream: true` | SSE progress for rescore/review/improve/translate/documents |

| `POST /api/translate-enabled` | `{project, enabled}` → pause/resume translate |
| `GET /api/history?project=&locale=&namespace=&key=` | translation history for one key; each event may include `provider`, `trigger` (`tm-hit`, `translate`, …), `quality_score`, and optional `candidates: [{model, score, provider}]` from dual-model ensemble (ADR-21) |
| `POST /api/verify` | mark a key verified |
| `POST /api/revert` | restore a previous value from history (`prev`) |
| `POST /api/context` | save a context note for a key |
| `GET /overlay.js`, `GET /overlay.css` | Translator overlay static assets (also served with CORS for consumer injection) |
| `GET /api/translator-bundle?mode=web-ui&locale=` | Web UI strings: `{entries, byTargetText, sourceLocale}` |
| `GET /api/translator-bundle?project=&locale=` | Full project bundle (legacy; overlay uses lookup instead) |
| `GET /api/translator-lookup?project=&locale=&namespace=&key=` | Single-key `{source, target, note}` for overlay hover |
| `GET /api/translator-config?mode=web-ui` | Web-UI locale list |
| `GET /api/translator-config?project=` | Project source/target locales and namespaces |
| `POST /api/save-ui-locale` | `{locale, key, value}` → `llm_localizator/web/locales/{locale}.json` |
| `POST /api/validate-key` | `{project, locale, namespace, key, value, fullValue?}` — used by overlay edit modal |
| `POST /api/resolve` | `{project?, locale, mode, text}` → `{candidates: [{namespace, key, score}]}` — overlay debounced fallback |
| `POST /api/flag` | Append developer flag for improve (overlay modal **Flag** button) |
| `GET /api/glossary?project=` | Domain bundle the glossary page lists |
| `POST /api/glossary` | `{domain, action, kind, term, translations?, forbidden?, note?}` — writes one domain file |
| `POST /api/lock` | `{locale, namespace, key, locked}` — sets the optional state field; does not change the catalogue |
| `GET /api/settings?project=` | System settings payload: providers, locale assignments, quality, asap/frozen, coverage, project, web, permission matrix. Does not return the session token |
| `POST /api/settings` | `{frozen?, asap?, fallbacks?, overlay_edit?, permission_matrix?, reset_permissions?, quality?, providers?, locale_assignments?, project?, allow_model_writes?}` — round-trips the toml; Translator×translate stays false; model/judge writes need bakeoff Winner or `allow_model_writes`; a bad value leaves the file unchanged |
| `GET /api/provider-status?project=` | Probe named providers (Ollama `/api/tags`; cloud = env key present). Soft-cached 60s; stale-while-revalidate to 5 min so Settings does not wait on a slow Ollama host |
| `POST /api/remove-locale` | `{locale}` — drop from targets and related maps; catalogue files kept |
| `POST /api/push-strings` | `{namespace, strings:{key:source}}` — Admin/Developer; updates source only; does not translate (ADR-40) |
| `GET /api/bundle?project=&locale=&namespace=` | Catalogue JSON + `etag`; `If-None-Match` → 304 empty body. Loopback only; no new CORS |
| `GET /api/workflow?project=&name=` | Named workflows (`script`, `warnings`, `rules`, `maxImproveLoops`, `notify`, `locales`, `lastRun`, `run`, plus `options` and `assignments`) or one by name (ADR-63) |
| `POST /api/workflow` | `{workflows:{name:{script|rules|high+low, maxImproveLoops, notify, locales}}, notifyWebhook?}` — `script` is a nested block tree (`{type, field, op, value, then[], else[]}`); validated like the config loader; the canonical pipeline is written compactly as high/low |
| `POST /api/ops/workflow` | `{name?, route_only?, dry_run?, locales?}` — runs the script; `data.run` carries status and per-block `counts` (`-1` = whole scope). Under taskqueue LLM blocks park the run as `waiting` |
| `GET /api/workflow/run?id=&project=` | Run status (read-only) |
| `POST /api/workflow/resume` | `{id}` — advances a `waiting` run when its queue task has finished (idempotent, edit role) |
| `POST /api/workflow/cancel` | `{id}` — cancels a waiting run (edit role) |
| `GET /api/workflow/summary?project=` | Per locale: applying workflow, last run, active run; plus `names`, `overlaps`, `uncovered` (dashboard, operations card, editor chip) |
| `POST /api/workflow/copy` | `{name, toProject, newName?, overwrite?}` — merges one workflow into another project's `[workflows]`; locales the target lacks are dropped (`droppedLocales`); existing name refused unless `overwrite` (edit role) |
| `GET /api/branches` | Tracked branch list under `{state}/branches/` (lite: no `collect`/git archive; Sync and merge-preview fill detail) |
| `POST /api/branches/track` | `{name, base?, auto_translate?}` — create branch state/scores dirs; catalogues stay shared (ADR-61) |
| `POST /api/branches/active` | `{name}` — select branch overlay (`main` clears) |
| `GET /api/branches/sync` | Read-only `git status`/`diff`; `committed` is always false |
| `GET /api/branches/merge-preview?branch=` | Branch vs main state rows |
| `GET /api/branches/diff?branch=` | Downloadable source + state diff |
| `POST /api/branches/archive` / `unarchive` | `{name}` |
| `POST /api/branches/delete` | `{name, confirm:true}` — removes registry entry and state dir |
| `POST /api/branches/fetch` | `git fetch --all --prune` (network; only with a remote) |
| `POST /api/branches/merge` | `{branch, choices:[{locale,namespace,key,side}]}` — conflicts untouched until chosen |
| `GET /api/auth/me` | Current actor (token Admin or session user) |
| `POST /api/auth/register` | `{username, password}` — first user is Admin; later users pending |
| `POST /api/auth/login` | `{username, password}` → sets `llm_session` HttpOnly cookie |
| `POST /api/auth/logout` | Clears the session cookie |
| `POST /api/auth/users` | Admin: list users + invite path |
| `POST /api/auth/users/approve` | Admin: `{id, role, locales?}` |
| `POST /api/auth/users/deny` | Admin: `{id}` |
| `POST /api/auth/users/remove` | Admin: `{id}` — refuses the last Admin and self-remove |
| `POST /api/setup` | Admin: write source/targets/model/domain/catalog via `load_config` probe |
| `GET /api/setup-state?project=` | Current values that prefill the setup wizard |
| `POST /api/setup/smoke-test` | Admin: `{model?, confirm?}` — send one short string to the model; a paid provider needs `confirm` |
| `GET /api/locales` | Languages the tool has profiles for: code, name, script, direction |
| `POST /api/ops/guide` | Getting-started checklist (`skip_provider` avoids contacting Ollama) |
| `GET /api/translator-activity?project=` | Admin/Supervisor: per-translator counts by trigger + timeline |
| `GET /api/project-config?project=` | Prompt family, per-locale families, glossary path, domain map; ADR-60: description, audience, domain, locale notes, model variants, localize mode, bridge, pivots, glossary rows with term counts, attachable projects, conflict mode and conflicting terms |
| `POST /api/project-config` | `{family?, locale_families?, glossary?, glossary_domains?, glossary_shared?, tm_shared?, tm_write?, display_name?, description?, audience?, domain?, localize?, glossary_conflict?, locale_notes?, models?, bridge?, pivots?, source_locale?}` — only the keys sent change; the result is probed via `load_config` and the file is replaced only if it loads (an invalid bridge locale, bad enum or over-long text returns `{ok:false,error}` and leaves the file unchanged). Keys: [ADR-60](decisions/ADR-60-project-config-prompt-bridge-identity.md) |
| `GET /api/model-eval` | Bakeoff markdown reports and Winner comparison rows, plus setup hints (`locales`, `pinned`, `limit`). Does not expose `[locales.models]`. `?report=NAME.md` returns that report's text |
| `POST /api/model-eval/run` | `{locale, model?, limit?, corpus?, dry_run?}` — with `model` or `dry_run`, goes through `op_bakeoff` (dry run counts only; a real run is submitted to taskqueue). Locale-only body enqueues `quality_bakeoff_matrix_*.yaml` via `tq`; refuses without it (ADR-28) |
| `POST /api/model-eval/apply` | `{report}` — append a dated note to `apply-notes.md`; never edits consumer config |
| `POST /api/web-token` | Rotates `{state}/web.token`, prints the new value once, and returns it once |
| `GET /api/usage?project=&period=` | Usage report. `period` is `month` (default), `last_month`, `90d` or `all`. Returns `monthUsd`, `runs` plus `cards`, `budget`, `daily`, `providers`, `locales` and `estimate`. Local cost is `0`; unpriced models are excluded from totals (ADR-65) |
| `GET /api/usage/export?project=&period=` | Ledger events as CSV (`ts,locale,provider,model,input_tokens,output_tokens,characters,usd`) |
| `GET /api/progress?project=` | Coverage and strings/day. Frozen locales have no ETA. Per locale: `priority` (`asap`/`normal`/`frozen`), `humanVerified`, `llmVerified` (LLM output plus TM reuse), `localized`, `velocityPerDay` (30-day mean), `velocity7PerDay`, `etaDates` (`localized`/`llm`/`human` → `{days, date}`; `null` when frozen or no velocity). Top-level `series`: 30 daily `days`, `stages` (cumulative keys per stage for active locales, dated by each key's latest history event), `sources` (keys per day by source class: `human`, `tm`, `mt`, `ai`, `imported`; each key is dated by its latest history event and counted in its current class, so it approximates past throughput), `avgPerDay`, `velocity` (strings written per day per locale, from run records; a multi-locale run is split evenly) and `quality` (per locale daily and trailing-7-day mean score, grouped by `scored_at`, so a key counts on the day it was last scored). Runs carry `delta`, `model` and `provider` |
| `GET /api/analysis?project=&locale=` | Exact, fuzzy, and no-match counts. They sum to the source-key count |
| `GET /api/analysis/report?project=&namespace=&bands=&fuzzy=` | Design-2 report: per-locale due/TM buckets, effort, cloud ceiling, provider, repetitions, budget. `bands=0` skips TM and length ratios; `bands=1` (default) counts exact TM hits only. `fuzzy=1` adds near-match bands (slow on large due sets). The Analysis page fetches bands=0 then bands=1 in parallel; they share a due-source cache. Queue uses `POST /api/ops/translate` |
| `GET /api/review/tickets?project=&locale=&status=&namespace=&key=` | Tickets from `.llm-review`. Status is a stored word (`open`, `in_progress`, `done`, `blocked`) |
| `GET /api/review/counts?project=` | `{counts, active}` over allowed locales; drives the sidebar badge (ADR-66) |
| `POST /api/review/tickets` | `{locale, namespace, key, reason, assignee?, description?, author?, title?}` — create; description becomes the first comment |
| `POST /api/review/tickets/{id}/comment` | `{locale, author, body, resolve?}` — append a comment; `resolve` sets status `done` |
| `POST /api/review/tickets/{id}/status` | `{locale, status, assignee?}` — records a status/assignee event by the signed-in user; empty assignee clears it; unknown status leaves the file unchanged |

The `locales` query parameter on `/api/messages` is a comma-separated list;
the first locale is the primary (editable), the rest are compare (read-only).
`namespace=__all__` returns keys from every namespace with a `namespace` field
on each row.

### Scale limits

| Constant | Value | Effect |
|----------|-------|--------|
| `MAX_PAGE_LIMIT` | 250 | Server clamps `limit` on `/api/messages` |
| `PAGE_SIZE_ALL_THRESHOLD` | 500 | UI hides “all” page size when `sourceTotal` exceeds this |
| `FULL_FINDINGS_THRESHOLD` | 2000 | Idle findings fetch returns `{partial: true}` unless `keys=` or `full=1` |
| `SCALE_GUARD_NS_ALL` | 500 | Client auto-selects first namespace instead of `(all)` |

The thresholds were tuned on a ~3,000-key, 44-namespace catalogue.

## CI integration — how to inform a project about localization status

The recommended way to surface localization health in CI without the web UI:

```bash
# fail on missing keys (and, with --strict, on stale translations)
llm-localizator validate --strict

# list each problem key with its reason
llm-localizator status --missing
```

`validate` exits non-zero on missing keys and other errors, and `--strict` also
fails on warnings such as stale translations, making it a clean CI gate.
`status` only reports and never fails the build. `--missing` prints `[reason] namespace.key` lines — useful for PR
annotations or opening issues.

For GitHub Actions, add a step:

```yaml
- name: Check translations
  run: llm-localizator validate --strict
```

To post a per-locale coverage table as a PR comment, capture the JSON output
of `/api/overview` during a test run of `llm-localizator web` (or call the
`overview()` function directly from a Python script).

A badge approach: run `llm-localizator status --json` (if your version supports
it) or script the `overview` API to write a shields.io endpoint JSON, commit
it, and reference it in the README.

Automated translation PRs are a workflow pattern: a CI job runs
`llm-localizator translate --dry-run` to count outstanding keys, then opens a
draft PR if any locale falls below a threshold. The branch gets a `translate`
job queued via `tq add`, and the PR description cites the coverage diff.

## Linking findings to the docs

Set `[web] docs_url = "https://example.com/docs"` and the editor's live QA line links each
finding code (`V04`, `V98`, …) to `<docs_url>/checks.md#<code>`. Without it the code shows a
tooltip with the docs path and nothing is fetched from the network.


## Workflows (config)

Workflows live per project in `.llm-localize.toml`. A locale uses the workflow
whose `locales` include it; locales in no scope use the workflow named
`default` (overlapping scopes warn, first alphabetically wins). The webhook is
project-wide.

```toml
[notify]
webhook = "https://example.invalid/hook"

[workflows.default]            # canonical pipeline, written compactly
high = 0.80
low = 0.55
max_improve_loops = 2

[workflows.arabic]             # nested block script, scoped to ar
locales = ["ar"]
notify = "webhook"

[[workflows.arabic.script]]
type = "translate"
[[workflows.arabic.script]]
type = "rescore"
[[workflows.arabic.script]]
type = "if"
field = "score"
op = "ge"
value = 0.9
[[workflows.arabic.script.then]]
type = "verify"
[[workflows.arabic.script.else]]
type = "improve"
max_loops = 1                  # per-block; falls back to max_improve_loops
[[workflows.arabic.script]]
type = "notify"
```

Runs are stored under `<state>/workflow/runs/<id>.json`; the last real run per
workflow in `<state>/workflow/runs.json`.

Difference mode: the Machine diff tab shows the machine version against the
current text with removed words struck and added words marked, and each
translation-memory match marks the words that differ from the current text.
The "Highlight differences" checkbox turns it off; the choice is kept in the
browser only. Texts without spaces (Chinese, Japanese, Thai) are compared per
character, and very long texts fall back to a whole-text comparison.
