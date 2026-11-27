---
name: l10n-review
description: Use when translations need a human check, or the user reports a wrong translation. Ranks risky keys, applies corrections with the right provenance, and turns repeated corrections into glossary terms.
---

# Review translations

Read the `llm-localizator` skill first. A correction the user dictates is stamped
`human`. A fix you choose yourself is stamped `agent`.

## Steps

1. Rank what a person should read first:
   ```bash
   llm-localizator review-risk --locale pl --limit 30
   llm-localizator review-risk --locale pl --format csv > review.csv
   ```
   The CSV has a `decision` column a reviewer can fill offline.
2. Apply corrections one at a time (with the user's yes):
   ```bash
   llm-localizator set --locale pl --key settings.save.button --text "Zapisz" --by human
   ```
   Use `--by human` only when a person gave you the text. The gate refuses text that loses
   a placeholder or changes ICU structure. Fix the text; do not reach for `--force`.
3. Or apply a filled CSV in one go (with the user's yes):
   ```bash
   llm-localizator import-review --locale pl --dry-run review.csv
   llm-localizator import-review --locale pl review.csv
   ```
4. Turn repeated corrections into terms:
   ```bash
   llm-localizator glossary-learn --locale pl
   ```
   It proposes terms only. Show them to the user, and write them with `--write` once they agree.
5. Clean up mechanical slips (wrapper quotes, `...` where the source uses `…`):
   ```bash
   llm-localizator normalize --locales pl
   ```
   It reports by default. `--write` applies the fixes, keeps each key's status, and never
   touches verified or locked keys.

## Done when

The keys the user asked about are corrected, `validate --locale pl` has no new errors, and
any proposed glossary terms were shown to the user.
