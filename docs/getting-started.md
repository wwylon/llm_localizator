# Getting started

The short path: install the tool, pick an engine (Ollama for local models, or an API key for a cloud engine),
run `guide`, follow Next.

## 1. Install the tool

```bash
pip install llm_localizator
# or, from a source checkout:
# pip install -e .
```

The PyPI distribution is `llm_localizator` (`llm-localize` on PyPI is an unrelated project); the command is
`llm-localizator` and the import `llm_localizator`. Ollama is optional: validation, the scanner and the review UI need no model.

Optional extras: `[hyphens]` (soft hyphens), `[dev]` (pytest).

> **Windows.** Prefer `uv run …` or the project venv (`.\.venv\Scripts\python.exe -m llm_localizator.cli.main …`).
> The Store/`WindowsApps` `python` stub and MSYS `python` often have no pip/pytest.

For long GPU runs, install [tqdaemon](https://github.com/wwylon/tqdaemon) so `tq` is on PATH
(`uv pip install -e ../tqdaemon` in a sibling checkout, or `pip install tqdaemon`).
Without it, `translate` still runs in this terminal — see
[taskqueue-integration.md](taskqueue-integration.md).

## 2. Install Ollama (required for local translation)

Local translate/improve/review need [Ollama](https://ollama.com).

```bash
# After installing from https://ollama.com
ollama serve                 # leave running
ollama pull aya-expanse:8b   # or whatever [locales.models] in your .toml says
```

If a command says Ollama is not reachable: install from the link above, start
`ollama serve`, then pull the model. Cloud providers are opt-in
(`[privacy] allow_cloud`); they are not the default.

Check with:

```bash
llm-localizator doctor
llm-localizator guide --no-input
```

## 3. Let the tool tell you what to do next

```bash
cd your-project
llm-localizator guide
```

`guide` prints a checklist and the exact next command. On a terminal it can run
that step for you. It does not call a model unless you ask (`--smoke-test` or
the translate step). Use `--no-input` / `--json` for scripts and agents.

| Step | Done when | Command |
|------|-----------|---------|
| Prepare machine | Ollama answers (or a cloud provider is configured) | install [Ollama](https://ollama.com), `ollama serve` |
| Create project | `.llm-localize.toml` exists with source keys | `llm-localizator init` |
| Choose languages | at least one **active** target | `llm-localizator add-locale --locale pl` |
| Pick a model | model pulled and smoke test ok | `ollama pull <tag>`, `llm-localizator guide --smoke-test` |
| Translate | active locales have no missing/stale keys | `llm-localizator translate` (or `run-translate` without taskqueue) |
| Review and fix | `validate` has **0 errors** | `llm-localizator validate`, then `llm-localizator web` |
| Keep current | you know how to re-sync | `llm-localizator sync` when English changes |

**Active vs frozen.** `[locales] frozen` keeps a language in status/validate/UI
but skips it on default GPU sweeps. Thaw with
`llm-localizator translate --locales de`. See [configuration.md](configuration.md).

**Model pin.** Use the tag in your project's `[locales.models]`, not a doc
example. Example tags in this file are illustrative.

### Create the project (`init`)

```bash
llm-localizator init
# or non-interactive:
llm-localizator init --yes --targets pl,de --model aya-expanse:8b --domain "a booking app"
```

If detection fails:

```bash
llm-localizator init --format json-flat --path 'i18n/{locale}.json'
```

Formats: `json-nested`, `json-flat`, `yaml`, `po`, `arb`, `android-xml`
([catalog-adapters.md](catalog-adapters.md)).

### Translate

```bash
llm-localizator status
llm-localizator translate                 # prefers taskqueue when `tq` is on PATH
llm-localizator run-translate --dry-run   # preview work, no model calls
```

Without taskqueue, `translate` runs in this terminal (same as `run-translate`).
With taskqueue:

```bash
llm-localizator init --taskqueue   # once
tq sync
llm-localizator translate
tq status
```

Automated sync→translate may skip tiny backlogs (`[translate] min_keys`,
default 50). Operator `translate` always bypasses that floor.

### Check quality (no GPU)

```bash
llm-localizator status
llm-localizator validate          # exit 0 clean, 1 errors, 2 warnings only
llm-localizator validate --strict # warnings also fail
```

### Cursor / agent edits outside the pipeline

```bash
llm-localizator adopt --locales pl
llm-localizator agent-backlog --locales pl
# …edit catalogues…
llm-localizator adopt --locales pl
llm-localizator status
```

Details: [agents.md](agents.md), [cli.md](cli.md),
[adding_localization.md](adding_localization.md),
[consumer-localization-checklist.md](consumer-localization-checklist.md)
(static + en-XX + TQ).

## Dogfood this repo (self-localize)

From the `llm_localizator` checkout (config already present):

```bash
cd /path/to/llm_localizator
llm-localizator guide --no-input
llm-localizator status
llm-localizator translate --locales pl          # active locale
llm-localizator translate --locales de          # thaw a frozen locale
llm-localizator improve --locales pl
llm-localizator validate
llm-localizator web
```

UI chrome catalogues live at `llm_localizator/web/locales/{locale}.json`.
Targets today: `pl` (active), `de`/`ar` (frozen until `--locales`).

## CI

```yaml
- run: pip install llm_localizator
- run: llm-localizator validate --format github --locale pl
- run: llm-localizator check-keys                # used keys exist, en-XX current
- run: llm-localizator runtime check             # only with [web] runtime_path
```

## Next

- [consumer-localization-checklist.md](consumer-localization-checklist.md) — full consumer path
- [operator guide](../llm_localizator/help/human.md) — decisions and reading results (`llm-localizator help human`)
- [agent guide](../llm_localizator/help/agent.md) — rules for coding agents (`llm-localizator help agent`)
- [cli.md](cli.md) — every command
- [taskqueue-integration.md](taskqueue-integration.md) — sync → translate → review → improve
- [configuration.md](configuration.md) — full TOML reference
