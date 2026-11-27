# Visual findings — operator procedure

Consumer Playwright (or manual) capture writes one JSON object per line.
Engine `llm-localizator ingest-visual` reads the file and opens review-queue tickets.
See [ADR-27](decisions/ADR-27-consumer-visual-capture.md).

This is the **end-to-end loop**. You should not need to read the capture script.

## Procedure

1. **Start the consumer UI**
   - Next.js app: `pnpm dev` (or e2e stack) on `:3000`
   - Dogfood: `llm-localizator web --no-browser` on `:8770`

2. **Capture** (CLI or taskqueue) with resume support
   - Next.js app:
     ```bash
     # Prefer the interpreter that has Playwright (often Windows: py -3.12)
     py -3.12 scripts/i18n_browse_review.py --locales pl,ar --no-llm --resume
     ```
   - Dogfood:
     ```bash
     py -3.12 experiments/visual_qa/dogfood_browse.py --locales pl --resume
     ```
   - Or submit the TQ suite (see [taskqueue-integration.md](taskqueue-integration.md#visual-qa-suite)):
     ```bash
     tq retry my-app/i18n_page_review
     # / tq retry llm_localizator/llm_localizator_visual_qa
     ```
   - Progress prints `[3/40] pl lobby (7.5%)`. After each locale×screen the script
     appends findings and updates the checkpoint — CTRL+C loses at most one screen.
   - Re-run with `--resume` (default when the checkpoint matches) or `tq retry`.
   - Full redo: `--force` (new `run_id`, clears `completed`, truncates findings).

3. **`llm-localizator ingest-visual`** → `.llm-review/{locale}.jsonl`

4. **`llm-localizator validate --check-layout`** → advisory **V28** on keys with screenshots
   (V27 remains HTML tag integrity)

5. **Triage** in `llm-localizator web` / Ops / review queue

When using the TQ suite, steps 3–4 chain via `on_complete` after capture exits 0.
Start the UI first; only the capture task has `requires_services`.

## Checkpoint file

| Project | Path |
|---------|------|
| Next.js app | `apps/web/messages/.visual_review_checkpoint.json` |
| Dogfood | `i18n/.visual_review_checkpoint.json` |

Schema (v1): `run_id`, `base_url`, `locales`, `screens`, `findings_path`, and
`completed[]` entries `{locale, screen, status, ts, screenshot, n_findings}`.
Statuses `ok` / `skipped` / `error` are treated as done on resume (unless `--force`).
Mismatch of `base_url` / locales / screens / findings path without `--force` exits
with a clear error. Override path with `--checkpoint PATH`.

Findings JSONL is **append-only** per screen (not only rewritten at end of run).

## Screenshots

| Layout | Purpose |
|--------|---------|
| `screenshots/{locale}__{screen}.png` | Resume + locale-specific layout QA |
| `screenshots/{screen}.png` | Updated from the **first locale** in the run (existing thumbs / ADR-17) |

### Dark-mode matrix (review UI)

When capturing the package review UI (dogfood), run each surface once under
`html[data-theme=light]` and once under `data-theme=dark` (chrome theme toggle
or `localStorage.llm_ui_theme`). Minimum pages: dashboard, editor, settings,
review, operations. Browser smoke: `tests/browser/test_smoke_pages.py::test_dark_theme_matrix_pages`
(`pytest -m browser`). Consumer product UIs keep their own theme capture.

Engine `resolve_screenshot_path` tries `{locale}__{screen}` then `{screen}` when
locale is known (`validate --check-layout`, translate vision).

## Location of findings

Default: `{context_dir}/../.visual_findings.jsonl` when `[prompt] context_dir` is
set (e.g. `apps/web/messages/.visual_findings.jsonl`, `i18n/.visual_findings.jsonl`).
Override with `[visual] findings_path` in `.llm-localize.toml`.

## Record fields (`schema_version: 1`)

| Field | Required | Notes |
|-------|----------|-------|
| `schema_version` | yes | Must be `1` |
| `locale` | yes | Target locale code |
| `screen` | yes | Logical UI surface id |
| `path` | no | URL or UI path hint |
| `namespace` | no | Catalogue namespace; null for flat keys |
| `key` | no | Bound key; null = page-level |
| `reason` | yes | See reasons below |
| `message` | yes | Human-readable detail |
| `screenshot` | no | Path relative to `context_dir` |
| `selector` | no | CSS that failed |
| `source` | no | `browse-review` \| `dogfood-harness` \| `tq-smoke` \| `manual` |
| `ts` | no | ISO-8601 |

### Reasons

`layout_overflow` · `layout_clip` · `layout_heuristic` · `layout_overlap` · `en_leak` · `icu_leak` · `glossary` · `other`

### Key binding (consumer priority)

Used by visual ingest and browse-review scripts to attach findings to keys.
The **translator overlay** uses the same attribute conventions; resolution
order is documented in [web.md](web.md) § Translator mode.

1. `[data-i18n-key="ns.key"]`
2. `[data-llm-ns]` + `[data-llm-key]`
3. `[data-i18n="flat.key"]`
4. Else `key` / `namespace` null (page-level ticket)

## Built-in QA crawl (`[qa]`)

For layout checks that need no consumer harness, a `[qa]` block lets the engine
crawl the app itself (ADR-119). Every layout locale gets a full-page screenshot
per page in `~/.llm_localize/data/<name>/qa/<ts>/<locale>/`. `layout.json` lists
the text elements that are clipped (`scrollWidth > clientWidth` with overflow
hidden or an ellipsis), outside the viewport, or overlapping another visible
text box (bounding-box intersection confirmed with `elementsFromPoint`), and
flags a page whose `dir` does not match the locale (rtl for ar/he/fa/ur). This
covers RTL overflow, CJK layout, and TiMi-style overlap. Map crawl `overlap`
issues to visual-findings reason `layout_overlap` when filing JSONL. Catalogue
keys with `data-i18n` / `data-llm-key` also feed **layout budgets**
(`~/.llm_localize/data/<project>/layout_budgets/<source_locale>.json`);
`validate --check-layout` then warns with **V29** when a translation is
estimated wider than the measured box (ADR-159). Visual findings JSONL (below)
remains the format for judged, screenshot-backed defects a consumer's own
harness produces.

## Python / Playwright note

On Windows, the default `python` on PATH is often MSYS (no pip/Playwright). Use
the install that has Playwright — typically `py -3.12` — for capture scripts and
for TQ worker `command:` if the queue’s default interpreter lacks browsers.

Review queue is the source of truth after ingest; `.flags.jsonl` may still be
appended by browse for the debug overlay.
