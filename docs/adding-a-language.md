# Adding a language

Everything the tool knows about a language lives in one file:
`llm_localizator/core/locales/<code>.py`. Nothing about a language is kept
anywhere else. This page is the procedure. [adding-a-parser.md](adding-a-parser.md)
is for *programming* languages and message standards, which are a different thing.

## What a profile holds

A profile is a `LocaleProfile` (see `core/locales/base.py`). Set only what
differs from the defaults.

| Field | Meaning |
|-------|---------|
| `code`, `name` | BCP-47 code and the English name used in prompts |
| `script`, `direction`, `segmented` | Writing system, `ltr`/`rtl`, `False` when words are not separated by spaces (zh, ja, th, km, lo, my) |
| `plural_categories`, `plural_example`, `gettext_plural_forms` | CLDR plural categories a translation must supply, an optional worked ICU example for the prompt, and the `Plural-Forms` header for new `.po` files |
| `expansion_band` | Expected translated length as a fraction of English (V14) |
| `hyphenate` | Insert soft hyphens in long compounds (de, nl, fi) |
| `decimal_mark` | `","` or `"."`; `None` skips the number-format check (V38) |
| `suspicious_digraphs` | Diacritic pairs that mark model garble (V25) |
| `inflects` | Approved glossary terms may appear inflected (V13 matches a stem) |
| `stopwords` | Common function words, used to spot leftovers of this language (V33) |
| `english_word_collisions` | English stopwords that are ordinary words in this language, so V33 ignores them |
| `typography_prompt` | One or two sentences sent to the model with every prompt |
| `informal_prompt` / `formal_prompt`, `informal_marker` / `formal_marker` | Optional formality wording sent to the model when a register is set explicitly, and pronoun patterns for the V40 warning |
| `typography_checks` | Rules checked after translation (V34); each carries a passing and a failing example |
| `grammar_prompt` | Short rule lines (cases, agreement, numerals, UI verb moods, phrasing around `{placeholders}`) sent with every translate, improve and judge prompt. Keep it under ~10 lines: it is in every request |
| `grammar_examples` | 5–10 vetted source→target pairs that show those rules; sent as worked examples |
| `grammar_checks` | Reliable grammar heuristics checked after translation (V45), same shape as typography rules. Only add a rule that never fires on correct text; the judge covers the rest |
| `selectable` | Offered in language pickers (a bare `pt` is not; `pt-PT` and `pt-BR` are) |
| `aliases` | Extra codes that resolve here, e.g. `zh-Hant` |

## Steps

1. Create `llm_localizator/core/locales/<code>.py`. Use `is_.py` and `id_.py` for
   codes that clash with Python names; the trailing underscore is stripped.

   ```python
   """Norwegian (Bokmal)."""

   from __future__ import annotations

   from .base import LocaleProfile

   PROFILE = LocaleProfile(
       code="nb",
       name="Norwegian (Bokmal)",
       decimal_mark=",",
       english_word_collisions=frozenset({"for", "is", "to"}),
       typography_prompt="Use « » for quotation marks.",
   )
   ```

2. Import the module and add it to `_MODULES` in `core/locales/__init__.py`.
   The order is the order of language pickers. A guard test fails if a file in
   the folder is not registered.
3. For regional differences, add a `VARIANTS` map in the same file and build each
   entry with `dataclasses.replace(PROFILE, ...)`. Lookup is exact code, then the
   code without its last subtag (`fr-BE` finds `fr`), then a harmless default.
   Look at `fr.py` (fr-CA), `pt.py` (pt-PT, pt-BR) and `zh.py` (zh-TW).
4. Typography rules use `regex_check(...)`, or `TypographyCheck(..., predicate=...)`
   when a regex cannot express it (see `es.py`). **Every rule needs a `good` and a
   `bad` example.** Importing the package fails if `bad` does not fire or `good`
   does. Prefer rules that cannot fire on times (`10:30`), URLs, or file names.
5. Add a row to the per-language cases in `tests/core/test_locale_profiles.py`
   for any rule you wrote, using real text.

Do not add a per-language table anywhere else, and do not import a language
constant from another module. Ask for `profile(locale)`.

## What changes when the profile exists

- Prompts and the LQS judge gain the language's grammar rules and examples (`grammar_prompt`, `grammar_examples`).
- Prompts gain the language's typography guidance and, for hard plural systems,
  a worked plural example.
- `validate` applies its typography rules (V34), plural categories, length band,
  digraph and number-format checks.
- Editors get the right direction and font for the script.
- `guide`, `init`, and the web language picker list it.
