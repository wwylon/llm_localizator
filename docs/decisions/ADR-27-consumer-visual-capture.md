# ADR-27 — Consumer Playwright capture; engine ingest

**Status:** Accepted (2026-08-30); amended 2026-10-18 (browser tests)

## Decision

Rendered UI / Playwright capture stays in **consumers** (a consumer's own browse-review,
dogfood `experiments/visual_qa/`, later taskqueue UI smoke). The `llm_localize`
**package** stays browser-free: it owns the findings JSONL schema, screenshot
path contract under `context_dir/screenshots/`, `core/layout_qa`, validate
`--check-layout` (**V28** advisory; V27 remains HTML tag integrity), and
`ingest-visual` → `.llm-review` (ADR-14 ops).

ADR-26’s rejection of “Playwright in-tree” means **no Playwright dependency in
the installed package or unmarked pytest**. Consumer harnesses under
`experiments/` (including this repo’s dogfood) are allowed.

## Why

A consumer app often already has Playwright and browse-review; duplicating Chromium in the
engine fights hermetic CI and ADR-1/14 boundaries. A shared findings schema lets
every consumer feed one review queue.

## Rejected

- `llm-localize[visual]` / Playwright inside `ops/` or `pipeline/` as a hard dep.
- Pixel golden / Percy baselines in v1.
- Taskqueue daemon hosting a shared browser service.

## Amendment (2026-10-18) — Playwright allowed for tests

UI behaviour of the web app (project switch, workflow editor, operations card)
cannot be verified by string-level contract tests. Playwright is therefore
allowed **for tests and tooling**, never as a runtime dependency:

- Optional extra `e2e = ["playwright>=1.45"]`; not in `dependencies`.
- pytest marker `browser`, **deselected by default** (`addopts`); the default
  run stays hermetic and needs no Chromium. Run:
  `uv run --extra e2e pytest tests/browser -m browser`.
- Tests live in `tests/browser/` and skip (not fail) when Playwright or
  Chromium is unavailable. They use scratch projects only.
- No Playwright import under `llm_localize/`; capture / `ingest-visual` /
  V28 boundaries above are unchanged. Pixel baselines stay rejected.
