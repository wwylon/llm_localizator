# ADR-69: `[privacy] local_only` is a hard block

C-023. `allow_cloud = false` only made cloud kinds fall back to Ollama with a note. Teams
with a no-egress rule need a setting that fails loudly instead.

- `local_only = true` plus `allow_cloud = true` is a load error.
- Load also fails for a cloud provider kind in `[provider]` or `[providers.<id>]`, for an
  Ollama URL that is not loopback, and for a non-loopback `[notify] webhook`.
- `provider_for_locale` and `project_provider` raise `ProviderError` for cloud kinds, as a
  second line of defence for configs mutated after load.
- Reads of existing TM and glossary files are unchanged. Workflow webhooks are not yet
  covered; they stay a follow-up (amends ADR-35).
- The usage page shows a local-only note instead of the budget meter.
