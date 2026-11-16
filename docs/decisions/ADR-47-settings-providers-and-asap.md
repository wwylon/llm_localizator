# ADR-47 — Named providers and ASAP locales

Settings (design/2) needs multiple named LLM endpoints and an ASAP
priority distinct from frozen. Optional ``[providers.<id>]`` tables hold
``name``, ``kind``, ``url``, and optional ``model_path``. When absent, the
loader synthesizes ``id = "default"`` from legacy ``[provider]``.
``[locales.providers]`` values are provider ids when that id exists;
otherwise they remain kind strings (today’s behavior).
``provider_for_locale`` uses the resolved entry’s URL and kind.

``[locales].asap`` is a target subset, disjoint from ``frozen``. Default
sweeps and translate ordering prefer ASAP after pivot dependencies; frozen
stays excluded. Bind host stays loopback (ADR-33). Model / judge pins still
need bakeoff evidence before Settings writes them (ADR-12).

Rejected: inventing ASAP as a third frozen state; silently treating the
design’s multi-endpoint table as UI-only without URL resolution.
