# Contributing

## Setup

```text
git clone https://github.com/wwylon/llm_localizator.git
cd llm_localizator
uv sync --extra dev
uv run llm-localizator doctor
```

## Tests

The default run is hermetic: it needs no Ollama, no GPU, no network and no API key.

```text
uv run pytest -q
# faster, in parallel (needs pytest-xdist):
uv run pytest -q -n auto --dist loadfile -m "not slow and not ollama and not live_bridge and not browser"
uvx ruff check llm_localizator
```

Browser tests need the `e2e` extra and Chromium (`uv run pytest -m browser`). Tests marked
`ollama` need a running Ollama server with the model pulled.

## Ground rules

- Every operator-facing command lives in `llm_localizator/ops/` first; the CLI and the web UI
  both call it.
- `llm_localizator/core/` stays pure: no I/O, no network, no project knowledge.
- Do not change default models without a bakeoff report
  ([docs/model-evaluation.md](docs/model-evaluation.md)).
- Pin false positives and false negatives of the scanner with a test under `tests/scan/`.

## Pull requests

- Open PRs against the public repository and link an issue when fixing a bug. For runtime
  problems include the output of `llm-localizator doctor --json`.
- Maintainers may replay accepted changes through an internal mirror, so your commits can
  appear rewritten in the next public export. Attribution is kept in the CHANGELOG or the PR
  thread where practical.

## Security

See [SECURITY.md](SECURITY.md). Do not report vulnerabilities in public issues.
