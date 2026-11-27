# CLI reference

```
llm-localizator <command> [project] [--config PATH] [options]
```

Every project-scoped command resolves its config three ways, in order: the
registered `project` name, an explicit `--config PATH`, or an upward walk from
the current directory.

Exit codes: `0` success, `1` errors, `2` warnings only (`validate`), `64` usage
error, `130` interrupted.

| Command | LLM? | Web (`POST /api/ops/…`) | Purpose |
|---------|------|-------------------------|---------|
| `guide` | no* | `guide` | Checklist of what to do next (`--json` / `--no-input` for agents) |
| `engine` | no | — | Pick the provider + model for every pipeline role (Claude, DeepSeek, OpenAI, local by VRAM): `list`, `recommend`, `show ID`, `apply ID` |
| `queue-engine` | no | `queue-engine` | Rewrite the existing taskqueue blueprints for one engine; before/after table (task, model, VRAM, lane); never creates a blueprint |
| `approach` | no | `approach` | How the project can be localized (local, cloud, agent, human, hybrid); `--set` records the choice |
| `help` | no | — | Print the operator guide (`human`) or the agent guide (`agent`) |
| `set` | no | — | Write one translation through the candidate gate, stamped agent or human |
| `review-risk` | no | — | Rank a locale's translations for human review (text, JSON, CSV) |
| `onboard` | no | — | Set up a project in one step: init, approach, frozen locales, runtime path, taskqueue check |
| `cycle` | no | — | One pass: check keys, validate, status (`--translate` queues), review risk, hardcoded; one report; `--repair --follow` waits for the repair, revalidates those keys, retries once and lists the stuck ones |
| `skill` | no | — | Install or check the agent guide as a Claude skill in the project |
| `init` | no | — | Detect layout, write config, optionally generate blueprints |
| `validate` | no | `validate` | Every catalogue check (`--check-layout` → V28) |
| `ingest-visual` | no | `ingest-visual` | Load consumer findings JSONL into `.llm-review` |
| `scan` | no | — | Usage backrefs and hardcoded strings |
| `discover` | no | `discover` | Propose text collections; writes nothing |
| `status` | no | `status` | File-catalogue coverage, or remote-content gaps; one leverage line per locale |
| `add-locale` | no | `POST /api/add-locale` | Append a target locale (and optional model) to the project config |
| `concordance` | no | `concordance` | Substring search of the translation memory; `--min-similarity 0.55` switches to word-overlap (fuzzy) search |
| `org` | no | `org` | Show whether this project uses the organisation-level TM and glossary (`[org]`, read-only) |
| `tm-export` | no | `tm-export` | Write one locale's translation memory as TMX |
| `tm-import` | no | `tm-import` | Merge TMX into the translation memory (`--dry-run` writes nothing) |
| `glossary-export` | no | `glossary-export` | Write the glossary as CSV or TBX |
| `glossary-import` | no | `glossary-import` | Merge CSV or TBX; `--dry-run` writes nothing; project terms win unless `--conflict overwrite` |
| `glossary-propose` | no | `glossary-propose` | Print candidate terms; writes nothing. `--locale` mines the translation memory for an importable CSV |
| `task` | no | `task` | Work packages of keys with one assignee per locale and a due date (`create`, `list`, `delete`) |
| `discuss` | no | `discuss` | Per-key discussion threads with @mentions and a resolved state (`list`, `add`, `resolve`, `reopen`) |
| `open-pr` | no | `open-pr` | Plan, open or check a pull request for changed catalogue files (`[git_host]`, opt-in) |
| `screenshot-link` | no | `screenshot-link` | Attach screenshots to keys, with optional highlighted regions |
| `source-diff` | no | `source-diff` | Show what changed in one source string and which words need translating (read-only) |
| `draft` | no | `draft` | Keep model suggestions as drafts until accepted (`create`, `list`, `accept`, `reject`) |
| `find-replace` | no | `find-replace` | Find and replace text in one locale's translations (lists unless `--confirm`) |
| `apply-near` | no | `apply-near` | Copy one edited translation onto similar keys you pick (lists unless `--confirm`) |
| `metrics` | no | `metrics` | Edit rate, cycle time and coverage trend from history |
| `impact` | no | `impact` | Locales stale because the stored source hash changed |
| `pseudo` | no | `pseudo` | Throwaway locale (`en-XA` accents+pad, or `en-XX` / `--style xxxx` marker Xs); no state |
| `hardcoded-hunt` | no | `hardcoded-hunt` | Pseudo en-XX + crawl (dogfood presets or `[qa]`) + static refresh (Playwright outside package) |
| `adopt` | no | `adopt` | Stamp catalogue-only keys into state (agent provenance) |
| `agent-backlog` | no | `agent-backlog` | Prompt/JSON list of keys an AI agent should still translate |
| `estimate-cost` | no | `estimate-cost` | Maximum USD for due strings on a cloud provider; no API call |
| `mcp` | no | — | stdio MCP server for agents (`pip install llm_localizator[mcp]`) |
| `agent-hardcoded` | no* | `agent-hardcoded` | Prompt of hardcoded source strings for an agent (writes nothing); `--status` = scan/en-XX readiness JSON |
| `explain-scan` | no | `explain-scan` | Why the scanner did or did not report `FILE:LINE`: skip rules, file type, sink, tier, brand, directive, and the filter each literal failed (ADR-154) |
| `server-copy` | no | — | People-facing English in Python server code (`[scan] server_dirs`): exception details, `error`/`message` payload values, `flash()`; read-only (ADR-134) |
| `glossary-learn` | no | — | Glossary proposals from repeated manual corrections (same word swap in 2+ keys); `--write` saves them for a person to confirm (ADR-135) |
| `import-review` | yes | — | Apply the `decision` column of a `review-risk --format csv` sheet through `set --by human`; `--dry-run` (ADR-135) |
| `sync` | no | `sync` | Reconcile catalogues with source locale |
| `web` | no | — | Browse and edit translations in a local UI |
| `migrate-state` | no | — | Rewrite derived state fields after a format change |
| `translate` | no* | `translate` | Submit or run a translation job |
| `run-translate` | **yes** | `translate` (inline) | Execute a translation job |
| `improve` | no* | `improve` | Submit or run an improve pass |
| `run-improve` | **yes** | `improve` (inline) | Execute an improve pass |
| `documents` | no | — | Submit a Markdown document job |
| `run-documents` | **yes** | — | Execute a document job |
| `review` | no* | `review` | Submit an LLM review pass |
| `run-review` | **yes** | `review` (inline) | Execute a review pass |
| `export` | no | `export` / `POST /api/export` | CSV, XLIFF, or JSON handoff; file count or per-locale/namespace zip; JSON report |
| `import` | no | `import` / `POST /api/ops/import` | CSV, JSON, or XLIFF import, with a change report |
| `rescore` | no* | `rescore` | Submit a BT quality re-score (no retranslate) |
| `run-rescore` | **yes** | `rescore` (inline) | Execute rescore |
| `bakeoff` | no* | `bakeoff` | Compare local models on your own strings (evidence for ADR-12) |
| `run-bakeoff` | **yes** | `bakeoff` (inline) | Execute a bakeoff |
| `doctor` | no | — | Install, config, Ollama, and web UI freshness checks |
| `runtime` | no | — | Install, update or check the shipped browser `i18n.js` in the consumer ([web-runtime.md](web-runtime.md)) |
| `check-keys` | no | — | Keys used in source vs the source catalogue, unused keys, stale en-XX; CI exit codes |

\* `translate`, `improve`, `review`, and `rescore` without `run-*` submit to
taskqueue by default; the web UI can run inline or submit via **Submit tq**.
`guide --smoke-test` may call the model once.

---

Project-scoped commands also accept `--branch NAME`: state and scores are read
and written under `state/branches/<name>/` (a branch tracked on the Branches
page, ADR-61). Catalogue files are unaffected.

## `guide`

Print the getting-started checklist for this project and the exact next
command. Changes nothing unless you confirm a step in an interactive terminal
(or pass flags that opt into a smoke test).

| Flag | Purpose |
|------|---------|
| `--no-input` | Print only; never prompt |
| `--json` | Machine-readable steps (agents) |
| `--smoke-test` | One short translation to verify the pinned model |
| `--skip-provider` | Do not ping Ollama / cloud |

If Ollama is missing or down, the first step tells you to install it from
https://ollama.com and run `ollama serve`. See [getting-started.md](getting-started.md)
and [agents.md](agents.md).

