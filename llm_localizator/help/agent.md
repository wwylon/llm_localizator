# llm-localizator — guide for AI agents

You are an AI agent working on an app that uses llm-localizator, a local-LLM
localisation engine. This file is the single source of rules and recipes for
agents. The human operator's guide is `llm-localizator help human`.

Print this file any time with `llm-localizator help agent`. MCP clients can read it as
the resource `llm-localizator://help/agent`. The MCP tools `check_keys`,
`hardcoded_status`, `list_approaches`, `localization_status`, `validate_catalogue`
and `agent_backlog` wrap the commands below.

**Terms used in this guide:**
- **Consumer repository**: the app being localized, not the llm-localizator engine.
- **`<project>`**: the project's registered name, or omit it when you run from
  inside the consumer repo. Its data lives under `~/.llm_localize/data/<project>/`.
- **Source catalogue**: the file with the original strings, usually `en.json`. Its
  path is `[catalog] path` in `.llm-localize.toml`, and the source language is
  `[project] source_locale`.
- **en-XX**: the QA marker locale. Every catalogued string is shown as `XXXX`, so
  readable English left on screen is hardcoded. It is **stale** when English
  strings were added or changed after it was generated.

## 1. Hard rules

1. **Ask before changing a consumer repository.** Get the user's yes first, every
   time, before you:
   - edit its source, catalogues, `.llm-localize.toml` or `i18n.config.js`;
   - run `llm-localizator init`, `runtime install`, `skill install` or `pseudo` (it
     writes `en-XX.json`);
   - run `hardcoded-hunt --serve`, which starts the app's server.

   Reading files, scanning (`agent-hardcoded`), `check-keys`, `validate`, `guide`,
   `approach` without `--set` and `engine list|recommend|show` are fine without asking.
   `engine apply` and `engine fetch --write` change what runs: ask first, and never apply
   a cloud engine on your own (it sends text out and costs money).
2. **Show the options before translating.** If `llm-localizator approach <project>` says
   no approach is chosen, show the user the five options and the recommendation it
   prints, and wait for their choice (section 2). Wiring UI text does not depend on
   the approach; translating does. Never pick `cloud` yourself: it costs money.
3. **Never mark your own edits `status=human`.** Agent edits are stamped `agent`
   (ADR-19, ADR-48). `human` means a person typed or saved it.
4. **Never hand-edit a translation without a stamp.** For one string use
   `llm-localizator set` (section 6). After editing catalogue files in bulk, run
   `llm-localizator adopt <project>` so state, scores and history know about the change.
5. **Never put a QA marker locale (`en-XX`, `en-XA`) in `[locales] targets`.** It is
   URL-only: `?lang=en-XX` or `/en-XX/…`.
6. **Never change `[locales.models]`, roles or `judge_model`** without a fresh
   bakeoff Winner (ADR-12, `llm-localizator bakeoff`).
7. **Long model work goes through taskqueue.** Use `llm-localizator translate` (it
   queues), never a background shell running `run-translate` for a full sweep.
8. **Never commit, push or merge** in a consumer repo unless the user asked.
9. **Propose glossary and context changes; people confirm them.** Show
   `glossary-learn` and `context-propose` output to the user. Do not edit the
   glossary or write context notes before they say yes.

## 2. Start a project, choose the approach

1. If the repo has no `.llm-localize.toml`, ask the user, then run
   `llm-localizator init`. It detects the catalogues, asks for the target languages,
   and asks for the approach.
2. Run `llm-localizator approach <project>`. It lists the options with a
   recommendation for this machine. After the user chooses, run
   `llm-localizator approach <project> --set <id>`, which records it as
   `[translate] approach`.
3. Run `llm-localizator guide <project>` at any time for the next step; it adapts to
   the approach.

