# ADR-12 — Local model bakeoff defaults

**Status:** Accepted (2026-08-18)

## Decision

Per-locale Ollama models are chosen from a checked-in bakeoff
(`experiments/quality_bakeoff/`), not from ad-hoc vibe checks. Until a live
bakeoff fills `REPORT.md`, dogfood keeps `qwen2.5:7b` for translate and
`aya-expanse:8b` for improve. A locale may switch to Anthropic/DeepL only after
it fails the bakeoff gate (mean BT &lt; 0.70 or glossary-blocking rejects) or an
operator sets `[locales.providers]` explicitly with `[budget] monthly_usd > 0`.

## Why

The internal quality plan requires evidence before Phase 2 cloud
spend. Pinning improve on aya already fixed several dogfood stuck keys; changing
the translate default without a report would thrash consumer configs.

**Operator steps:** [docs/model-evaluation.md](../model-evaluation.md)
(matrix + LEDGER for quality/speed × locale coverage).