## `init`

Probe for a known catalogue layout and write `.llm-localize.toml`.

| Flag | Purpose |
|------|---------|
| `directory` | Project root (default: cwd) |
| `--name` | Project name (default: directory name) |
| `--source-locale` | Default `en` |
| `--format` | Catalogue format — bypasses auto-detection. Requires `--path`. |
| `--path` | Path template, e.g. `taskqueue/static/locales/{locale}.json`. Required with `--format`. |
| `--taskqueue` | Also generate blueprint YAML into `experiments/operator_queue/` |
| `--no-register` | Skip the `~/.llm_localize/projects.yaml` entry |
| `--force` | Overwrite an existing config |

Detection covers `apps/web/messages/`, `src/messages/`, `messages/`,
`locales/`, and `public/locales/`. If none match, pass `--format` and `--path`
to skip detection entirely — useful for new projects or non-standard layouts:

```bash
llm-localizator init . --format json-flat --path "static/locales/{locale}.json" --name myproject
```

---

## `quality`

One-shot quality report. With no options it validates the current project. With
`--path-template` it works on message files you name, with no registration, and
writes nothing next to them (a scratch config lives in a temp folder).

```bash
llm-localizator quality --root ./messages --path-template "{locale}.json" --source en --target de --target fr
```

| Option | Meaning |
|--------|---------|
| `--path-template` | Files relative to `--root`, with `{locale}` |
| `--root` | Base directory (default: current) |
| `--catalog-format` | Adapter (default `json-nested`) |
| `--source`, `--target` | Locales for the ad hoc run; `--target` repeats |
| `--locale` | Restrict the report to this locale |
| `--score` | Also run the judge model (Ollama; cloud rules apply) |
| `--format text\|json` | Output format |

CLI only: it reads arbitrary paths, so the web UI does not offer it ([ADR-76](decisions/ADR-76-quality-command.md)).

## `rename-placeholder`

Rename a placeholder in the source text and every translation in one step
([ADR-77](decisions/ADR-77-rename-placeholder.md)).

```bash
llm-localizator rename-placeholder --old name --new user --dry-run
llm-localizator rename-placeholder --old name --new user --confirm
```

| Option | Meaning |
|--------|---------|
| `--old NAME` / `--new NAME` | Placeholder names (word characters) |
| `--namespace NS` | Restrict to one namespace |
| `--keys KEY` | Restrict to explicit `namespace.key` entries |
| `--dry-run` | List the edits only |
| `--confirm` | Required to write; without it the command only reports |

Handles `{x}`, `{x, number}`, the variable of `plural`/`select` and placeholders
inside branches. Keys whose source already uses the new name are skipped. State
hashes are refreshed so nothing turns stale; status and provenance are kept.
Translation memory is not changed. Admin and Supervisor only.

## `validate`

All checks in [validation-rules.md](validation-rules.md). No LLM.

| Flag | Purpose |
|------|---------|
| `--locale CODE` | Restrict; repeatable |
| `--namespace NAME` | Restrict to one namespace |
| `--format text\|github\|json` | `github` emits workflow annotations |
| `--strict` | Warnings become errors (exit 1 instead of 2) |
| `--check-expansion` | Enable V14, the noisy expansion-band check. `--semantic` enables V14 as well |
| `--check-numbers` | Enable V38, the locale number and date-order check. Off unless this flag is set |
| `--semantic` | Enable semantic advisory family (V17/V21–V31) and V14. Refused on an unscoped full catalogue above **500** source keys — use `--namespace` instead. V30/V31 coherence is skipped per namespace above 500 keys. |
| `--check-layout` | Enable V28 screenshot layout QA when context `screen`/`image` resolves |
| `--diff-scope [FILE...]` | Only namespaces touching these files; with no arguments reads paths from stdin |
| `--unused` | Also report V41, source keys no scanned code references. Needs `[scan]`; runs the scanner, so off by default |
| `--quiet` | Summary line only |
| `--write-flags` | Append selected findings to the project flags file |

```bash
llm-localizator validate --format github --strict
llm-localizator validate --check-layout --locale pl
git diff --name-only origin/main | llm-localizator validate --diff-scope
```

---

## `ingest-visual`

Load consumer Playwright / browse-review findings JSONL into `.llm-review`
(ADR-27). No LLM. Full procedure (capture → ingest → validate, checkpoints,
TQ suite): [visual-findings.md](visual-findings.md).

| Flag | Purpose |
|------|---------|
| `--path PATH` | Findings file (default: `{context_dir}/../.visual_findings.jsonl` or `[visual] findings_path`) |
| `--dry-run` | Parse and list tickets without writing |

```bash
llm-localizator ingest-visual
llm-localizator ingest-visual --path apps/web/messages/.visual_findings.jsonl --dry-run
```

