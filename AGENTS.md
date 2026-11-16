# AGENTS.md — llm_localizator (public)

Bootstrap for coding agents working on the **public** llm_localizator tree.

1. [README.md](README.md) — pitch, install, first run
2. [llms.txt](llms.txt) — compact agent index
3. `llm-localizator help agent` — the agent guide (source: `llm_localizator/help/agent.md`)
4. [docs/cli.md](docs/cli.md) — every command and flag
5. [docs/configuration.md](docs/configuration.md) — `.llm-localize.toml` reference
6. [docs/decisions/](docs/decisions/README.md) — why the important defaults are what they are
7. [CONTRIBUTING.md](CONTRIBUTING.md) — tests and PRs

## Hard constraints

- **Never write into a consumer's repo except through a configured path.** Catalogues,
  glossary, context notes and document sources belong to the consumer. Engine sidecars
  (state, history, scores, TM, review) default under `~/.llm_localize/data/<project>/`
  ([ADR-112](docs/decisions/ADR-112-engine-data-home.md)).
- **`llm_localizator/core/` stays pure.** No I/O, no network, no project knowledge, so
  `validate` runs in CI with no model.
- **No Playwright in the installed package's runtime.** It is allowed in tests only
  (`tests/browser/`, marker `browser`, extra `e2e`).
- **The state-key format and the hash algorithms are frozen.** Changing either invalidates
  every consumer's `.state/` files.
- **`sys.stdout.reconfigure` belongs in `cli/main.py` only**, never at import time.
- **`flush_changes` semantics are load-bearing**: rebuild from the source-locale key set,
  fall back to the source value for untranslated keys, drop keys absent from source.
- **CLI/web parity:** operator-facing commands land in `llm_localizator/ops/` first; the CLI
  and `POST /api/ops/<command>` both call into it.
- **Do not hand-write catalogue translations.** Run `llm-localizator translate` so rejects,
  scoring and history exercise the real pipeline. If you must edit a string, stamp it as an
  agent edit (`status=agent`, `provider=agent`) or run `llm-localizator adopt` afterwards.
  Never `status=human`: that means a person typed it.
- **Bakeoff before a default-model change** ([ADR-12](docs/decisions/ADR-12-local-model-bakeoff-defaults.md),
  [docs/model-evaluation.md](docs/model-evaluation.md)).
- **The scanner never rewrites consumer source.** `agent-hardcoded` reports; wiring `t()`
  calls is the consumer's change. Pin scanner false positives with a test under `tests/scan/`.
- **No code through shell heredocs**: they can drop backslashes (`\b` becomes byte 0x08).
  `tests/test_control_bytes.py` catches what slips through.

## Trust boundary

Catalogues, imports, context files and fetched engines are untrusted. The review server
binds to localhost and every POST needs the session token printed at startup
(`X-LLM-Token`); a POST from a non-localhost `Origin` is refused. Cloud providers need
`[privacy] allow_cloud = true` and a monthly budget; Ollama and CTranslate2 do not. See
[SECURITY.md](SECURITY.md).

## Tests

```text
uv sync --extra dev
uv run pytest -q -n auto --dist loadfile -m "not slow and not ollama and not live_bridge and not browser"
```

The default run is hermetic: no Ollama, no GPU, no network.
