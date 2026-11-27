---
name: l10n-wire-strings
description: Use after adding or changing user-visible UI text in this project. Finds hardcoded strings, wires them to catalogue keys, and checks every used key exists. Does not translate.
---

# Wire new UI text

Read the `llm-localizator` skill first for the ask-first rules. Wiring edits source and
the source catalogue, so you need the user's yes unless they asked you to localize the
change.

## Steps

1. See what is hardcoded:
   ```bash
   llm-localizator agent-hardcoded --status
   llm-localizator agent-hardcoded
   ```
   The second command prints the strings with file, line and confidence. High and medium
   hits are almost always UI copy.
2. For each string:
   - Add the key and its English text to the **source** catalogue first. Name keys
     `area.element.purpose`, in lowercase with dots (`settings.save.button`).
   - Reference it from code with a literal key (`i18n.t('settings.save.button')`), or in
     markup with `data-i18n="…"` (and `data-i18n-title`, `-placeholder`, `-aria-label`, `-alt`).
   - Counts and choices use ICU: `{n, plural, one {# file} other {# files}}`. Never build
     `n + ' files'`, and never join translated fragments.
3. A hit that is not UI copy gets a recorded reason, not silence:
   ```bash
   llm-localizator scan-decide ignore --ids <id> --note "log line"
   ```
4. Check:
   ```bash
   llm-localizator check-keys
   llm-localizator validate
   ```

## Stays literal

Brand and product names; code identifiers, commands, file names, URLs; unit symbols and
numbers; user and server data; logs and debug text; language self-names in a picker.

## Done when

- `check-keys` exits 0.
- `agent-hardcoded` leaves no high or medium hit undecided.
- `validate` shows no errors in the source locale.

Then tell the user the new keys exist only in English. Translating them is a separate
step that needs their yes (`l10n-add-language`, or `translate`).
