# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

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
