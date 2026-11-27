---
name: l10n-release
description: Use before shipping a release. Read-only checks that every used key exists, active languages validate, no hardcoded copy is left, and nothing is waiting for review. Reports a go / no-go summary.
---

# Localization release check

Read the `llm-localizator` skill first. Every step here is read-only, so no yes is
needed. Fixing what it finds is.

## Steps

1. Keys used in code exist in the catalogue:
   ```bash
   llm-localizator check-keys
   ```
2. No hardcoded copy is left undecided:
   ```bash
   llm-localizator agent-hardcoded --status
   ```
3. Active languages validate. Frozen locales are not shipped, so name the active ones:
   ```bash
   llm-localizator status
   llm-localizator validate --locale pl
   ```
   Exit 2 means only warnings remain. That is a pass unless the user says otherwise.
4. Mechanical slips:
   ```bash
   llm-localizator normalize
   ```
5. Work waiting for people:
   ```bash
   llm-localizator draft list
   llm-localizator review-risk --locale pl --limit 10
   ```

## Report

`llm-localizator report` runs the same checks and prints a page with a verdict. Use
`--format html --out l10n-report.html` to hand it to people who don't use the CLI.

Give the user one short table: each check, pass or fail, and the count behind any fail.
Then a go / no-go:
- **No-go** if `check-keys` fails, `validate` has errors in an active locale, or a high or
  medium hardcoded hit is undecided.
- **Go, with notes** for warnings, normalize fixes, drafts or risky keys. List them, and
  let the user decide.

Do not fix anything as part of this check. Offer the fixes, and run them only after a yes.
