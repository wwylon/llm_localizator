# Project config page

`/app/project-config` (Admin only) edits the selected project's
`.llm-localize.toml`. Keys are defined in
[ADR-60](decisions/ADR-60-project-config-prompt-bridge-identity.md).

**Saving.** Nothing is written until you press **Save all**. The page sends
only the fields you changed. The server builds the new file in memory, checks
it with the same loader the CLI uses, and replaces the file only if it loads.
On any error the message appears under the tabs and the file is byte-for-byte
unchanged. Closing the page with unsaved edits loses them.

## Prompt templates

| Control | Key | Limit | Effect |
|---------|-----|-------|--------|
| Project description | `[prompt] description` | 2000 chars | Added to every translation prompt as "Project description". |
| Per-language additions | `[prompt.styles.<locale>] notes` | 500 chars each | Extra instructions for one target language only. |
| Per-model variants | `[prompt.models."<model>"] text` | 1000 chars each | Used only when that exact model tag runs. |
| Translate this variant | `[prompt.models."<model>"] localize` | | Translate that variant into the target language (see below). |
| Automatic prompt localization | `[prompt] localize` | `source` / `target` / `per-model` | `source` keeps instructions in the source language. `target` translates them for every language. `per-model` translates only for models whose box is ticked. |
| Advanced | `[prompt] family`, `[locales.prompt_family]`, glossary path and domains | | Unchanged from earlier versions. |

**How prompt localization works.** The description, audience, notes and model
text are translated once per target language by the model that is running the
job, then cached in `<state>/prompt-i18n/<locale>.json`, keyed by a hash of the
text. Editing the text makes a new hash and a new translation; unchanged text
is never translated twice. If the provider fails, the source-language text is
used and the run says so. Per ADR-12 this never changes `[locales.models]`.

## Bridge language

Translate first into an intermediate locale, then from it into every other
target. Useful when the source language is a poor pivot for a target.

| Control | Key | Notes |
|---------|-----|-------|
| Mode | `[bridge] mode` | `none`, `en` (English) or `custom`. |
| Bridge locale | `[bridge] locale` | Must be a target locale or the source locale. |
| Bridge model | `[bridge] model` | Used for the bridge locale only. Empty = normal model. |
| Store bridge text | `[bridge] store` | `No` is allowed only when the bridge locale is the source locale. |
| Pivot locales | `[locales.pivots]` | Per-language override of the bridge. Wins over the bridge. |

The bridge is the default pivot: `cfg.pivot_for(locale)` returns the explicit
pivot, else the bridge locale. The bridge locale itself translates from the
source and is ordered before the languages that depend on it. A bridge locale
combined with a pivot for that same locale is rejected.

## Glossary sharing

Attach glossaries owned by other registered projects. They are read-only here
(ADR-42): you can attach and detach, never edit another project's file. Each
row shows its source (own or shared) and term count.

| Merge conflict mode | `[prompt] glossary_conflict` | Result when a term exists in both |
|---------------------|------------------------------|-----------------------------------|
| Project wins | `own` (default) | Your translation is used. |
| Shared wins | `shared` | The shared translation is used. |
| Project wins, list conflicts | `flag` | Your translation is used and the page lists the conflicting terms. It does not create review flags. |

## Project identity

| Control | Key | Effect |
|---------|-----|--------|
| Display name | `[project] display_name` | Shown in headings. Not sent to the model. |
| Domain | `[prompt] domain` | Preset or free text; added to every prompt. |
| Audience | `[prompt] audience` (300 chars) | Added to every prompt as "Target audience". |

## Troubleshooting

A rejected save shows the loader message, which names the key and the rule that failed: an enum that is not one of its allowed values, text over its limit (2000, 300, 500 or 1000 characters), a bridge locale that is not a target or source locale, `store = false` with a non-source bridge locale, or a bridge locale that also has a pivot. Fix the field and save again; the file was not touched.
