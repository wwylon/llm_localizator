---
name: llm-localizator
description: Hard rules for localizing this project with llm-localizator (what needs the user's yes, provenance stamps, cost). Read before editing catalogues, wiring UI strings or running translations. Task recipes are in the l10n-* skills.
---

# llm-localizator: rules

This project's UI text is localized with llm-localizator. The config is
`.llm-localize.toml` in the repo root. For the full version-matched guide, run
`llm-localizator help agent`. To see where the project stands and what to do next, run
`llm-localizator guide`.

## Ask the user first

Get a yes, every time, before you:
- edit source, catalogues, `.llm-localize.toml` or `i18n.config.js`;
- run `init`, `runtime install`, `skill install`, `pseudo`, `set`, `adopt`, `normalize --write`;
- run `translate`, `improve`, `review`, `rescore` or `cycle --translate` (GPU time or cloud spend);
- run `engine apply`, `approach --set`, or `hardcoded-hunt --serve` (starts the app).

These are safe without asking: reading files, `guide`, `status`, `validate`, `check-keys`,
`agent-hardcoded`, `agent-backlog`, `review-risk`, `estimate-cost`, `explain-scan`.

## Never

- Mark your own edits `human`. Agent edits are stamped `agent`.
- Hand-edit a catalogue without stamping it: use `set` for one string, and run `adopt` after
  bulk edits.
- Pick the `cloud` approach or apply a cloud engine yourself. It sends text out and costs money.
- Change `[locales.models]`, roles or `judge_model` without a bakeoff winner.
- Put `en-XX` in `[locales] targets`. It is a URL-only marker locale.
- Commit, push or merge unless the user asked.

## Task skills

| Situation | Skill |
|---|---|
| You added or changed UI text | `l10n-wire-strings` |
| The user wants a new language | `l10n-add-language` |
| Translations need a human check | `l10n-review` |
| Preparing a release | `l10n-release` |

Results come back as JSON with `ok`, `exit_code` and `data` (`--format json`). Branch on
those, never on the wording. Exit codes: 0 clean, 1 fix something, 2 warnings only, 64 usage.
