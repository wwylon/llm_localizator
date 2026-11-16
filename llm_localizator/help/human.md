# llm-localizator — guide for people

This guide is for the person who owns the localization of an app: what to decide,
what to run, and how to read what comes back. Agents follow their own rules in
`llm-localizator help agent`. Print this file any time with `llm-localizator help human`.

## 1. Choose how to localize

Run `llm-localizator guide <project>` (or open `llm-localizator web`). Its first questions
are which languages you want and who writes the translations.
`llm-localizator approach <project>` shows the options with a recommendation for your
machine; `--set <id>` records your choice.

<!-- generated:approaches -->
| Approach | Pick it when | Cost |
|---|---|---|
| `local`: Local model, queued | Private text, no budget, a GPU available. | free; slow (minutes to hours) |
| `cloud`: Cloud model with a spending cap | No GPU, many strings, or a deadline; the text may leave the machine. | paid; fast |
| `agent`: Your coding agent writes them | Few strings, an agent already working in the repo, no local model. | the agent's tokens; no model setup here |
| `human`: Human translators | Legal, marketing or brand text, or a language you cannot check. | their time |
| `hybrid`: Machine draft, human review | Languages you ship to users: drafts are fast, review catches one-word errors. | mixed |
<!-- /generated:approaches -->

`hybrid` is the safe default for anything users will read. Machine scores do not
catch every one-word error (section 6).

## 2. Decisions only you make

- **Which languages you ship** (`[locales] targets`), and which are **frozen**: kept
  only to check layout, such as Chinese for long glyphs or Arabic for right-to-left.
  Frozen languages are skipped by default runs.
- **Glossary terms**: the approved word for each product term, plus forbidden
  variants. `llm-localizator glossary-propose` suggests candidates, and
  `llm-localizator glossary-learn <project> --locale pl` proposes rules from fixes people
  and agents made more than once (zaoferuj → zapowiedź). You confirm each one; nothing
  is added to the glossary on its own.
- **Drafts held back.** A translation scoring under `[quality] write_floor`, or a
  rerun that is not better than what is there, is kept as a draft instead of being
  written. Review drafts in the web editor (`llm-localizator draft list`) and accept or
  reject them.
- **Review** of short labels and buttons in every language you ship.
- **Whether an agent may edit an app repo**, install the runtime, or start your
  app's server for a crawl. Agents are told to ask you first.
- **Model changes** happen only after a bakeoff (`llm-localizator bakeoff`, ADR-12).

## 3. The workflow

```bash
llm-localizator init                              # detect the catalogues, write .llm-localize.toml
llm-localizator approach <project> --set hybrid   # who writes the translations
llm-localizator runtime install <project>         # plain JS apps: the shipped i18n.js ([web] runtime_path)
# wire the UI: i18n.t('key') / data-i18n (agents follow `help agent` section 3)
llm-localizator check-keys <project>              # every used key exists; en-XX current
llm-localizator translate <project>               # queued (taskqueue); `tq status` to watch
llm-localizator validate <project>                # catalogue checks
llm-localizator hardcoded-hunt <project> --serve  # en-XX crawl: what is still English on screen
llm-localizator web                               # review and fix in the editor
llm-localizator cycle <project>                   # all of the checks above in one report
llm-localizator review-risk <project> --locale pl # the translations to read first
```

`llm-localizator guide` always tells you the next step, and adapts it to your
approach.

## 4. Reading the results

**`check-keys`.**
- `missing`: code uses a key that `en.json` lacks; the page shows the raw key.
- `unused`: an `en.json` key nothing uses.
- `stale en-XX`: run `llm-localizator pseudo <project> --locale en-XX`.

**`validate`.** Errors block shipping; warnings are worth a look.

<!-- generated:checks -->
| Code | Severity | What it means |
|---|---|---|
| V01 | error | key missing in a language (for frozen languages this is expected) |
| V03 | error | plural forms missing for the language (Polish needs one, few, many, other) |
| V04 | error | a forbidden glossary variant was used, or a whole label lacks its approved word |
| V13 | warning | an approved glossary term is missing from a sentence (warning) |
| V43 | error | the translation is wrapped in quotes |
| V46 | error | a short label got a long sentence back (the model echoed its instructions) |
| V47 | error | the ICU structure changed (a `select` became a `plural`, or a branch is gone) |
| V48 | warning | one glossary term is translated several ways across the app |
| V49 | error | the app's description leaked into the translation |
| V50 | error | markup the source lacks (`**`, backticks), or text moved outside an ICU message |
| V51 | error | a leading symbol (`~`, `≈`, `<`) was dropped or spelled out |
<!-- /generated:checks -->

**QA crawl report** (`~/.llm_localize/data/<name>/qa/<ts>/index.md`):
- **Leftovers**: text still English under en-XX. Rows marked *dynamic* are not in
  the source code; they come from the server or an API, or they are user data.
- **Layout**, per Arabic and Chinese page:
  - text direction;
  - clipped or off-screen text;
  - a full-page screenshot. Look at it: mixed-direction text is not measured
    automatically.

To set up the crawl, describe your app once in `[qa]` (`docs/configuration.md#qa`):
base URL, pages, how a page switches language, and the command that starts it.

### Reviewing in a spreadsheet

```bash
llm-localizator review-risk <project> --locale pl --format csv   # save the output as review.csv
# fill the decision column: keep, suggestion (take the judge's), or your own text
llm-localizator import-review <project> review.csv --locale pl --dry-run
llm-localizator import-review <project> review.csv --locale pl
```

Every row goes through the same checks as `set`, stamped as a human edit.

### Before you ship a language

- [ ] Glossary confirmed: product terms approved, `glossary-learn` proposals decided.
- [ ] `llm-localizator review-risk <project> --locale pl`: every high-risk row read.
- [ ] `llm-localizator cycle <project>` reports no validation errors for the language.
- [ ] Short labels and buttons read by someone who speaks it (section 6).
- [ ] The en-XX crawl shows no English except names, data and units.
- [ ] Layout checked in the crawl screenshots for long or right-to-left languages.
- [ ] The CI commands in section 5 pass.

## 5. Keeping it in CI

Add these to the app's test suite or CI. Each exits non-zero on a problem:

```bash
llm-localizator validate <project>        # 1 = errors, 2 = warnings only (--strict: warnings fail too)
llm-localizator runtime check <project>   # the shipped i18n.js is current and unedited
llm-localizator check-keys <project>      # no missing keys, en-XX not stale
```

A CI step that should tolerate warnings treats exit code 2 as a pass.

## 6. Known traps

- **One-word errors pass the score.** "Zmniejsz" ("shrink") for "make big" and
  "Zrzutka" (a whip-round) for "Discard" both scored high. Read short labels
  yourself.
- **Stale en-XX** makes keys look hardcoded. Regenerate it after `en.json` grows.
- **Frozen languages** show many V01 "missing" errors. That is expected; they are
  layout checks.
- **Server text is not in your catalogues.** API messages show up as *dynamic* in
  the crawl report and need a change on the server.

## 7. Where things live

- Settings: `.llm-localize.toml` in the app repo. The reference is
  `docs/configuration.md`.
- State, scores, history and reports live under `~/.llm_localize/data/<name>/`.
  Nothing is written into the app repo except the catalogues and, if you install
  it, `i18n.js`.
