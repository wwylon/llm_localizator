# ADR-34 — Project hosts the content API; the engine is the client

**Status:** Accepted (2026-09-19)

Database text (club descriptions, tournament names, and the like) is not a
catalogue file. The project that owns the database hosts `GET/PUT /v1/units`.
llm_localize calls that API from the machine that has the model. Each unit
carries its own `source_locale`; the engine does not assume English and does
not pivot through English. `src_sha` is the frozen `src_hash` (ADR-7). Human
rows are not overwritten unless the operator forces it.

The review server stays on `127.0.0.1` with its startup `X-LLM-Token` (ADR-33).
That token is not the content credential. The content token is
`LLM_LOCALIZE_CONTENT_TOKEN`, and the URL is `LLM_LOCALIZE_CONTENT_URL`. Neither
is written into the review server, and the engine does not open Postgres.

Rejected: an MCP data plane, a SQL adapter, subclassing `Catalog`, teaching
`status.collect()` to speak HTTP, and binding `llm-localize web` on a public
interface.
