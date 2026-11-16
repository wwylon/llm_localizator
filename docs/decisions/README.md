# Design decisions

A curated subset of the project's architecture decision records: the ones the user
documentation refers to. Each explains why a behaviour or default is the way it is.

| ADR | Decision |
|-----|----------|
| [ADR-12](ADR-12-local-model-bakeoff-defaults.md) | Local model bakeoff defaults |
| [ADR-16](ADR-16-frozen-locales.md) | Frozen locales stay in targets but skip default LLM sweeps |
| [ADR-17](ADR-17-screenshot-context-opt-in-vision.md) | Screenshot context is opt-in via a separate vision model |
| [ADR-21](ADR-21-locale-model-roles.md) | Per-locale model roles (primary / secondary / judge) |
| [ADR-22](ADR-22-tm-and-ctranslate2.md) | Translation memory + optional CTranslate2 provider |
| [ADR-23](ADR-23-prompt-families.md) | Prompt families (chat vs mt_chat) |
| [ADR-27](ADR-27-consumer-visual-capture.md) | Consumer Playwright capture; engine ingest |
| [ADR-34](ADR-34-remote-content-api.md) | Project hosts the content API; the engine is the client |
| [ADR-35](ADR-35-cloud-cost-and-agent-mcp.md) | Cloud cost ceiling and agent MCP |
| [ADR-47](ADR-47-settings-providers-and-asap.md) | Named providers and ASAP locales |
| [ADR-60](ADR-60-project-config-prompt-bridge-identity.md) | Project prompt text, bridge locale, and identity keys |
| [ADR-68](ADR-68-voice-section.md) | `[voice]` section for product description, audience and tone |
| [ADR-69](ADR-69-local-only.md) | `[privacy] local_only` is a hard block |
| [ADR-74](ADR-74-approved-only.md) | Approved-only delivery |
| [ADR-75](ADR-75-tag-runs.md) | Tag-filtered runs |
| [ADR-76](ADR-76-quality-command.md) | Ad hoc quality command |
| [ADR-77](ADR-77-rename-placeholder.md) | Placeholder rename |
| [ADR-89](ADR-89-style-presets.md) | Style presets are an opt-in prompt line (C-002) |
| [ADR-90](ADR-90-ambiguity-notes.md) | Ambiguity notes are advice attached to Suggest (C-033) |
| [ADR-93](ADR-93-tasks-only-contributing.md) | Tasks-only contributing is enforced in the permission layer (C-029) |
| [ADR-95](ADR-95-several-shared-tms.md) | Several read-only shared TMs and one optional write target (C-030) |
| [ADR-110](ADR-110-qa-marker-locales.md) | QA marker locales (en-XX) are opt-in |
| [ADR-111](ADR-111-cloud-token-efficiency.md) | Portable cloud token efficiency + Haiku 5.5 default |
| [ADR-112](ADR-112-engine-data-home.md) | Engine sidecars default to ~/.llm_localize/data/<name>/ |
| [ADR-118](ADR-118-shipped-web-runtime.md) | Shipped web runtime, `runtime` and `check-keys` |
