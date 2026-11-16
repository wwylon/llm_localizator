# ADR-23 — Prompt families (chat vs mt_chat)

**Status:** Accepted (2026-08-29)

## Decision

Translation prompts share one builder stack, but may select a **family**:

- `chat` (default) — full instruction rules (ICU, punctuation, short-label, …).
- `mt_chat` — shorter rules that emphasize one sense from key/context/glossary.

Configured as `[prompt] family` with optional `[locales.prompt_family]`
overrides. Families are **not** model defaults and do **not** replace ADR-12
bakeoff gates for `[locales.models]` / roles.

Bakeoff must distinguish **stripped** (raw fluency) from **consumer**
(production-like domain/glossary/key/context). Stripped-only rankings must not
drive model swaps.

## Why

Dense chat rules suit instruction models (e.g. aya). MT-oriented chat tags
(e.g. TranslateGemma) can overfit or ignore sense when context is missing —
bakeoff `Board` → `Plaża` under a SaaS domain with empty glossary. Separating
prompt family from model pins keeps experiments cheap without a prompt file
per Ollama tag.

## Rejected

- Per-model prompt files for every Ollama tag.
- Auto-detecting family from model name forever (explicit TOML only).
- Applying families to CTranslate2/MADLAD (source-only; prompt text ignored).
