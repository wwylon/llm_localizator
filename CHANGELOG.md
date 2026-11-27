# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-11-27

### Added

- `report`: one read-only localization page (Markdown, self-contained HTML or JSON) that gathers status, validate, check-keys, the hardcoded scan, review risk, drafts, budget and recent runs, with a verdict: NO-GO (exit 1), GO with notes, or GO. Also `POST /api/ops/report`, which never writes a file.
- `normalize`: applies the output normalizer (wrapper quotes, `...` versus `…`) to values written earlier or by hand. It reports by default; `--write` applies, records history and keeps each key's status. Also `POST /api/ops/normalize`.
- `skill install` writes five short task skills for consumer repos (core rules, wiring strings, adding a language, review, release) instead of one long guide.
- Every operation result carries `schema_version`; [docs/agent-contract.md](docs/agent-contract.md) lists the stable fields, safe versus ask-first commands and web role refusals (exit 77).
- `review-risk`, `glossary-learn` and `cycle` are available as web operations.
- Translation issues in a rubric style (LQS), the Hy-MT3 engine, and a layout-overlap check; measured pixel budgets (V29) and an agent checklist.
- Docs: concepts, troubleshooting, adding to an existing project, cost and budget, exit codes.

### Changed

- `translate` and related commands run locally when taskqueue is not installed, instead of failing.
- `agent-backlog` covers active target locales by default; name a frozen locale in `--locales` to include it.
- `run_translation`, improve and blueprint generation split into small named steps; faster translate and improve runs through targeted cache invalidation.
- Web export takes the same options as the CLI (`xliff_version`, `bom`, `approved_only`).
- Hardcoded-string scanner v71; ruff covers tests and scripts; test coverage gate at 80%.

### Fixed

- Scoring fails a chat answer about the translation ("The translation of X is Y") and leaked prompt text, which back-translation used to score 1.0.
- A partly failed cloud batch keeps and bills the finished results and retries only the failed keys.
- Web: link schemes in the editor are allow-listed (XSS); path-like locales are rejected; `/api/bundle` serves only known locales and namespaces; a stale session token is refreshed once; streamed output is flushed at the end.
- Web UI keys that were missing from the catalogue, and leaked prompt text and stray quotes in the ar/de UI translations.
- `report` treats a stale pseudo-locale as a note instead of NO-GO.
- Improve uses the improve model's style notes, not the translate model's.

## [0.2.1] - 2026-11-22

### Fixed