<!-- generated:approaches -->
| id | Who writes the words | Needs | Stamp written |
|---|---|---|---|
| `local` | Ollama models on this machine, run through taskqueue | Ollama (a GPU makes it practical), taskqueue | machine |
| `cloud` | Anthropic, OpenAI or DeepL under [budget] monthly_usd (ADR-35) | an API key in the environment and a [budget] ceiling | machine |
| `agent` | the AI agent in your editor fills the catalogues | an agent session (Claude Code or similar) | agent |
| `human` | people, through an exported file or the web editor | translators; xlsx / xliff / csv round trip or `llm-localizator web` | human |
| `hybrid` | a draft from local, cloud or agent, then reviewers fix what is risky | one of the above plus a reviewer | machine/agent, then human |
<!-- /generated:approaches -->

With `agent`, you translate:
1. `llm-localizator agent-backlog <project>` prints the keys to fill, with context and
   rules.
2. Write the translations into the catalogue files. Ask first (rule 1) if you have
   not been asked to translate.
3. Run `llm-localizator adopt <project>`, then `llm-localizator validate <project>`.

The draft gate in section 5 applies to model runs (`translate`, `improve`). Your own
writes are checked by `validate`.

## 3. Wiring UI text (the app side)

**Key names.** Use `area.element.purpose` in lowercase with dots, e.g.
`library.filter.placeholder` or `files.delete.done`. Keep one area per page or
component. Never reuse a key for a different meaning.

**Seed English first.** Add the key and its English text to the source catalogue,
then reference it from code.

**In code**, use a string literal as the key. Pass values as an object:

```js
i18n.t('settings.save.button')
i18n.t('files.delete.done', { n: count })   // en.json: "Deleted {n, plural, one {# file} other {# files}}"
```

A computed key cannot be checked. If you must build one, keep a literal prefix
(`` i18n.t(`kind.${k}`) `` or `i18n.t('kind.' + k)`) so the keys under it are not
reported unused.

**In markup**, put the key on the element and keep the English text in it:
`<button data-i18n="settings.save.button">Save changes</button>`.
- User-visible attributes have their own forms: `data-i18n-title`,
  `data-i18n-placeholder`, `data-i18n-aria-label`, `data-i18n-alt`.
- Markup keys take no values. Text with numbers or names is set from code with
  `i18n.t(key, {…})`.
- Put the key on the innermost element. An element that has child elements is
  never rewritten.
- After inserting markup that carries `data-i18n*`, call `i18n.applyDOM(node)`.
  Alternatively, ask the user to set `observe: true` in `i18n.config.js`.

**ICU for counts and choices.** Never build `n + ' files'` or pick between two keys
by count. Use `plural` (with `#` for the number), `select` for kind or gender, and
`selectordinal` for 1st / 2nd.

**Whole sentences.** Use one key per sentence or label, with `{placeholders}` for
variable parts. Never concatenate translated fragments: word order differs between
languages.

**What stays literal.** This is the one list; other docs link here:
- brand and product names;
- code identifiers, CLI commands, file names, URLs;
- units shown as symbols (px, MB, ms) and pure numbers;
- user data and server data (titles, names, ids);
- log lines and developer-only debug text;
- language self-names in a language picker (English, Polski, 中文).

Anything else a user can see needs a key.

**Plain JS apps without an i18n library** use the shipped runtime. With the user's
yes:
1. add to `.llm-localize.toml`:
   ```toml
   [web]
   runtime_path = "web/static/js"   # a folder (i18n.js goes inside) or a .js path
   ```
2. run `llm-localizator runtime install <project>`. It writes `i18n.js`, plus
   `i18n.config.js` if that is missing;
3. load `i18n.config.js`, then `i18n.js`, before the app's own scripts.

Apps that already use an i18n library (next-intl, i18next, gettext…) keep it.

## 4. The hardcoded-text loop

Exit code 0 means clean, 1 means fix something, 2 means a configuration problem.

