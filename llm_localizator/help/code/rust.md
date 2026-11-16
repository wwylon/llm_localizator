# Rust (CLI, Tauri, Yew, Leptos): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `rust` | basic |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `println!(`, `Label::new(`, `Button::new(`, `.set_label(`, `Paragraph::new(`, `bail!(`, `anyhow!(`.

Catalogue formats (`[catalog] format`): `po`.
<!-- /generated:code-facts -->

## For people

- Common libraries: `fluent` (`.ftl` files), `rust-i18n` (`t!("key")`), `gettext-rs`. Pick one before adding screens.
- A CLI is user-facing too: `println!("…")`, `eprintln!`, `bail!("…")`, `clap` help text from `///` doc comments and `#[arg(help = "…")]` are shown to a person.
  `.expect("…")`, `panic!` and `unwrap` messages are for developers and are not reported.
- Interpolate with named arguments in the message format, never with `format!` around a translated piece.
- For web front ends (Yew, Leptos, Dioxus), text inside `html!`/`view!` macros is markup text.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. Rust is read by the literal detector (basic tier): macros, `clap` doc comments and the sinks above. Test modules (`#[cfg(test)]`) are skipped.
2. Fix by moving the text to the catalogue and calling the library's lookup; then `llm-localizator validate`.
3. No catalogue adapter for Fluent `.ftl` yet: gettext `.po` catalogues work today. Do not hand-edit `.ftl` through other tools unless you keep message ids and variables unchanged.
