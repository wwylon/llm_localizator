---
name: l10n-add-language
description: Use when the user wants the app in a new language, or wants missing translations filled. Adds the locale, shows cost and approach before anything runs, then translates and validates.
---

# Add a language, or fill missing translations

Read the `llm-localizator` skill first. Every write step here needs the user's yes, and a
translate run can cost money.

## Steps

1. Check the approach (who writes the words):
   ```bash
   llm-localizator approach
   ```
   If none is chosen, show the user the options and the recommendation, and wait. Never
   choose `cloud` yourself.
2. Add the locale (with the user's yes). It must be a real language code, never `en-XX`:
   ```bash
   llm-localizator add-locale --locale de
   ```
3. Show what a run would do, before running it:
   ```bash
   llm-localizator translate --locales de --dry-run
   llm-localizator estimate-cost --locales de
   ```
   Tell the user the key count and, for cloud, the maximum cost. With the default budget
   mode (`on_request`), cloud runs only for named keys (`--keys`).
4. Translate (with the user's yes):
   ```bash
   llm-localizator translate --locales de
   ```
   It queues through taskqueue when installed and runs inline otherwise. Never start a
   full sweep in a background shell.
   - **Agent approach:** you write the words yourself. Run `llm-localizator agent-backlog --locales de`,
     fill the catalogue, then run `llm-localizator adopt --locales de`.
5. Check:
   ```bash
   llm-localizator validate --locale de
   llm-localizator review-risk --locale de --limit 20
   ```

## If the project already has translations

Values with no state record are left as they are. Record them with `adopt` before
translating, then fill only the gaps with `translate --only-missing`.

## Done when

`validate --locale de` has no errors, and the user has seen the `review-risk` list (or
said a review is not needed).
