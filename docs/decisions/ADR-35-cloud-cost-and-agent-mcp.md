# ADR-35 — Cloud cost ceiling and agent MCP

**Status:** Accepted (2026-09-19)

Paid localization is opt-in. `[budget] mode` is `on_request` or `dynamic`.
`on_request` calls a cloud provider only for an explicit key list.
`dynamic` may send every due string, but only when the pre-flight `max_usd`
fits the remaining monthly budget. The check runs again in the worker before
each batch. `max_usd` is a ceiling (one request per string, higher published
rate, no cache discount). The ledger records actual usage. Ollama and
CTranslate2 ignore the mode. There is no watcher.

OpenAI and DeepSeek join Anthropic and DeepL. Keys stay in the environment.
Unknown models are not priced as a cheap default.

The agent MCP is an operator interface over `ops/`. It is not the content API
(ADR-34) and it does not write catalogue strings itself (ADR-19).

Rejected: a background poller, pricing the model's maximum output as the
ceiling, and accepting API keys as MCP arguments.