```bash
llm-localizator agent-hardcoded <project> --status   # what is left and the next steps (JSON)
llm-localizator agent-hardcoded <project>            # prompt listing hardcoded strings
# wire them (section 3), seeding the source catalogue
llm-localizator check-keys <project>                 # 1 = a used key is missing, or en-XX stale
llm-localizator hardcoded-hunt <project> --serve     # with consent: en-XX crawl of the running app
llm-localizator validate <project>                   # catalogue checks
```

**Scanner results.** Each hit has a confidence: high, medium or low. high and
medium are almost always UI copy. To dismiss a hit that is not copy, record why:
`llm-localizator scan-decide <project> ignore --ids <id> --note "why"`.

**The en-XX crawl** needs a `[qa]` block in `.llm-localize.toml` that says where
the app runs and how a page switches language. It writes its report to
`~/.llm_localize/data/<project>/qa/<timestamp>/`. If the app has no `en-XX.json`,
the crawl generates the marker catalogue in the browser. `pseudo` is only needed
for apps that ship the file themselves.

**Reading the crawl report:**
- `leftovers.json`: English still visible under en-XX. Each row has `literal`:
  - `true` with `file` and `line`: a literal in the source; wire it;
  - `false`: the text appears nowhere in the source.
- `dynamic_text.json`: the `literal: false` rows. They come from the server, an
  API or runtime string building. Find the producer (an API response, a server
  template) instead of looking for a JS literal. User data stays as it is.
- `layout.json` and the `ar/`, `zh/` screenshots: wrong `dir`, clipped or
  off-screen text. Look at the screenshots too; bidi problems are not measured.

**Done** when all of these hold:
- `check-keys` exits 0;
- `agent-hardcoded` reports no high or medium hits left undecided (wired, or
  ignored with a reason);
- the en-XX crawl shows only items from the what-stays-literal list. If the user
  declined the crawl, say that this check was not done;
- `validate` has no errors in the target locales.

## 5. Translation checks you will see

When a check fails, use the command in the last column. If a key still fails after
`cycle --repair --follow` (two attempts), fix it with `set`, or propose a glossary
entry or a context note (`context-note`) to the user.

<!-- generated:checks -->
| Code | Severity | Meaning | Fix with |
|---|---|---|---|
| V01 | error | key missing in a target locale | `translate`, or `agent-backlog` then `set` |
| V02 | error | placeholder set differs from the source | `set` with every `{placeholder}` kept |
| V03 | error | plural categories missing for the locale | `cycle --repair`, or `set` the full plural |
| V04 | error | forbidden glossary variant, or a whole label lacks its approved word | `set` the approved term |
| V13 | warning | approved glossary term absent (warning) | `set` if the term belongs; else leave it |
| V27 | error | HTML tag structure differs from the source | `set` with the source tags |
| V43 | error | translation wrapped in quotes | `cycle --repair`, or `set` without the quotes |
| V46 | error | leaked prompt text: a long answer to a short source | `cycle --repair`; `set` a label |
| V47 | error | ICU structure changed (`select` became `plural`, a branch lost) | `cycle --repair`; `set` the source structure |
| V48 | warning | one glossary term rendered several ways | `set` the approved rendering everywhere |
| V49 | error | project description leaked into the output | `cycle --repair` |
| V50 | error | invented markup, or text moved outside an ICU message | `set` the plain text |
| V51 | error | leading symbol dropped or spelled out | `set` with the symbol |
<!-- /generated:checks -->

In model runs, a translation scoring under `[quality] write_floor`, or a rerun that
is not better than the current text, is kept as a **draft** instead of being
written. List drafts with `llm-localizator draft list <project>`. Only a human accepts
them.

## 6. Fixing one translation

Use `llm-localizator set`. It runs the same gate as a model run (normalizer, then the
hard checks in section 5), writes the catalogue, and stamps the edit:

```bash
llm-localizator set <project> --locale pl --key table.action.discard --text "Odrzuć {card}"
```

- `--by agent` is the default, stamped `agent`. Use `--by human` only when a person
  dictated the text to you.
