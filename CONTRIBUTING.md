# Contributing

## Setup

```text
git clone https://github.com/wwylon/llm_localizator.git
cd llm_localizator
uv sync --extra dev
uv run llm-localizator doctor
```

On Windows prefer `uv run …` or `.\.venv\Scripts\python.exe …`. The Store/`WindowsApps`
`python` stub and MSYS `python` often lack pytest and the editable install.

### Optional: taskqueue (`tq`)

Hermetic tests do **not** need `tq`. For real queue submits (`translate` without
`--inline`, web **Submit to taskqueue**), install [tqdaemon](https://github.com/wwylon/tqdaemon)
so `tq` is on PATH (doctor warns when it is missing):

```text
# sibling checkout (house layout):
uv pip install --python .venv/Scripts/python.exe -e ../tqdaemon
# or from PyPI when published:
# pip install tqdaemon
uv run tq --help
uv run llm-localizator doctor   # taskqueue check should be ok
```

Without `tq`, operator commands run in-process. Explicit web **Run locally**
(`inline=true`) still needs `confirm=true`. Prefer-queue behaviour:
[docs/taskqueue-integration.md](docs/taskqueue-integration.md).

## Tests

The default run is hermetic: it needs no Ollama, no GPU, no network, no API key,
and no `tq` on PATH. The suite must pass with `tq_available() is False`. Tests
that exercise the queue path stub
`llm_localizator.projects.taskqueue.tq_available` to `True`.

```text
uv run python scripts/test_lane.py quick   # every edit
uv run python scripts/test_lane.py full    # full hermetic suite (before scanner commits)
# or:
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
