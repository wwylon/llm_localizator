# Agent contract

The stable, machine-facing surface for coding agents, scripts and MCP clients. The guide
for agents (rules and recipes) is `llm-localizator help agent`. This page is the reference
it relies on.

## Three ways in, one result shape

| Surface | How | Result |
|---|---|---|
| CLI | `llm-localizator <command> … --format json` (or `--json` on `guide`, `approach`, `engine`, `doctor`, `check-keys`) | JSON on stdout, exit code as the process status |
| Web | `POST /api/ops/<command>` on the local server, with the `X-LLM-Token` header | JSON body |
| MCP | `llm-localizator mcp` tools (`localization_status`, `agent_backlog`, `check_keys`, `hardcoded_status`, `validate_catalogue`, …) | JSON text |

Every op returns the same envelope:

```json
{
  "schema_version": 1,
  "ok": true,
  "exit_code": 0,
  "command": "agent-backlog",
  "summary": "12 key(s) need work in pl",
  "lines": ["human-readable lines, same as the CLI prints"],
  "data": { "command-specific payload": "…" }
}
```

| Field | Stable? | Notes |
|---|---|---|
| `schema_version` | yes | Integer. Changes only when a top-level field is renamed, removed or changes meaning. A new field is not a version change. |
| `ok` | yes | `false` means the command did not do what was asked. Read `summary`. |
| `exit_code` | yes | Same numbers as the CLI ([exit-codes.md](exit-codes.md)). `77` = role not allowed. |
| `command` | yes | The CLI name (hyphenated). |
| `summary` | wording may change | One line for people. Do not parse it. |
| `lines` | wording may change | What the CLI prints. Do not parse it. |
| `data` | per command | The structured payload. Fields are added over time; existing fields keep their meaning within a `schema_version`. |

Branch on `ok`, `exit_code` and `data`. Never on `summary` or `lines`.

## Safe to run without asking

These only read, or write inside the engine's own data home:

`guide`, `status`, `validate`, `check-keys`, `agent-backlog`, `agent-hardcoded` (report only),
`explain-scan`, `approach` (without `--set`), `engine list|recommend|show`, `estimate-cost`,
`review-risk`, `glossary-learn` (without `write`), `doctor`, `help`.

## Ask the user first

These change the consumer repository, start processes, send text to a cloud service or
cost money:

| Command | Why it needs a yes |
|---|---|
| `init`, `runtime install`, `skill install`, `pseudo` | Write files into the consumer repo |
| `set`, `adopt` | Write a translation, or stamp state for existing values |
| `translate`, `improve`, `review`, `rescore`, `cycle --translate` | Run models: GPU time, or cloud spend under `[budget]` |
| `engine apply`, `engine fetch --write`, `approach --set` | Change what runs from then on |
| `hardcoded-hunt --serve` | Starts the app's dev server |
| `glossary-learn` with `write: true` | Edits the glossary |

Never apply a cloud engine or pick the `cloud` approach yourself. Never change
`[locales.models]`, roles or `judge_model` without a bakeoff winner (ADR-12).

## Roles on the web

`POST /api/ops/*` checks the caller's role against the matrix in
`llm_localizator/ops/permissions.py` (ADR-39). A refusal is `ok: false, exit_code: 77`.
Locale-scoped translators see and change only their locales.

## Versioning promise

- Envelope: `schema_version` above.
- Exit codes: the numbers in [exit-codes.md](exit-codes.md) do not change meaning.
- State key and hash format: frozen (ADR-7).
