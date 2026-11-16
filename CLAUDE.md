# CLAUDE.md — llm_localizator (public)

Public checkout guidance. Hard constraints live in [AGENTS.md](AGENTS.md); follow both.

## Layout

| Path | Contents |
|------|----------|
| `llm_localizator/core/` | Pure validation primitives (no I/O, no project knowledge) |
| `llm_localizator/core/locales/` | One module per language: all language knowledge |
| `llm_localizator/catalog/` | Message-file adapters and translation state |
| `llm_localizator/providers/` | LLM backends behind one interface |
| `llm_localizator/engines/` | Built-in engine profiles (`engine list`) |
| `llm_localizator/pipeline/` | Translate, documents and review engines |
| `llm_localizator/scan/` | Source scanners (usage backrefs, hardcoded strings) |
| `llm_localizator/projects/` | Config, registry and the task-queue bridge |
| `llm_localizator/ops/` | Shared operation layer (CLI and web parity) |
| `llm_localizator/cli/` | Command entry points |
| `llm_localizator/web/` | Local review UI and `/api/ops` endpoints |
| `tests/browser/` | Playwright UI tests (`-m browser`, extra `e2e`) |

## Working rules

- Run pytest through the project environment: `uv run pytest`. The default run is hermetic.
  Mark a test `@pytest.mark.slow` when it takes over about 1.5 s.
- Write code and regexes with file tools, not shell heredocs.
- Docs: user reference in [docs/](docs/), design decisions in [docs/decisions/](docs/decisions/README.md).
- Do not assume sibling checkouts or a shared inbox; this repository is standalone.
