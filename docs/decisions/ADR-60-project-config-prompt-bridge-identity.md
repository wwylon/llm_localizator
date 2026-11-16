# ADR-60 — Project prompt text, bridge locale, and identity keys

The operator asked for the full design-2 Project config page. That needs
config keys W-07 refused to invent without a decision.

## Decision

New keys, all optional; absent keys leave behaviour unchanged.

- `[project] display_name` — label only; shown in the web UI.
- `[prompt] description` (≤2000 chars) and `audience` (≤300) — added to every
  translation preamble as "Project description" / "Target audience".
- `[prompt.models."<model>"] text` (≤1000) and `localize` (bool) — extra
  instruction text appended when that exact model runs.
- `[prompt] localize = "source" | "target" | "per-model"` — whether the
  project/model instruction block is translated into the target language.
  The translation is generated once per (locale, text hash) by the run's own
  model and cached in `<state>/prompt-i18n/<locale>.json`. Default `source`.
- `[bridge] mode = "none" | "en" | "custom"`, `locale`, `model`, `store`.
  Bridge locale must be a target (or the source). Every target without an
  explicit `[locales.pivots]` entry takes the bridge locale as its pivot, so
  the existing pivot ordering and reference prompt (ADR-21/25) do the work and
  the bridge locale is translated first. `model` overrides the model for the
  bridge locale only. `store = "no"` is rejected unless bridge equals source:
  a bridge locale that is a target is stored by definition.
- `[prompt] glossary_conflict = "own" | "shared" | "flag"` — who wins on the
  same term (ADR-42 default is `own`); `flag` keeps own and lists every conflicting term on the Project config
  page (term flags have no key to attach to in the review queue).

Reused, not new: per-language additions are `[prompt.styles.<loc>] notes`;
pivot table is `[locales.pivots]`; domain/industry is `[prompt] domain`.

## Rejected

A free-form prompt template replacing the built-in rules (ADR-23 keeps the
family set closed); a hidden scratch locale for non-stored bridges.
