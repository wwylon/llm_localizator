# ADR-16 — Frozen locales stay in targets but skip default LLM sweeps

**Status:** Accepted (2026-08-26)

## Decision

1. `[locales] frozen = [...]` lists target locales that remain in the catalogue
   (status, validate, web browse, export) but are **excluded from the default
   work set** for translate, improve, review, sync, documents, rescore, and
   base taskqueue blueprints.
2. Explicit `--locales` / checked frozen locales in the web Ops picker still run
   them. Per-locale translate blueprints are still generated for frozen
   locales so an operator can thaw one with `tq retry …__de`.
3. Freezing every target is a config error — leave at least one active.

## Why

Consumer projects (for example a card-game app) ship many locales for product coverage while only
actively improving a few. Removing locales from `targets` drops them from the
UI and status; freezing keeps visibility without burning GPU on every sweep.

## Consequences

- `ProjectConfig.active_targets()` / `resolve_locales(None)` is the default
  work set. Pipelines and ops that previously defaulted to `cfg.targets` for
  LLM work now use that helper.
- Validate / status / export keep the full `targets` list.
- Base blueprints bake active locales into `--locales`; regenerate after
  changing `frozen`.
