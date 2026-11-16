# Adding a parser

The list of source languages and message standards lives in
`llm_localizator/core/languages.py`. This page is the procedure. It does not copy
that list. [adding_localization.md](adding_localization.md) is for translating
a project, not for extending the engine.

A programming language and a message standard are different. A Python project
may store ICU JSON. `[catalog] standard` is checked against the catalogue
format, not against the scan language. `po` and `android-xml` may only use
`icu`, because those adapters already return ICU from `load`.

## Another programming language

Hardcoded-string scan.

1. Add a row in `llm_localizator/core/languages.py`: id, extensions, comment
   markers, quote style, and the standard ids that are usual for that language.
   The usual-standards list is a hint. It is not a config error.
2. Ordinary source is picked up by `llm_localizator/scan/literals.py`. A new file
   under `llm_localizator/scan/` is only for a framework call-site parser such as
   `t()` or `i18n.t()`, registered in `llm_localizator/scan/__init__.py`.
3. Add one case to `tests/scan/test_languages.py`: one prose hit, and one
   comment or single-word miss. No network, no subprocess, no model.

Do not add the extensions to `next_intl.py` or `raw_js.py`. Those modules read
the registry.

`[scan] adapter = "source"` scans every row. `next-intl` and `raw-js` keep
their own files and also walk the literal languages in `src_dirs`.

## Another message standard

Placeholders, plurals, and other text that must be copied unchanged.

1. Add `llm_localizator/core/standards/<id>.py` with `tokens`, `syntax_error`,
   `plural_categories`, and `missing_plural_keys`. Standards with no plurals
   return `None` from `plural_categories` and `[]` from `missing_plural_keys`.
   Do not convert the stored string to ICU here. gettext and Android already
   do that in their catalog adapters.
2. Register the id in `llm_localizator/core/standards/__init__.py` and add a
   `StandardInfo` row in `llm_localizator/core/languages.py`. Do not add a branch
   in `validate.py`.
3. Add one case to `tests/core/test_standards.py`: a valid string, a broken
   token (V16), and a localized string that drops a token (V02). If the
   standard has plurals, one missing category (V03).
4. Set `[catalog] standard` to the id. An id the catalogue format does not
   allow is a config error.

`validate_translation` compares `tokens(source)` with `tokens(translated)`.
The ICU placeholder mask and ICU span splitting run only when the standard is
`icu`. For every other standard the prompt lists the tokens and says to copy
them unchanged.
