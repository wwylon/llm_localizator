# ADR-76: Ad hoc quality command

Status: accepted (2026-10-21)

`llm-localize quality` (C-016) validates, and optionally scores, message files without a registered project. It generates a scratch `.llm-localize.toml` and state dir in a temp folder, so the catalogue is only read. It is excluded from the ops manifest (CLI only): accepting a root and path template from the web would let a client read arbitrary disk paths, which crosses the trust boundary. `--score` goes through `cloud_gate`.
