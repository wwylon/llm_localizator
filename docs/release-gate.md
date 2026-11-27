# Pre-release gate

Run these before tagging a release or quoting scanner metrics publicly.

## 1. Hermetic tests

```text
.\.venv\Scripts\python.exe -m scripts.test_lane full
```

Or the fast lane while iterating:

```text
.\.venv\Scripts\python.exe -m pytest -m "not slow and not ollama and not live_bridge and not browser"
```

Full suite with xdist (file-affine):

```text
.\.venv\Scripts\python.exe -m pytest -n auto --dist loadfile -m "not ollama and not live_bridge and not browser"
```

Tests marked `@pytest.mark.serial_web` share one xdist group so load-sensitive localhost
servers do not collide under `-n auto`. Prefer fixing shared fixtures over `xfail`.

## 2. Lint and module budgets

```text
.\.venv\Scripts\python.exe -m ruff check llm_localizator
.\.venv\Scripts\python.exe scripts/check_module_budgets.py
```

`scripts/size_budget.py` is a deprecated alias of the same ratchet.

## 3. Scanner (dev corpora only)

```text
.\.venv\Scripts\python.exe experiments/scanner_bench/gate_all.py
```

Never tune on a frozen held-out pool. After gate_all passes, a **single** held-out
score (if any unused pool remains) goes through `experiments/scanner_bench/cycle.py`
and is recorded in the LEDGER.

## 4. Self-validate dogfood catalogues

```text
.\.venv\Scripts\python.exe -m llm_localizator validate .
```

## 5. Optional live / browser

Needs Ollama or the `e2e` extra — not part of the hermetic gate.