Prefer the TQ visual QA suite (`on_complete` browse→ingest→validate) when the
consumer UI is already up — see [taskqueue-integration.md](taskqueue-integration.md#visual-qa-suite).

---

## `scan`

Read source code for `t()` call sites and hardcoded user-visible strings.

| Flag | Purpose |
|------|---------|
| `--adapter NAME` | Override the configured adapter |
| `--out-dir PATH` | Where usage artefacts go |
| `--no-write` | Report only |
| `--format text\|github\|json` | |
| `--strict` | Exit 1 if any hardcoded string is found in a surface that is to be fixed. Never calls a model. |
| `--surface a,b` | Only these `[scan.surfaces]` names (`other` is the part no surface matches) |

The text report prints counts by confidence (and by surface), lists the first 100 findings, and
says when it cut the list; `--format json` has all of them.

**Surfaces.** Name the parts of a project and decide what to do with each:

```toml
[scan.surfaces.web]
paths = ["tqdaemon/web", "static/**/*.js"]
mode = "fix"        # counted, fails --strict (default)

[scan.surfaces.cli]
paths = ["tqdaemon/cli.py"]
mode = "report"     # listed, never fails --strict

[scan.surfaces.tests]
paths = ["tests/"]
mode = "ignore"     # dropped, only counted
```

`paths` are globs or directory prefixes; the first surface that matches a file wins. A finding that
matches none belongs to `other` and behaves as `fix`, so a project without surfaces works as before.

The paste-ready report for an agent is `agent-hardcoded`, not `scan`. `scan`
still writes usage artefacts. See [adding_localization.md](adding_localization.md) §4.

---

## `localize-project`

The localization checklist as one report. Read-only unless you pass `--submit`.

```
llm-localizator localize-project --locales pl,de
llm-localizator localize-project --locales pl,de --submit
```

It prints (1) the scan summary, (2) per locale the keys that are absent or empty, and how many existing
translations have no state record, (3) the cost estimate, and (4) the next commands. `--submit` enqueues one
`translate --only-missing` job for those locales through the normal path, so the cloud gate and the budget
cap still apply. It never changes an existing translation. Frozen locales are left out unless you name them
with `--locales`. After the job ends, run `validate` and compare with the errors that existed before.

| Flag | Purpose |
|------|---------|
| `--locales a,b` | Locales to check (default: targets that are not frozen) |
| `--submit` | Also enqueue the translate job (and record the validation baseline) |
| `--baseline` | Record today's validation errors; later runs report new, unchanged and fixed ones |
| `--format text\|json` | |

---

## `discover`

Propose locale-named directories (usually a sibling folder per language). Writes
nothing. Copy a confirmed root into `.llm-localize.toml`. See
[configuration.md](configuration.md).

| Flag | Purpose |
|------|---------|
| `--format text\|json` | |

---

## `status`

File catalogues: per-locale coverage from the state files. A remote collection
(`--collection`) calls the project's content API and reports each unit's
source language. See [content-api.md](content-api.md). File status needs no
network. Remote status does.

| Flag | Purpose |
|------|---------|
| `--format text\|json` | Output format |
| `--missing` | List each missing/stale key instead of summary counts |

`status` counts a key whose target has text that differs from the source but no state record apart from
`missing` ("have text but no record"). The text is there; run `adopt` to record it. Coverage counts only
keys with a record.

| Flag | Purpose |
|------|---------|
| `--by-screen` | Group coverage by the `screen` in each key's context note (least complete first) |
| `--collection NAME` | Default `messages`. A file collection lists path, coverage, and stale. A remote collection lists each unit's source language and what is missing, stale, machine, or human. See [content-api.md](content-api.md) |

```
locale    coverage    done   stale  missing  notes
pl          96.2%    2968       1      117
cs           0.0%       0       0     3086  never translated; namespace file(s) absent
```

(Example totals for a ~3k-key catalogue; yours will differ.)

`--missing` output (useful for CI or a translator's work list):

```
pl: 34 key(s) need translation
  [stale] auth.welcomeBack
  [missing] clubs.newMember
  ...
```

---

## `adopt`

Stamp keys that already have a non-empty target catalogue value but **no**
state entry — typical after manual or Cursor edits to the JSON catalogues.
Writes state / scores / history only (ADR-19 `provider=agent`); does **not**
rewrite catalogue files or refresh stale keys.

| Flag | Purpose |
|------|---------|
| `--locales a,b` | Restrict (default: all targets, including frozen) |
| `--namespace NAME` | Restrict to one namespace |
| `--limit N` | Cap how many keys to stamp |
| `--dry-run` | Report without writing |
| `--format text\|json` | |
| `--model` / `--provider` / `--verified-by` | Override stamps (defaults: `cursor-agent` / `agent` / `cursor-agent`) |

```bash
llm-localizator adopt my-app --locales es
llm-localizator adopt my-app --locales es --dry-run
```

---

## `agent-backlog`

Emit keys an AI agent should still translate or retranslate (`missing`,
`empty`, `no_state`, `stale`), with English source text. Default `--format
prompt` is paste-ready markdown for Cursor.

| Flag | Purpose |
|------|---------|
| `--locales a,b` | Restrict (default: active targets; name a frozen locale here to include it) |
| `--namespace NAME` | Restrict to one namespace |
| `--limit N` | Cap backlog size |
| `--reasons LIST` | Comma-separated subset of `missing,empty,no_state,stale` |
| `--format prompt\|json` | Prompt markdown (default) or JSON |
| `--include-existing` | Show current target text on empty/stale/no_state rows |

```bash
llm-localizator adopt my-app --locales es          # fix false missing first
llm-localizator agent-backlog my-app --locales es  # paste into Cursor
# agent edits catalogues…
llm-localizator adopt my-app --locales es
```

If the web UI was already open when you ran `adopt` from the CLI, click **↺**
(reload) so overview cards re-read `.state` from disk. Ops → adopt refreshes
sidecars automatically.

---

## `estimate-cost`

Maximum USD to send due strings (`missing`, `empty`, `stale`) to a cloud
provider. No API call. `max_usd` assumes one request per string. `batch_usd`
assumes the configured batch size. The bill, after a real run, is actual usage.

`--purpose review` or `--purpose rescore` prices a judge run instead: one call per translated string (source plus
target) on the project provider and its `judge_model`. A local provider quotes no cloud cost. The web Ops drawer shows
the same Estimate button on the review and rescore forms.

Cloud runs are `on_request` unless `[budget] mode = "dynamic"`. `on_request`
requires `--keys namespace.key` (or a remote unit id with `--collection`).
`improve`, `review` and `rescore` take the same `--keys` (repeatable or
comma-separated; also `keys` in the web body): only those keys are sent, so
a paid locale can run them under `on_request`. Without `--keys` they are
refused for a paying locale.

The result also carries `eta_s`, a rough wall time from the median speed of
the last ten `translate` runs (`null` when there are none). The Ops drawer
shows it with an Estimate button for `translate` and `improve`, local
models included.

```bash
llm-localizator estimate-cost --locales pl
llm-localizator translate --locales pl --keys app.hello
```

## `mcp`

stdio MCP server so an agent can estimate, request keys, or localize due
strings. Install the extra first: `pip install "llm_localizator[mcp]"`. Tools take
a registry project name. They do not accept API keys.

```json
{
  "mcpServers": {
    "llm-localizator": {
      "command": "llm-localizator",
      "args": ["mcp"]
    }
  }
}
```

Tools: `estimate_localization_cost`, `request_localization` (`on_request` only),
`localize_due` (`dynamic` only). See
[ADR-35](decisions/ADR-35-cloud-cost-and-agent-mcp.md).

---

## `agent-hardcoded`

Read-only report of hardcoded product strings, grouped by file, for an external
agent. The engine does not rewrite source and does not invent keys (ADR-32).
Exit 64 when no adapter or `src_dirs` is set.

This is the **static** half of hardcoded detection. Pair it with the visual
`en-XX` leftover hunt for painted English the sinks miss — see
[scanners.md](scanners.md) § How detection improved and
[agents.md](agents.md) § Agent wire loop.

| Flag | Purpose |
|------|---------|
| `--adapter NAME` | Override `[scan] adapter` |
| `--limit N` | Cap source files |
| `--format prompt\|json` | Paste-ready markdown (default) or JSON |
| `--show-low` | Include low-confidence bare literals (default report is high+medium) |
| `--llm` | Optional local-model second pass. Off by default. Slow. |
| `--dry-run` | With `--llm`, list files and do not call the model |
| `--refresh` | Rescan even when no source file changed. Without it an unchanged tree returns the report stored in `<state>/scan_cache.json` |
| `--status` | Print scan-cache / en-XX readiness JSON (`next[]` hints); no rescan |

Literal languages (Go, Python, TypeScript, ...) are included. A member named like its own
label, `SAVE: "Save"`, is reported at medium confidence. Helper sinks
(`card` / `field` / `panel` / `section` / `setStatus` / `showError` / `say` /
`action`) and SSR chrome land at medium so they appear in the default report.
`GET /api/scan/status` returns the cache age, counts per confidence, en-XX lag,
`qaLocales`, and ordered `next` commands (ADR-54). Bump `_SCAN_VERSION` when adding sinks so
the cache invalidates.

```bash
llm-localizator agent-hardcoded --status        # what next?
llm-localizator agent-hardcoded my-app          # paste into Cursor; English only
llm-localizator agent-hardcoded my-app --llm --dry-run
```

When `tq` is on PATH, a non-dry `--llm` run submits `run-agent-hardcoded`.
Without `tq`, the command runs the model inline. The default path never
constructs a provider.

Every hit carries a stable `id` and a `decision` (`null`, `accepted`, `applied`). Hits you
ignored are hidden; `--show-ignored` lists them again (ADR-55).

## `hardcoded-hunt`

Orchestrator for the **visual** half of hardcoded detection (ADR-110,
ADR-27, ADR-119). Runs `pseudo --locale en-XX`, then the engine's own
`experiments/hardcoded_visible/crawl.py` (never a copy in the project repo),
then refreshes `agent-hardcoded --split auto`. For the engine's own UI the crawl
uses presets plus `intersect.py`. A project with a `[qa]` block gets the
config-driven crawl instead (en-XX leftovers, `dynamic_text.json`, ar/zh layout
and screenshots) under `~/.llm_localize/data/<name>/qa/<ts>/`. Playwright stays outside
the package. Prefer `agent-hardcoded --status` first. Full loop:
[scanners.md](scanners.md) § Operator / agent workflow.

| Flag | Purpose |
|------|---------|
| `--skip-crawl` | Pseudo (+ optional static) only |
| `--skip-static` | Skip the agent-hardcoded refresh |
| `--serve` | Let crawl start the server (`[qa] start` for consumers); default expects it running |
| `--format text\|json` | Human lines or JSON result |

```bash
llm-localizator hardcoded-hunt                  # needs qa_locales + Playwright for crawl
llm-localizator hardcoded-hunt --skip-crawl     # marker + static only
```

## `explain-scan`

Why one line was, or was not, reported by the hardcoded-string scanner. The command walks the same steps as a scan
for that one file: `[scan] src_dirs`, skipped folders and `[scan] exclude`, the file type, minified or unreadable
files, the file's scanner, brand names and ignore directives. Each hit on the line is shown with its tier and reason;
each quoted literal that was not reported gets the first filter that rejected it (inside a translation call, an
API/enum token, not prose, or no rule for that position). Without `:LINE` it lists every hit in the file. Read-only.

```bash
llm-localizator explain-scan src/app/views.py:42
llm-localizator explain-scan src/app/views.py:42 --format json   # for agents
```

The web Ops panel runs the same op (`POST /api/ops/explain-scan` with `file` and `line`, or `target`).

## `scan-decide`

Say which scan results are worth localizing. Ids come from `agent-hardcoded --format json`.
`discover` proposals can be decided too (`--kind collection`).

| Flag | Purpose |
|------|---------|
| `accept\|ignore\|reset\|status` | What to do (default `status`: counts and the apply mode) |
| `--ids A,B` | Ids from the report |
| `--confidence high\|medium\|low` | Every pending hit of that confidence |
| `--file GLOB` | Pending hits in files matching the glob |
| `--all-pending` | Every pending item |
| `--key NAME` | Catalogue key for one accepted hit; refused if it holds other text |
| `--note TEXT` / `--by NAME` | Stored with the decision |
| `--kind hit\|collection` | What is being decided (default `hit`) |

What `accept` does follows `[apply] mode` (`docs/configuration.md`): `manual` records it,
`request` opens a review ticket on the source locale, `auto` writes the key and queues
translation. Admin and Developer only.

Live hits for decide/ignore include **low** confidence even when the default
`agent-hardcoded` report is high+medium only (`show_low=True` inside
`scan-decide`). Use `ignore --confidence low` for protocol/API/docs noise after
a `--show-low` report.

```bash
llm-localizator agent-hardcoded my-app --format json    # find ids
llm-localizator scan-decide my-app accept --confidence high
llm-localizator scan-decide my-app ignore --confidence low
llm-localizator scan-decide my-app ignore --ids 3fa9c1d20b7e
llm-localizator apply my-app --confirm                  # manual mode: write accepted keys
```

## `patch` and `apply`

`patch` writes `patch.json` and `patch.md` (hardcoded strings with a suggested key, plus
catalogue gaps) and changes nothing. `apply --confirm` writes the source-locale keys for
accepted hits and copies source text into target catalogues as placeholders for `translate`;
`--dry-run` previews. Once any decision exists both cover accepted hits only. Neither edits
source code; an agent does that from the report (ADR-32, ADR-55). Admin and Developer only.

`translate`, `export`, and `status` take `--collection`. Omitting it means
`messages`. A file collection other than `messages` uses the documents
pipeline. A collection with `kind = "remote"` does not: it reads and writes
the content API, one unit at a time, from that unit's `source_locale`.
Markdown export is the file, not a remote unit.

---

## `web`

Serve the local translation browser. See [web.md](web.md) for the full UI,
API, and **Translator mode** (CTRL-hover English tips + in-page edit overlay).

| Flag | Purpose |
|------|---------|
| `--port N` | App port (default 8770), clear of taskqueue's 8765/8766 |
| `--marketing-port N` | Marketing site port (default 8760; ADR-45) |
| `--no-marketing` | Do not bind the marketing site |
| `--no-browser` | Do not open a browser window |

Binds `127.0.0.1` only (app and marketing). A POST on the **app** port needs
the session token printed at startup (`X-LLM-Token`). That token is not the
content-API bearer token. The marketing port is GET-only HTML and static
assets — no catalogue APIs.

---

## `migrate-state`

Rewrite derived fields in the state files after a signature-format change.

| Flag | Purpose |
|------|---------|
| `--locales LIST` | Default: active (non-frozen) targets |
| `--dry-run` | Report what would change; write nothing |
| `--stamp-provider` | Write inferred `provider` (ADR-19) onto entries that lack one |

**When you need it.** `structure_signature` is versioned (ADR-11). When
`SIGNATURE_VERSION` changes, every stored value mismatches the freshly computed
one, so every key reads as *structurally stale*. A policy layer acting on that
can overwrite translations with the source text.

`validate` tells you when this has happened: a `V08` finding on a key whose
source has **not** changed can only mean the stored signature was written by
something computing it differently — an older format version, or a second
implementation that has drifted.

```
warn [V08] pl/play.claim: structure signature does not match the current
source even though the source is unchanged -- run 'llm-localizator migrate-state'
```

Safe because `structure_sig` is *derived*: it is recomputed from the current
source with no model and no network. `src_sha`, `translated_at`, `model`, and
`status` are left untouched, so no translation is invalidated and nothing is
queued for retranslation. Entries whose source key no longer exists cannot be
recomputed; they are reported and left alone rather than pruned.

`--stamp-provider` is additive (ADR-19): it only fills missing `provider`
channels from `model` / `verified_by` heuristics and does not change hashes.
---

## `translate` / `run-translate`

`translate` submits to taskqueue and exits. `run-translate` does the work and is
what the blueprint invokes — see [taskqueue-integration.md](taskqueue-integration.md).

| Flag | Purpose |
|------|---------|
| `--locales LIST` | Comma-separated; default is active (non-frozen) targets |
| `--collection NAME` | Default `messages`. File collections use the documents pipeline. A remote collection translates each unit from its own `source_locale` ([content-api.md](content-api.md)) |
| `--namespace NAME` | Restrict to one namespace |
| `--model NAME` | Override the model for every locale |
| `--batch-size N` | Keys per request (default 10) |
| `--force` | Retranslate keys that are already up to date |
| `--flagged` | Only keys flagged through the dev overlay |
| `--sync` | Cloud: one synchronous request per batch instead of Message Batches. Full price, no wait; use for small or urgent runs |
| `--only-missing` | Only keys whose target value is absent or empty. Existing translations are never touched |
| `--keys-file PATH` | Explicit keys read from a file (one per line or comma-separated, `#` comments ignored, `-` reads stdin); merged with `--keys`. Use it instead of a very long `--keys` |
| `--tag TAG` | Only keys whose context note carries this tag; repeat or comma-separate for several (any match). Tags are set in the editor's key panel or as `"tags": ["checkout"]` in the context file, and never make a translation stale ([ADR-75](decisions/ADR-75-tag-runs.md)) |
| `--dry-run` | Print the work list; call nothing, write nothing |
| `--pre-translate` | Write the translation with history `trigger=pre-translate`. No score row and no low-score flag. Not a new status |
| `--ignore-min-keys` | Bypass `[translate] min_keys` (operator runs; `translate` submit always sets this). Automated sync→translate omits it. |

**Existing translations without a record.** A target value that differs from the
source and has no state record (the project had catalogues before it used this
tool) counts as an existing translation, not a gap. A plain run leaves it as is
and says so (`left as is: pl 612 ...`). `llm-localizator adopt` records such
values; `--force`, or naming the key with `--keys`, retranslates them.

`--dry-run` is the safest way to confirm the tool is looking at the files you
expect. It is also the golden-fidelity gate: a dry run must leave every file
byte-identical.

**Incremental updates.** Each run only translates keys where the source has
changed since the last successful translation — those with `status: missing` or
`status: stale` in the state file. Keys that are already `machine`, `llm_reviewed`,
or `human` are skipped unless you pass `--force`. This means re-running
`translate` after adding ten new English strings costs roughly ten LLM calls,
not a full catalogue re-translation.

Pivot locales are automatically ordered so a reference is translated before the
variant that depends on it.

**Two-phase scoring (deferred).** When `[quality] score_model` (or
`improve_model` fallback) differs from the pinned translate model and
`multi_sample < 2`, `run-translate` splits work:

1. **Phase A** — translate with the pin; score with CPU heuristics only
   (`scorer=heuristic`). Low-score flags are written in phase B, not here.
2. **Phase B** — `ollama stop` on the pin, warm the score model, batch
   back-translate (`[quality] bt_batch_size`, default 5), update `.llm-scores`,
   append flags, `ollama stop` on the score model.

Stdout includes `phase 2: BT scoring N key(s) with …` when phase B runs. A job
killed after phase A leaves heuristic rows; the next `run-translate` or
`rescore` finishes scoring without re-translating. Set `[quality] defer_scoring
= false` to restore per-key BT during translate (old behaviour; causes model
swap every key when models differ). `multi_sample ≥ 2` always scores inline
(best-of-N needs BT during generation).

**Translation memory.** When `[prompt] tm_dir` is set (default `.llm-tm`), an
exact source+context hit reuses the stored text with `trigger=tm-hit` (no LLM
call). Near matches (token overlap) are injected as few-shot examples only —
never auto-accepted. See ADR-22.

---

## `documents` / `run-documents`

Section-level Markdown translation for long documents.

| Flag | Purpose |
|------|---------|
| `--doc STEM` | A single document, e.g. `terms` |
| `--doc-dir PATH` | Document root (default `<project>/content/legal`) |
| `--locales LIST` | |
| `--model NAME` | |
| `--dry-run` | |
| `--draft-edits` | Print a minimal-edit draft (diff) for each changed section; runs the model, writes nothing. Needs the old English kept in the document state, so sections translated before C-047 get no draft until retranslated once |

Only sections whose source changed are retranslated, and the previous
translation of a section is offered to the model as an update target so wording
stays stable. **If any section fails, the entire locale file is deleted** so the
page falls back to the source language — a half-translated privacy policy looks
authoritative and is wrong.

---

## `review` / `run-review`

A second pass over machine translations. Promotes `machine` to `llm_reviewed`,
applies corrections that still validate, and marks `needs_better_model` on
rejection — the signal to route that locale to a larger model rather than retry
the same one.

| Flag | Purpose |
|------|---------|
| `--locales LIST` | |
| `--namespace NAME` | |
| `--model NAME` | Reviewer model; defaults to the locale's translation model |
| `--dry-run` | Count what would be reviewed |

A correction is only accepted if it passes the same validation as an original
translation. A reviewer that "fixes" a string by dropping a placeholder is not
trusted over the validator.

---

## `sync` / `run-sync`

Gather work without a watcher daemon (ADR-1). Runs `scan` when configured,
counts missing/stale keys, writes `proposed_keys.json` for hardcoded findings,
and submits an incremental `translate` job to taskqueue.

| Flag | Purpose |
|------|---------|
| `--locales LIST` | |
| `--dry-run` | Report only; write nothing; do not submit |
| `--no-translate` | Gather artefacts but do not enqueue translate |
| `--diff` | Write the work manifest `work_manifest.json` in the state directory: added, changed and removed keys with the locales that need work |
| `--exit-nonzero` | With `--diff`: exit 1 when keys were added or changed (a CI gate) |
| `--strict-branch` | Exit 1 when the checked-out git branch is not `[catalog] source_branch` (default `main`) |

Use from CI as `llm-localizator run-sync --dry-run` to surface backlog, and as a
nightly queue task for continuous intake. Sync always warns when it runs on a
branch other than `source_branch`, because pushing source strings from a side
branch can delete another branch's translations. Ready-made pull-request checks
are in [ci-templates/](ci-templates/).

`sync` (not a dry run) and `push-strings` also log each changed English string to
`source_history.jsonl` in the state directory; the editor uses it to explain why a key is stale.

## `check`

CI / pre-commit gate. Reads state only (no LLM) and exits 1 when a non-frozen locale
is below `--min-coverage` (default 1.0) or has stale translations (`--allow-stale` ignores those).

```bash
llm-localizator check --min-coverage 0.95 --locales pl,de
```

## `workflow`

Run a named workflow script (ADR-62/63): route keys, then improve and review
blocks. `--route-only` does no LLM work; `--dry-run` counts what each block would
do; `--submit` sends LLM blocks to the taskqueue, `--inline` runs them here.
A run that stops at an approval block prints its id; `--resume RUN_ID` continues it.

The `validate` block runs the catalogue checks on the keys that reach it, logs the findings and
lets the keys continue. `--list-presets` prints the built-in starting scripts (the same list the
web "New workflow" dialog offers), including `tm_llm_validate`.

```bash
llm-localizator workflow --name default --locales pl --dry-run
llm-localizator workflow --resume 20261020T101500Z-ab12
llm-localizator workflow --list-presets
```

## `export` options

`--xliff-version 2.0` writes XLIFF 2.0 (one target locale per file, so pair it
with `--layout per-locale` for several locales). `--bom` prefixes CSV with a
UTF-8 byte-order mark so Excel opens it as UTF-8.

`--format xlsx` writes the CSV grid as an Excel workbook, one sheet per namespace
(needs the optional extra: `pip install "llm_localizator[xlsx]"`; `--out` is required
because the file is binary). `import` reads `.xlsx` the same way, alone or inside a
zip; every sheet must share the first sheet's header. The old `.xls` format is not
read: save it as `.xlsx` first. Cells are plain text, so a translation starting with
`=` is stored with a leading apostrophe and restored on import.

`--approved-only` blanks every translation that is not verified (or, with
`[delivery] require = "reviewed"`, not verified or still under an open review
ticket). Blank cells import back as untranslated, so the file shows exactly what
is cleared for release.

## `watch`

```bash
llm-localizator watch --interval 5 --diff
```

Foreground loop for a developer: syncs once, then again whenever a source catalogue file
changes, and stops on Ctrl-C. It only gathers the backlog (no model, no queue), so it is not
a scheduler (ADR-1). For unattended intake use a queue task or a CI trigger.

`translate --manifest PATH` (and `run-translate --manifest PATH`) then works on
exactly the keys the manifest lists.

When `[review] escalate_after_days` is set, `sync` posts the `[notify]` webhook
once for each review ticket that has been open longer than that; the payload names the
locale's supervisor.

---

## `improve` / `run-improve`

Overnight pass over low `quality_score`, flagged, and `needs_better_model` keys.
Retranslates with `[quality] improve_model` (default `aya-expanse:8b`), scores
the candidate (optional back-translation), and **keeps only if the score rises**.
Otherwise the previous value stays; history records the attempt
(`improve-reject` / `improve-fail`). Those stuck keys are skipped for
`[quality] improve_reject_cooldown_hours` (default 7 days) so the next
`--limit N` batch rotates; use `--include-rejected` to force a retry.

| Flag | Purpose |
|------|---------|
| `--locales LIST` | |
| `--namespace NAME` | |
| `--model NAME` | Override improve model |
| `--limit N` | Max keys this run (default 50) |
| `--keys KEY` | Explicit keys (`namespace.key`); when set, skip the low-score gate |
| `--tag TAG` | Only keys carrying this context tag (repeatable); resolved to `--keys`, so it also skips the low-score gate |
| `--include-rejected` | Retry keys that KEEP/FAIL'd recently (default: skip during cooldown) |
| `--dry-run` | List candidates only |

`[budget] monthly_usd = 0` keeps the lane fully local. A positive budget is
reserved for a future API improve path.

---

## `rescore` / `run-rescore`

Recompute quality scores with back-translation (and optional LQS judge) **without
changing catalogue text**. Use after scoring-rule changes, to refresh scores
for strings you already trust, or to finish phase B after an interrupted
deferred translate. Prefer-queue (ADR-15 / ADR-28): `rescore` submits;
`run-rescore` is what the blueprint invokes.

Scores are computed in batches of `[quality] bt_batch_size` (default 5) with one
BT call per batch when no LQS judge is configured. The worker calls
`ensure_ready(score_model)` before scoring and `ollama stop` on exit.

| Flag | Purpose |
|------|---------|
| `--locales LIST` | |
| `--namespace NAME` | |
| `--model NAME` | Override BT/score model (default: `[quality] score_model` / `improve_model`) |
| `--dry-run` | List keys that would be rescored; no LLM, no score writes |

Each completed run writes `{state}/_runs/{run_id}.json` and emits a final
`TQ_METRIC` line with `wall_s`, `keys_per_s` or `items_per_s`, and command context.
Ops also print one JSON object to **stderr** per finished `dispatch_op`
(`command`, `locale`, `keys`, `wall_seconds`, `exit`) so CI can parse wall
time without scraping text logs. Cloud HTTP (Anthropic, OpenAI, DeepSeek,
DeepL) retries 429 and 5xx with capped backoff; other 4xx fail once. Ollama
is unchanged. An interrupted translate leaves `last_finished` on the flush
journal as `phase=progress` (not a mutator block); already-written keys are
skipped via `src_sha` on the next run.

---

## `bakeoff` / `run-bakeoff`

Translate a fixed set of your own strings with each candidate model, back-translate,
and score. It is the evidence step of [ADR-12](decisions/ADR-12-local-model-bakeoff-defaults.md):
it writes a report and a ledger and **never** edits `[locales.models]`. Local Ollama
models only. Prefer-queue (ADR-15 / ADR-28): `bakeoff` submits when `tq` is on PATH and runs
here otherwise; `run-bakeoff` always runs here.

```bash
llm-localizator bakeoff --locales pl --models qwen2.5:7b --dry-run
llm-localizator run-bakeoff --locales pl --models qwen2.5:7b --limit 30
llm-localizator bakeoff --locales pl --propose-config
```

| Flag | Purpose |
|------|---------|
| `--locales LIST` | Locales to test (default: the first active target) |
| `--models LIST` | Ollama tags (default: the pinned set). The locale's current model is **always** added |
| `--limit N` | Keys to test, sampled evenly across UI roles (button, error, title, ...); default 30 |
| `--corpus FILE\|builtin` | A corpus JSON, or the shipped 76-string set (default: this project's strings) |
| `--out DIR` | Where `REPORT.md`, `LEDGER.md` and `matrix_results.jsonl` go (default `<state dir>/bakeoff`) |
| `--family chat\|mt_chat` | Prompt family (default: the project's) |
| `--matrix` | Standard cells: stripped/chat, consumer/chat, consumer/mt_chat |
| `--force-cells` | Re-run cells already in the ledger (default: skip them, so a retry resumes) |
| `--dry-run` | List the cells; call no model |
| `--propose-config` | Print a `[locales.models]` snippet from the `## Winners` table of `REPORT.md` in `--out`; unchanged models are marked, runner-ups are shown as comments. Writes nothing |

`REPORT.md` only ever gets a dated section appended; a hand-written Winners section above
it is never rewritten. The gate is unchanged: mean back-translation >= 0.70 and no
glossary-blocking rejects. Checklist: [model-evaluation.md](model-evaluation.md).

---

## `metrics`

Read-only process metrics from the history files. No LLM.

```bash
llm-localizator metrics
llm-localizator metrics --locale pl --since 30d
llm-localizator metrics --format json
llm-localizator metrics --why-low --locale pl
llm-localizator metrics --by locale+user --since 30d --format csv
```

`--by user|locale|locale+user` switches to an activity report: edits per translator and/or locale
(`edits`, `translate`, `web_edit`, `last_at`) from the translator activity log. `--format csv` needs `--by`;
cells starting with `=`, `+`, `-` or `@` get a leading quote so spreadsheets do not execute them.
On the web, `GET /api/metrics?by=...&format=csv` and the Export CSV links on the Team activity page
are limited to Admin and Supervisor.

`--why-low [--threshold N]` instead lists, per locale, how many keys scored below the threshold (default 0.55) and which quality dimension is weakest for each (`placeholders`, `terminology`, `fluency`, ...). Keys whose score has no stored dimensions show as `no-dimensions`; unscored keys are not counted. The model and prompt rule behind a text are not recorded, so they are not attributed. The editor shows the same weakest dimension on the quality card of a low-scored key.

| Column | Meaning |
|--------|---------|
| machine | Keys a machine translated in the window |
| edited | Of those, keys a person then edited in the web UI |
| edit rate | edited / machine |
| cycle h | Mean hours from the machine translation to the first human edit |
| coverage | Share of source keys with a value; the JSON carries a weekly trend for 90 days |

`--since` takes `30d`, `12h`, `2w` or an ISO date. History retention limits how far back the
numbers go, and the coverage trend is approximate (first history event per key). The web UI
serves the same data at `GET /api/metrics`, including `editRateWeekly` (12 weekly points).

## `task`

A task is a named set of keys with one assignee per locale and an optional due date. It holds no text; progress is read from the state store (a key is done for a locale once a person verified it), so a task finishes when every assigned locale is fully verified.

```bash
llm-localizator task create --name "Checkout copy" --namespace checkout --assign pl=anna,de=ben --due 2026-12-01
llm-localizator task create --name "Open items" --keys app.a,app.b --assign pl=anna --unverified
llm-localizator task list --assignee anna
llm-localizator task delete --id T-001
```

`--unverified` keeps only keys not yet verified in an assigned locale. `list` shows per-locale progress and marks overdue tasks; `--assignee` is the "My tasks" view and the web Ops drawer offers the same. There is no outbound notification: the list is the notification.

## `discuss`

A thread per source key (shared by every locale) for questions about the English or the translation: comments, `@name` mentions and a resolved state. A thread holds no translation text and changes nothing in the catalogue.

```bash
llm-localizator discuss add --namespace app --key greeting --text "@anna is this formal?" --by ben
llm-localizator discuss list --open-only
llm-localizator discuss list --mention anna
llm-localizator discuss resolve --namespace app --key greeting
llm-localizator discuss reopen --namespace app --key greeting
```

A new comment on a resolved thread reopens it. `list` filters by `--namespace`/`--key`, `--open-only` and `--mention`. `task list` shows how many unresolved threads touch each task's keys. Everyone with a role can discuss, including Translators; the data stays in the project state directory and nothing is sent anywhere.

## `draft`

Keeps a model suggestion as a *draft* until a person accepts it. Nothing reaches the catalogue, state, history or TM before then.

```bash
llm-localizator draft create --locale pl --namespace app --key greeting
llm-localizator draft list --locale pl
llm-localizator draft accept --locale pl --keys app.greeting
llm-localizator draft reject --locale pl --keys app.greeting
llm-localizator draft create --mode minimal-edit --locale pl --namespace app --key greeting
```

`create` runs the same pipeline as `suggest` for one key and stores the text, score and model with the English text it was made from. A new draft for the same key replaces the old one. `accept` validates the text (placeholders, HTML, `maxChars`, glossary) and writes it as a human edit recorded in history with trigger `draft-accept`; locked and verified keys, translations a person edited (`status=human`, unless you pass `--confirm`), and drafts whose English text has changed since, are skipped and shown with the reason. `list` marks stale drafts.

`--mode minimal-edit` (create only, opt-in) asks the model for the smallest edit of the *existing* translation after a recorded source change, sending the old source, the new source and the current translation. The result is a draft like any other, so it is never applied until accepted. It needs a recorded change (`sync` writes it), a non-empty translation, and obeys the cloud gate. Existing translate and suggest prompts are unchanged.

## `source-diff`

Read-only. For one key, shows the old and new English source from the source-change log, the current translation (with `--locale`) and the words of the new source the old translation does not cover.

```bash
llm-localizator source-diff --locale pl --namespace app --key greeting --format json
```

JSON carries `oldSource`, `newSource`, `translation`, `spans` (`equal`, `insert`, `delete`, `replace`) and `newSpans` (`text`, `changed`); the editor colours `changed` spans as needing translation. A key with no recorded change returns `changed: false`.

## `suggest`

```bash
llm-localizator suggest --locale pl --namespace app --key greeting
```

Asks the model for one translation and prints it with its score. Nothing is written: no
catalogue value, state, history or TM entry. The web editor's Suggest button calls the same
operation, and Translators may use it even though they may not run `translate` (ADR-53).

```bash
llm-localizator suggest --locale pl --namespace app --key greeting --explain
llm-localizator suggest --locale pl --namespace app --key greeting --alternatives
llm-localizator suggest --locale pl --namespace app --key greeting --ambiguity
```

`--explain` adds a "Why this result" section: model and register, context and notes, glossary
hits, TM and same-screen examples, the pivot text, the length limit, missing-context reasons and
the retrieval trace. The editor shows the same data under the suggestion. It contains no provider
URLs or keys. In JSON output it is `data.explain`.

`--alternatives` also asks up to two other configured models (the secondary role, then the roster
default; a model already used is skipped) and returns each version that differs, with its score,
as `data.alternatives`. Projects that pay for a cloud provider get none, since every extra model is
another paid call. The editor shows them under "More versions" with the differences highlighted
against the first suggestion; nothing is stored until a person picks one and saves.

`--ambiguity` makes one more model call that names up to three source terms with several senses in the target language and the sense the suggestion used, as `data.ambiguity` (`term`, `senses`, `chosen`). It is advice for the reviewer: it changes no score, state or fingerprint ([ADR-90](decisions/ADR-90-ambiguity-notes.md)). Cloud-paying projects get none. The editor shows the notes under the suggestion when "Flag ambiguous terms" is ticked.

## `apply-near`

Copies one edited translation onto *similar* keys you choose. Identical English texts are already filled when you save in the editor; this covers near matches (for example "Save changes" and "Save change").

```bash
llm-localizator apply-near --locale pl --namespace app --key save_changes
llm-localizator apply-near --locale pl --namespace app --key save_changes --min-similarity 0.9 --keys app.save_change --confirm
```

Without `--keys` and `--confirm` it only lists candidates with their similarity (character edit similarity of the English texts, default at least 0.85). Each target is checked by the normal validator (placeholders, HTML, `maxChars`, glossary); verified, locked, human-edited and intentional keys are skipped and shown with the reason. Writes happen under the project lock, are stamped as human edits and recorded in history with trigger `apply-near`. The editor offers the same as "Apply to similar keys" on a translated key, with the English differences highlighted.

## `find-replace`

Finds literal text in one locale's translations and shows each key before and after.

```bash
llm-localizator find-replace --locale pl --find Konto --replace Profil
llm-localizator find-replace --locale pl --find Konto --replace Profil --keys app.title --confirm
```

Without `--keys` and `--confirm` it only lists matches (case-insensitive unless `--case-sensitive`). Each result is checked by the normal validator (placeholders, HTML, `maxChars`, glossary); verified and locked keys are skipped and shown with the reason. Writes happen under the project lock, are stamped as human edits and recorded in history with trigger `find-replace`.

## `flag-source` and `source-review-queue`

```bash
llm-localizator flag-source --namespace app --key greeting --note "ambiguous: verb or noun?"
llm-localizator source-review-queue
```

Flags an English string for review and lists the open flags. A flag is a review ticket on the
source locale, so it never triggers a retranslation.

## `bulk-clear`

```bash
llm-localizator bulk-clear --locale pl --stale-to-source
llm-localizator bulk-clear --locale pl --purge-machine-older-than 90 --confirm
```

Sends keys back to the translate backlog by dropping their state entry; the old text stays in
the catalogue as a fallback. `--stale-to-source` picks keys whose English changed since they
were translated, `--purge-machine-older-than DAYS` picks old machine translations. Human,
verified and locked keys are always kept. Without `--confirm` it only lists what it would clear.

```bash
llm-localizator bulk-clear --invalid --latin-leftover --dry-run
```

`--invalid` picks translations that fail a hard check: a backslash the source does not have (V39),
letters from a foreign script, a placeholder, HTML or literal mismatch. `--latin-leftover` picks
non-Latin translations that carry Latin words the source does not. A row stamped `human` whose
provider is `import` or `agent` is a hand-off copy and is eligible; a real web edit is not
(ADR-48, ADR-57). The editor's bulk bar has a **Requeue broken text** button for both.

## `glossary-propose --locale`

```bash
llm-localizator glossary-propose --locale pl --min-occurrences 5 --out suggestions.csv
```

Mines the locale's translation memory for short source terms that keep pairing with the same
target phrase in at least `--min-occurrences` entries and are not in the glossary yet. The
output is the `glossary-import` CSV format; review it, then import it. Nothing is written to
the glossary.

## `analytics`

Read-only summary of persisted run speed and verify/score lag (ADR-37). No LLM.

```bash
llm-localizator analytics my-app
llm-localizator analytics my-app --run-command translate --locale ar --last 5
llm-localizator analytics my-app --format json
```

| Flag | Purpose |
|------|---------|
| `--run-command NAME` | Filter: `translate`, `improve`, `review`, `rescore` |
| `--locale CODE` | Runs that include this locale |
| `--locales LIST` | Locales for lag report (default: active targets) |
| `--model NAME` | Filter by pinned model |
| `--since ISO` | `started_at` lower bound |
| `--last N` | Most recent N runs only |
| `--format text\|json` | |

**Lag report** (no extra capture): median hours from `translated_at` to
`scored_at` / `verified_at`; counts keys still at `scorer=heuristic`.

**Final `TQ_METRIC` fields** (end of translate/review/improve/rescore):

| Field | Meaning |
|-------|---------|
| `command` | Pipeline command |
| `run_id` | Manifest id |
| `done` / `total` | Progress |
| `wall_s` | Wall seconds |
| `keys_per_s` / `items_per_s` | Throughput |
| `phase_a_s` / `phase_b_s` | Deferred translate phases |

---

## `doctor`

Sanity-check the install and (optionally) a project. Probes whether a web
server on port 8770 is running **stale code** — the usual reason export/history/
ops buttons are missing after `pip install -e`.

```bash
llm-localizator doctor              # install + web freshness only
llm-localizator doctor my-app       # include project config/catalog checks
llm-localizator doctor --json       # machine-readable
```

With a project that sets `[scan]`, doctor also warns about the hardcoded-string scan: `src_dirs` that do not exist,
file types inside them that no scanner reads (`NOT scanned`, e.g. `.pug`), and Xcode targets that compile Swift but
do not ship `Localizable.strings` / `.xcstrings` (their `Text("…")` stays English). Store listings present only in
the source locale are the `store-text` warning (ADR-152).

If `web` reports **fail** or **warn**, stop the old server (Ctrl-C in its
terminal) and run `llm-localizator web` again.

## `engine`

```
llm-localizator engine list
llm-localizator engine recommend --gpu-busy
llm-localizator engine show claude-haiku
llm-localizator engine apply claude-haiku
llm-localizator engine apply local-16gb --accept-unbenchmarked --vram 16
llm-localizator engine fetch
llm-localizator engine fetch --write
llm-localizator engine fetch --from https://example.org/engines/ --write --accept-unverified
```

An engine sets the provider and model of every role (translate, BT score, judge, improve) in one switch (ADR-156).
`list` shows the built-in engines with their evidence status (`benchmarked`, `waiver`, `smoke`, `unbenchmarked`) and
whether this machine can run them (API key present, GPU size from `nvidia-smi` or `--vram`). `recommend` picks the
best fit; `--gpu-busy` skips engines that need the GPU. `apply ID` (alias `use ID`) writes `[engine] id` and removes the project keys
that would hide the engine; per-locale overrides stay. Cloud engines never turn cloud on: the command prints the
`[privacy]` / `[budget]` lines to add yourself.

`fetch` downloads engine files from the project site (`--from URL` for another host; default
`https://wwylon.github.io/llm_localizator/engines/`). It is a dry run until `--write`: each file is fetched without following
redirects, capped at 64 KB, hash-checked against `index.json`, and refused if it sets anything an engine may not
(privacy, budget, URLs, keys). A file whose hash this release ships is `verified`; anything newer is `UNVERIFIED`
and is saved only with `--accept-unverified`, after you have read it. Fetched engines live in
`~/.llm_localize/engines/` and never replace a built-in id.

For one run only, pass `--engine ID` to translate, improve, review, rescore or documents
(queue: `tq retry <project>/<task> --set --engine=ID`).

## `queue-engine`

```
llm-localizator queue-engine claude-haiku --dry-run
llm-localizator queue-engine local-8gb my-project
```

Rewrites the blueprints in `experiments/operator_queue/` that already exist, with `--engine ID` baked into `args`
and the GPU reservation, lock and Ollama probe sized for that engine (a cloud lane drops them). It prints a
before/after table of task, model, VRAM and lane. It never creates a blueprint (a new YAML may be queued and run at
once) and does not change `.llm-localize.toml`; use `engine apply` for that. A job whose model the queue cannot size
(for example a cloud engine without `[privacy] allow_cloud` and a budget, which falls back to the GPU) is skipped and
listed. The web Queue page (`/app/queue`) shows the same tasks with their queue status, read-only.

## `approach`

The options for who writes the translations, what each needs and costs, a
recommendation for this machine, and how strings reach the app (ADR-123).
`guide` shows the same list as its step "Choose how to localize".

```bash
llm-localizator approach myproject              # list options + recommendation
llm-localizator approach myproject --set hybrid # record [translate] approach
llm-localizator init --approach agent           # choose while creating the config
```

## `onboard`

One step from an app folder to a project ready to translate: `init` when there is
no config, then frozen layout locales, the approach and `[web] runtime_path`. It
installs the runtime only with `--install-runtime`, reports whether taskqueue knows
the project (it never edits `~/.taskqueue/projects.yaml`), and prints the next
commands.

```bash
llm-localizator onboard ./myapp --targets pl --frozen zh,ar --approach hybrid --runtime-path web/js
```

`translate --sample layout[:N]` translates only a layout-check sample (short chrome
keys, the longest sources, a spread across areas), for frozen zh/ar:

```bash
llm-localizator translate myproject --locales zh,ar --sample layout:40
```

## `cycle` and `review-risk`

`cycle` runs the loop's read-only steps in order and writes one report to
`~/.llm_localize/data/<name>/reports/cycle-<ts>.md`; `--translate` also queues the
due strings through taskqueue (ADR-126). `review-risk` is the "read these first"
list on its own; `--format csv` gives a sheet with a `decision` column.

```bash
llm-localizator cycle myproject --locales pl
llm-localizator cycle myproject --translate
llm-localizator cycle myproject --repair     # retranslate keys failing V03/V04/V43/V46/V47
llm-localizator review-risk myproject --locale pl --limit 30 --format csv
```

## `report`

One shareable page on where localization stands (ADR-163), for people who don't run the
CLI and for CI to attach to a pull request. It is read-only and writes nothing except
`--out`.

```bash
llm-localizator report myapp                                  # Markdown to stdout
llm-localizator report myapp --format html --out l10n.html    # one self-contained page
llm-localizator report myapp --format json                    # the facts, for tooling
```

It contains coverage per locale ("has text", missing, out of date, not recorded), validation
errors and warnings in active locales, the `check-keys` result, the last hardcoded scan,
the riskiest keys to review, drafts waiting, cloud spend this month and recent runs.

The verdict:
- **NO-GO**: a key used in code is missing from the catalogue, or an active locale has
  validation errors. Exit 1, so CI can gate on it.
- **GO, with notes**: something a person should look at (warnings, risky keys, drafts,
  hardcoded hits, unrecorded values, untranslated strings).
- **GO**: none of the above.

| Flag | Purpose |
|------|---------|
| `--format md\|html\|json` | Output format (default `md`) |
| `--out FILE` | Write to a file instead of stdout |
| `--locales a,b` | Restrict (default: active targets) |
| `--review-limit N` | Risky keys listed per locale (default 5) |

`cycle` is the operator's loop: it can queue translations and writes its own log in the
data home. `report` is the read-only view to share.

## `normalize`

Apply the candidate normalizer to values already in the catalogue (ADR-161). New model output
already goes through it; values written earlier or by hand can still carry wrapper quotes
(`„Brakujące”`) or `...` where the source uses `…`.

```bash
llm-localizator normalize myapp                    # report what would change
llm-localizator normalize myapp --write            # apply, keeping each key's status
llm-localizator normalize myapp --steps case       # include an opt-in step
```

| Flag | Purpose |
|------|---------|
| `--locales a,b` | Restrict (default: active targets) |
| `--namespace NAME` | Restrict to a namespace (repeatable) |
| `--write` | Apply the fixes. Without it the command only reports. |
| `--steps LIST` | Default `quotes,icu_quotes,ellipsis,symbol,plural_fill`. Opt-in: `case`, `first_line` (they can undo a reviewer's deliberate choice). |
| `--format text\|json` | Output format |

Verified and locked keys are never changed. A value whose fix needs an opt-in step is
counted and left alone, not half-fixed. Each write records a history event
(`trigger=normalize`) and does not re-score the key.

## `set`

Write one translation through the same gate as a model run (normalizer plus the
hard checks), with ADR-19 provenance (ADR-122). Exit 1 when the gate rejects the
text; `--force` writes it anyway, and `validate` keeps reporting it.

```bash
llm-localizator set myproject --locale pl --key table.action.discard --text "Odrzuć {card}"
llm-localizator set myproject --locale pl --key app.title --text "Ustawienia" --by human
```

## `help` and `skill`

The packaged guides (ADR-121): `help human` for operators, `help agent` for AI
agents. `--path` prints the file path. `skill install` writes the task skills into
a project under `.claude/skills/` (`llm-localizator` for the rules, plus
`l10n-wire-strings`, `l10n-add-language`, `l10n-review`, `l10n-release`; ADR-162), and
`skill check` exits 1 when any of them is missing, edited or outdated. A skill file the
tool did not write is left alone unless `--force`. Run `skill install` only with the
project owner's agreement.

```bash
llm-localizator help agent
llm-localizator help human --path
llm-localizator skill install myproject
llm-localizator skill check myproject
```

## `runtime`

Manage the consumer's copy of the shipped browser runtime
([web-runtime.md](web-runtime.md), ADR-118). The path comes from
`[web] runtime_path` or `--path`.

```bash
llm-localizator runtime install myproject   # i18n.js, plus i18n.config.js if absent
llm-localizator runtime update myproject    # replace i18n.js with the shipped version
llm-localizator runtime check myproject     # exit 1: missing, edited locally, or outdated
```

`--force` replaces a file at the path that is not an llm-localizator runtime.
`--json` prints the state. Exit 2 when no runtime path is configured.

## `check-keys`

No-LLM wiring check for consumer CI. Scans `[scan] src_dirs` for
`i18n.t('…')` and `data-i18n*` keys.

```bash
llm-localizator check-keys myproject           # exit 1: missing keys or stale en-XX
llm-localizator check-keys myproject --strict  # also exit 1 on unused keys
llm-localizator check-keys myproject --no-qa --json
```

## Organisation-level sharing (`org`)

`[org] use = true` in the project config adds the organisation translation memory (read-only, after the project TM) and glossary (under the project glossary) to every run. `contribute = true` also appends human-approved text to the organisation TM (the `tm_write` mechanism of ADR-95). Both default off; `contribute` without `use` is an error. The shared locations come from an `org:` block in `~/.llm_localize/projects.yaml` (`tm:` directory, `glossary:` file), defaulting to `~/.llm_localize/org/tm` and `org/glossary.yaml`. `llm-localizator org` shows the current state and never writes. To reuse the shared memory elsewhere, point a project's `tm_dir` at it and run `tm-export`, or `glossary-export` for the glossary.

## `open-pr`

Sends uncommitted catalogue changes to your git host as a pull request. It is off until the project config says `[git_host] enabled = true` (optional: `remote = "origin"`, `base = "main"`, `branch_prefix = "l10n/"`, `kind = "github"`; GitHub through the `gh` CLI).

```bash
llm-localizator open-pr                       # plan: branch, files, title, body; writes nothing
llm-localizator open-pr open --yes           # branch, commit the catalogue files, push, gh pr create
llm-localizator open-pr status --pr-branch l10n/20261022-1030
```

`open` stages only the changed files under the catalogue directory, by path, and commits only those, so other work in the tree stays untouched. The commit message and PR body end with `Co-authored-by:` trailers for the people (recorded names) and models (model ids) on history events newer than the base branch's last commit; the addresses use the reserved `llm-localizator.invalid` domain because none is stored. `status` runs `gh pr view` once, when asked; nothing polls. The web UI reaches the same operation through `/api/ops/open-pr`.

## `screenshot-link`

Links an image from the project's `screenshots/` context folder to a key, so the editor can show the screen the string appears on. A link may carry a region, the rectangle to outline, as `x,y,w,h` fractions of the image (0 to 1), so it still fits when the image is resized.

```bash
llm-localizator screenshot-link link --file screenshots/home.png --namespace app --key title --region 0.1,0.2,0.3,0.1
llm-localizator screenshot-link list --namespace app --key title
llm-localizator screenshot-link unlink --link <id>
```

Files must exist under the context folder and be png, jpg or webp; anything else, and regions that leave the image, are refused. The same image, key and region replace each other. `ingest-visual` links a finding's `screenshot` to its key (no region) when the finding names a real `namespace` and `key`. Links live in `screenshot_links.json` under the state folder; they never change translations, state keys or prompts. Images are served only through the authenticated `/api/screenshot` route.

### Agent-sized parts (`--split auto`)

`agent-hardcoded --split auto [--budget-tokens 15000] [--max-hits 150] [--out-dir DIR]`
writes `part-<id>.md` files and `index.md` / `index.json` instead of one document
(ADR-105). Parts follow the directory hierarchy, never split a file unless it alone
exceeds the budget, and each carries its own routing note and `scan-decide`
cheat-sheet. Re-run after deciding hits to shrink the set. `--max-files` is an alias
of `--limit`.

### In-code ignore comments

`// l10n-ignore`, `l10n-ignore-next-line`, `l10n-ignore-start` / `l10n-ignore-end`
and `l10n-ignore-file` (first 10 lines) hide hits from `agent-hardcoded` in any
comment style (ADR-106). The engine only reads them.

Hints: `// l10n: key=pay.btn note="Pay button" max-length=20 dnt` (on the line or the
line above) and `// l10n: namespace=checkout` (on its own line, whole file) travel into
reports. `scan --lint-directives` reports stale or malformed directives (exit 1).
`[scan] directive_aliases = false` turns off the eslint/`noqa` aliases.

## projects

`llm-localizator projects [list|remove NAME|rename OLD NEW|prune] [--format json]` manages the
per-user registry only. `remove` never touches the project's config, catalogues or state;
`rename` refuses a name already in use; `prune` drops entries whose config file is gone.

`init --force` on an existing config now **merges**: only the catalogue format/path, source
locale and the options you pass (`--targets`, `--model`, `--domain`, `--provider`, `--name`)
change; comments and every other section are kept.

## places

`llm-localizator places [list|set|unset] [PLACE] [--policy auto|request|review|never]` — show or set the translation policy per namespace (or `NS:KEYGLOB`). See `[places]` in configuration.md.

### agent-backlog --split

`llm-localizator agent-backlog --split locale|namespace [--out-dir DIR] [--budget-tokens 15000]` writes one paste-ready file per locale or namespace (default `reports/backlog/`), chunked so no file exceeds the token budget, plus `backlog-index.json`. Stale part files from earlier runs are removed.
