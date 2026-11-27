# Cost and budget (cloud providers)

Local models (Ollama, CTranslate2) cost nothing per call. Cloud providers (Anthropic,
OpenAI, DeepSeek, DeepL) run only when you opt in, and every run is priced before it
starts. Field reference: [configuration.md](configuration.md) `[budget]` and `[privacy]`.

## Turning cloud on

Cloud needs all three:

1. An API key in the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …).
2. `[privacy] allow_cloud = true`.
3. `[budget] monthly_usd` above 0. At 0, cloud locales stay on the local provider.

`engine apply` never writes `[privacy]` or `[budget]` (ADR-156). Set them by hand, on purpose.

## What a run may spend

- **Pre-flight quote.** Before any call, the run prints
  `cloud quote: max_usd=… batch_usd=… remaining=… provider=… model=… keys=…`.
  `max_usd` is a ceiling from token counts, with `output_expansion` (default 2.0) and
  `thinking_tokens` as headroom. A run whose ceiling exceeds the month's remainder is
  refused before it sends anything.
- **Monthly ledger.** Actual usage is recorded per run in the data home. `remaining` is
  `monthly_usd` minus this month's spend.
- **Holds.** A run reserves its ceiling while it works and releases what it did not use,
  so two runs cannot each spend the same remainder.
- **Per-batch check.** Each batch is checked again during the run. If one would go over,
  the run stops and the queued cloud jobs are not sent.

## Budget modes

| `[budget] mode` | Behaviour |
|---|---|
| `on_request` (default) | Cloud runs only for named keys: `translate --keys ns.key[,…]` (also improve, review, rescore). A sweep without `--keys` is refused with `cloud mode is on_request: pass --keys …`. |
| `dynamic` | Any due string may go to the cloud while its ceiling fits the remainder. |

## Spending less

- `llm-localizator estimate-cost --locales pl` prints the maximum for everything due, with
  no API call.
- `[budget] cloud_batch = true` (default) sends multi-batch runs through Anthropic Message
  Batches or OpenAI Batch, at about half price. Batches finish in minutes rather than
  seconds. If some items in a batch fail, the ones that succeeded are kept and billed, and
  only the failed keys are retried.
- `[translate] cloud_batch_size` sends larger batches to hosted models (fewer requests, and
  the shared prompt prefix is cached).
- Glossary answers and translation-memory hits never reach the model.
- DeepSeek has no batch API. Its prefix cache and off-peak pricing are what make it cheap.

## Choosing a model

Never change models to save money without evidence: `llm-localizator bakeoff` compares
candidates on your own strings (ADR-12, [model-evaluation.md](model-evaluation.md)).
