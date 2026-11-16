# ADR-68: `[voice]` section for product description, audience and tone

`description` and `audience` already existed under `[prompt]` (ADR-60). C-001 adds a
`[voice]` table as their preferred home and a new `tone` line, so a product's voice
sits in one place and the guided setup can ask for it.

- `[voice]` feeds the same `ProjectConfig.description` / `audience` fields; `tone` is new.
- Setting one field in both tables is a load error, not a silent precedence rule.
- `prompt_extras_for` appends `Tone: ...` only when set, so projects without `[voice]`
  keep byte-identical prompts (prompt snapshot test).
- Web project config writes to `[voice]` when that table already holds the key, else to
  `[prompt]`; `tone` always goes to `[voice]`.
- Guided setup gets an optional step; it never blocks "ship".