- `--model <id>` records which agent or model wrote it.
- A text the gate rejects (a lost placeholder, a changed ICU structure) is refused.
  `--force` writes it anyway, and `validate` keeps reporting it. Do not use `--force`
  without the user's yes.
- It changes a consumer catalogue, so rule 1 applies: ask first unless the user
  asked you to fix translations.

Check the result with `llm-localizator validate <project>`.

## 7. Where things are

- Config: `.llm-localize.toml` in the consumer repo. The reference is
  `docs/configuration.md` in the llm-localizator repository.
- Reports, state, scores and history live under `~/.llm_localize/data/<project>/`,
  never in the consumer repo.
- Runtime details are in `docs/web-runtime.md` in the llm-localizator repository;
  every option of a command is in `llm-localizator <command> --help`.

### All commands

<!-- generated:commands -->
| Command | What it does |
|---|---|
| `acknowledge-flush` | Delete an interrupted flush journal without writing catalogues |
| `add-locale` | Add a target locale to the project config (no LLM) |
| `adopt` | Stamp catalogue strings missing from state as agent provenance (no LLM) |
| `agent-backlog` | List keys an AI agent should still translate (prompt or JSON, no LLM) |
| `agent-hardcoded` | Report hardcoded product strings for an agent to fix in source (writes nothing) |
| `analytics` | Summarize run speed from _runs/ manifests and verify/score lag |
| `apply` | Apply catalogue additions from scan (writes catalogue files, not source files) |
| `apply-near` | Copy one edited translation onto similar keys you name (preview unless --confirm) |
| `approach` | Show how this project can be localized (local, cloud, agent, human, hybrid) |
| `bakeoff` | Compare local models on your own strings (evidence for ADR-12) |
| `bulk-clear` | Send stale or old machine translations back to the backlog (human keys are kept) |
| `check` | CI gate: exit 1 when translations are stale or incomplete (no LLM) |
| `check-keys` | Keys used in source vs the source catalogue, unused keys, stale en-XX (no LLM) |
| `concordance` | Search the translation memory (no LLM) |
| `context-note` | Write one per-key translator note |
| `context-propose` | Suggest translator notes for short placeholder frames (read-only) |
| `cycle` | One pass: check keys, validate, status (queue translate), review risk, hardcoded; one report |
| `discover` | Propose text collections from locale-named directories (writes nothing) |
| `discuss` | Per-key discussion threads with @mentions and a resolved state |
| `doctor` | Check install, config, Ollama, and whether the web UI is up to date |
| `documents` | Submit a Markdown document translation job to taskqueue |
| `draft` | Keep model suggestions as drafts until a person accepts them (nothing is written by create) |
| `engine` | Pick the engine (provider + model for every pipeline role): Claude, DeepSeek, OpenAI or local by VRAM |
| `estimate-cost` | Maximum USD to localize due strings with a cloud provider (no API call) |
| `explain-scan` | Why the hardcoded-string scanner did or did not report FILE:LINE (skip rules, filters, sink, tier) |
| `export` | Export catalogue for translators (CSV, XLIFF, JSON or xlsx) |
| `find-replace` | Find and replace text in one locale's translations (preview unless --confirm) |
| `flag-source` | Flag an English string for source review |
| `glossary-export` | Write the glossary as CSV or TBX |
| `glossary-import` | Merge a CSV or TBX glossary |
| `glossary-learn` | Propose glossary terms from repeated manual corrections (read-only) |
| `glossary-propose` | Print candidate glossary terms (writes nothing) |
| `guide` | Show what to do next, step by step, from an empty folder to translations |
| `hard-keys` | Cross-locale score report — source-hard vs locale-hard keys (no LLM) |
| `hardcoded-hunt` | Pseudo en-XX, crawl leftovers (dogfood presets or [qa]), refresh agent-hardcoded |
| `help` | Print the guide for people (human) or for AI agents (agent) |
| `impact` | List locales stale because the source hash changed |
| `import` | Import edited CSV, JSON, XLIFF or xlsx back into catalogues |
| `import-review` | Apply the decision column of a review-risk CSV through set --by human |
| `improve` | Submit overnight improve of low-score / flagged keys |
| `ingest-visual` | Load consumer visual findings JSONL into the review queue (no LLM) |
| `init` | Detect the catalogue layout and write a config file |
| `localize-project` | One report for the localization checklist: scan, gaps, cost, next commands (read-only) |
| `mcp` | stdio MCP server for agents (optional mcp extra) |
| `metrics` | Edit rate, cycle time and coverage trend from history |
| `migrate-state` | Recompute derived state fields after a signature-format change (no LLM) |
| `onboard` | Set up a project in one step: init, approach, frozen locales, runtime path, tq check |
| `open-pr` | Plan, open or check a pull request for changed catalogue files |
| `org` | Show whether this project uses the organisation-level TM and glossary |
| `patch` | Generate a structured changeset (hardcoded strings + catalogue gaps). Writes nothing. |
| `places` | List or set the translation policy per text place |
| `projects` | List, rename, remove or prune registered projects |
| `pseudo` | Write a throwaway expanded locale (no state) |
| `quality` | One-shot quality report for a project or for message files (no registration) |
| `queue-engine` | Rewrite the project's existing taskqueue blueprints for one engine (never creates a blueprint) |
| `release-diff` | Diff the current source against a release snapshot |
| `release-freeze` | Snapshot source hashes for a named release |
| `rename-placeholder` | Rename {old} to {new} in the English text and every translation (no re-translation) |
| `rescore` | Submit a quality re-score job to taskqueue |
| `review` | Submit an LLM review pass to taskqueue |
| `review-risk` | Rank a locale's translations by how much a person should read them (read-only) |
| `run-agent-hardcoded` | Execute the hardcoded-string model pass (invoked by taskqueue) |
| `run-bakeoff` | Execute bakeoff (invoked by taskqueue) |
| `run-documents` | Execute a document translation job (invoked by taskqueue) |
| `run-improve` | Execute improve pass (invoked by taskqueue) |
| `run-rescore` | Execute rescore (invoked by taskqueue) |
| `run-review` | Execute an LLM review pass (invoked by taskqueue) |
| `run-sync` | Execute gather/sync (invoked by taskqueue or CI) |
| `run-translate` | Execute a translation job (invoked by taskqueue) |
| `runtime` | Install, update or check the shipped browser i18n runtime in the consumer |
| `scan` | Find t() call sites and hardcoded strings (no LLM) |
| `scan-decide` | Accept or ignore scan results; what apply then writes follows [apply] mode |
| `screenshot-link` | Attach screenshots to keys, with optional highlighted regions |
| `server-copy` | People-facing English in Python server code ([scan] server_dirs) |
| `set` | Write one translation through the candidate gate, with provenance stamps |
| `skill` | Install or check the agent guide as a Claude skill in the project |
| `source-diff` | Show what changed in one source string and which words need translating |
| `source-review-queue` | List English strings flagged for review |
| `status` | Show per-locale translation coverage (no LLM) |
| `suggest` | Show one model translation for a key without saving it |
| `sync` | Scan + detect missing/stale (queue on_complete chains translate) |
| `task` | Work packages of keys with one assignee per locale and a due date |
| `term-report` | Glossary gaps and terms rendered inconsistently across keys (read-only) |
| `tm-export` | Write one locale's translation memory as TMX |
| `tm-import` | Merge a TMX file into the translation memory |
| `translate` | Submit a translation job to taskqueue and exit |
| `validate` | Check catalogues for ICU, plural, glossary, and staleness problems (no LLM) |
| `verify` | Run the verification workflow on a disposable copy of a project |
| `watch` | Foreground: re-run sync when a source catalogue file changes (not a daemon) |
| `web` | Browse and edit translations in a local web UI |
| `workflow` | Run a named workflow script (route, improve, review) |
<!-- /generated:commands -->
