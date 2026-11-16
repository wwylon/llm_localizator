# ADR-111 — Portable cloud token efficiency + Haiku 5.5 default

**Status:** Accepted (2026-11-01)

## Context

Cloud translate is opt-in (ADR-35). List prices for short-prompt Claude Haiku
dropped an order of magnitude with `claude-haiku-5-5`, and every major vendor
offers either prompt caching, an async Batch API at ~50% off, or both.
Monolithic user-only prompts prevented Anthropic `cache_control` hits.

## Decision

1. **Anthropic package default** is `claude-haiku-5-5` (pricing row +
   `CLOUD_DEFAULT_MODEL`). Keep Haiku 4.5 rows for existing ledger history.
2. **Portable rules** for all LLM cloud kinds:
   - stable system prefix (domain / register / style / glossary / rules),
     volatile string list last;
   - pack many strings per HTTP call (`[translate] batch_size`);
   - prefer async Batch when latency can wait (`[budget] cloud_batch`,
     default true) — Anthropic Message Batches and OpenAI Batch;
   - DeepSeek: no Batch API; disable thinking for JSON MT; meter
     `prompt_cache_hit_tokens`; schedule bulk off-peak when possible;
   - DeepL: character billing; up to 50 texts; free `context`;
   - meter real cache fields into ledger `actual_usd`;
   - ADR-35 `max_usd` stays conservative (no assumed cache/batch discount).
3. **ADR-12 unchanged.** Do not swap dogfood `[locales.models]` / roles /
   `judge_model` without a bakeoff Winner. Cheap cloud is named providers
   (`anthropic_haiku`, `openai_luna`, `deepseek_flash`), `--model`, or
   on_request only.
4. **Gemini** stays out of scope until a dedicated provider ADR.

## Consequences

- `CompletionRequest.system` + `build_*_prompt_parts` feed Anthropic
  `cache_control` and OpenAI/DeepSeek automatic prefix cache.
- TQ cloud translate drains multi-batch jobs through `Provider.complete_many`.
- Operators enable cloud with `[privacy] allow_cloud`, a positive
  `[budget] monthly_usd`, and env keys — never keys in TOML.
