# ADR-112 — Engine sidecars default to ~/.llm_localize/data/<name>/

Accepted 2026-11-02. Amends ADR-3’s “everything the engine reads stays in the
consumer repo” reading for **runtime sidecars only**.

Config (`.llm-localize.toml`) stays in the consumer (ADR-3). Catalogues,
glossary, context notes, examples, and document **source** trees stay there
too. State, history, scores, TM, review queue, budget ledger, flags, document
translation state, and scan usage output default under
`~/.llm_localize/data/<project.name>/` (overridable with `LLM_LOCALIZE_HOME`),
so consumer checkouts stay tidy.

Opt out with `[project] data_home = "project"` — relative sidecar paths then
resolve against the config directory, as before. Absolute overrides always win.
Relative sidecar overrides under `data_home = "engine"` resolve against the
engine data root, not the consumer root.

Rejected: storing sidecars inside the llm_localize git checkout (`project_data/`)
— that couples every consumer to an editable package tree and is wrong for a
PyPI install. Rejected: putting configuration itself in the registry (already
rejected by ADR-3).