- Public docs no longer point at private `experiments/quality_bakeoff/` paths or
  internal tooling; model evaluation uses `llm-localizator bakeoff` only (#8, #9).
- Homepage and `engine fetch` default URL use GitHub Pages
  (`https://wwylon.github.io/llm_localizator/`) until `llm-localizator.dev` DNS
  exists (#7).
- GitHub Actions: `checkout`/`setup-python` v7; Pages deploy actions v5/v6 (#1–#5).
- Cloud providers treat an explicit empty API key as missing instead of falling
  back to the environment (hermetic tests no longer pick up a host key).

### Added

- `translate` and `run-translate` take `--only-missing` (only keys whose target value is absent or empty) and `--keys-file PATH` (keys from a file or stdin, merged with `--keys`).
- API keys are read from `LLM_LOCALIZATOR_ANTHROPIC_API_KEY`, `LLM_LOCALIZATOR_OPENAI_API_KEY`, `LLM_LOCALIZATOR_DEEPSEEK_API_KEY` and `LLM_LOCALIZATOR_DEEPL_AUTH_KEY` first, then the vendor variables as before, so this tool can have its own key. A provider table can name its variable with `api_key_env`.
- Provider kind `openai_compat` for any service with an OpenAI-compatible Chat Completions endpoint (needs `url`, a model and a `[budget.rates]` price).
- `[scan.surfaces.<name>]` (`paths`, `mode = fix | report | ignore`) and `scan --surface a,b`: name the parts of a project and fail `--strict` only on the ones to fix. The text report shows counts by confidence and surface, and says when it cut the list at 100.
- `localize-project`: one read-only report for the localization checklist (scan, missing keys, cost, next commands); `--submit` enqueues `translate --only-missing`.
- `engine use ID` as an alias for `engine apply ID`.
- `doctor` names the variable that supplies a cloud key (never its value) and reports missing packages instead of a stack trace.
- Cloud scoring (back-translation) is faster with the same scores: a cloud scorer sends `[translate] cloud_batch_size` keys per request (override: `[quality] bt_cloud_batch_size`) and up to `[quality] bt_workers` (default 4) requests at once, with progress lines. With several locales, back-translation of a finished locale starts while the next one is still translating; scoring and score writes stay in the final phase. A local scorer is unchanged. The score stays an independent pass; the translator does not score its own output.
- Deferred scoring (cloud runs) now judges one- and two-word keys with the scoring model, as the inline path already did (`[quality] judge_risky`, default on). Before, a bare back-translation gave "Wynik pobierania" for "Download result" a 1.0. The judge calls run `bt_workers` at a time.
- `translate --sync` (also `run-translate`): cloud locales use one synchronous request per batch instead of Message Batches. Full price, no wait; for small or urgent runs.
- Cloud batch runs print progress on stderr: a note that Message Batches are asynchronous, then batch id, state, requests done and elapsed time every 30 s (`batch_progress_s` option).
- `status` counts keys that have text but no state record apart from missing ones.

### Changed

- A broad `translate` or `sync` no longer treats an existing translation that has no state record as work, so a project that already had catalogues is not overwritten. `--force` or naming the key still retranslates it; a "left as is" line reports the count.

- Hardcoded-string scanner v58 to v69: Python desktop GUI text (Tk, Qt, Flet, Slicer-style Qt modules, messages and formatted f-strings), Java widgets, enum labels, status and output-pane helpers and display-name returns, Dart text constants, Jinja macro captions, mkdocs and JSON screen files, AppStream store text. Regex patterns and `{"en": {...}, "fa": {...}}` language catalogues are no longer reported. On a fresh held-out round the last measured figures were recall 0.61 and precision 0.77 (pool L, v67).
- Published scanner numbers now come from the seven latest held-out rounds (pools F to L, 136 projects, scanner v57 to v67): macro precision 0.74, macro recall 0.59. They replace the earlier 12-project round (0.91 / 0.34).
- Shipped files no longer reference private internal tooling.
- ERB (Rails views) joins the supported scanner tier (held-out rounds A to I: 5 projects at the bar, 2 below). Scanner v59.
- Python desktop GUIs (Tk, Qt, wx, Kivy, Toga): widget captions, menu entries, window titles and tooltips are found. Dart text constants are found. One file that breaks the scanner is listed as skipped instead of stopping the scan (v58).
- `doctor` reports an unreachable Ollama as a warning (exit 0); `doctor --strict` makes it fail.
- `check --format github` prints one workflow error annotation per problem, like `validate --format github`.
- Web UI: a skip link, a live region that announces status messages, column scopes on table headers and reduced-motion support. Cross-origin reads need `overlay_edit`, the login routes or the translator overlay lookups. The session token file is limited to its owner on Windows too.
- Development: `scripts/test_lane.py quick|full`, a mypy error-count ratchet, `pip-audit`, a Makefile and CI on push and pull requests.
- The web server sends security headers (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, a limited `Content-Security-Policy`) and caps ordinary POST bodies at 4 MB; imports and uploads keep 32 MB. Unexpected errors are logged.
- The project is renamed `llm_localizator` (ADR-157): distribution, import package, command and brand. The old
  command `llm-localize`, the config filename `.llm-localize.toml`, `~/.llm_localize` and `LLM_LOCALIZE_*` keep working.

## [0.2.0] - 2026-11-14

First public release. On PyPI the distribution is `llmlocalize`. The import
package is `llm_localize` and the command is `llm-localize`. This project is not
related to the `llm-localize` package on PyPI.

### Added

- **Engines.** `llm-localize engine list|recommend|show|apply|fetch` switches the
  provider and model of every pipeline role (translate, back-translation score,
  judge, improve) in one step. Built-in engines: Claude Haiku 5.5 (no GPU, about
  $0.12 per 2,300-key locale sweep), DeepSeek, OpenAI, local Ollama profiles for
  4, 8 and 16 GB GPUs, and a hybrid of local translation with Haiku scoring.
  `recommend` picks one from your API keys and GPU size, and `fetch` downloads
  hash-checked engine files.
- **Claude Haiku 5.5 default for cloud projects**, with a calibrated Haiku
  scorer. Cloud providers stay off until you set `[privacy] allow_cloud` and a
  monthly budget.
- **Hardcoded-string scanner.** `agent-hardcoded` finds UI text that never went
  through a translation call. It reads 40 languages and file formats, eight of
  them at the "supported" tier, and reports each hit at high, medium or low
  confidence. It was measured on held-out
  open-source projects that were never used to tune it. Tiers, per-language
  support and known gaps are in [docs/scanners.md](docs/scanners.md).
  `explain-scan FILE:LINE` says why a line was or was not reported.
- `en-XX` pseudo-locale leftover hunt and a config-driven `[qa]` crawl.
- Review web UI with roles, per-locale assignments, tasks, approve-only
  publishing, translation memory and glossary editing.
- `check-keys` for CI, `agent-backlog` for coding agents, and an MCP server
  (`llmlocalize[mcp]` extra).
- A shipped browser runtime for plain JS apps (`llm-localize runtime install`).

### Changed

- The PyPI distribution name is `llmlocalize` (it was `llm-localize` in source
  checkouts). `pip install` hints in errors and docs use the new name.
