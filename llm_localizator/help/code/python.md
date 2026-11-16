# Python (Django, Flask, FastAPI): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `python` | basic |

Calls recognised as already translated: `$_`, `$format`, `$formatMessage`, `$t`, `L`, `_`, `__`, `formatMessage`, `getTranslations`, `gettext`, `gettext_lazy`, `i18n._`, `i18n.__`, `i18n.__n`, `i18n.t`, `i18next.t`, `intl.formatMessage`, `ngettext`, `npgettext`, `pgettext`, `props.t`, `t`, `this.$t`, `this.L`, `this.props.t`, `tr`, `translate`, `uiLocale.t`, `uiT`, `useTranslations`.

Catalogue formats (`[catalog] format`): `po`, `json-flat`, `yaml`.
<!-- /generated:code-facts -->

## For people

- Use `gettext` (`_("Save")`, `ngettext` for plurals, `pgettext` when the same English word means different things). In Django, use
  `gettext_lazy` for text defined at import time (model fields, form labels).
- Text in `flash(...)`, `messages.error(...)`, `raise ValidationError("...")`, `abort(404, "...")` and in a template is shown to a person: route it.
- Never build sentences with `+` or an f-string around a translated piece. Use `_("Hello %(name)s") % {"name": name}` so translators can reorder.
- Do not translate log messages, exception text meant for developers, SQL or dictionary keys.
- Keep translator comments (`# Translators: …`) above ambiguous strings; they reach the `.po` file.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. Python is read as syntax (calls such as `flash`, `render`, `Response`, form labels), not by regex, so docstrings, logs and
   dictionary keys are not reported.
2. After a fix, `llm-localizator check-keys` compares the keys used in code with the catalogue (`.po` or JSON).
3. In `.po` files keep `msgctxt`, `%(name)s` placeholders and the `Plural-Forms` header; `llm-localizator validate` checks them (V02, V03).
4. Do not edit `.po` by hand without `llm-localizator adopt` afterwards.
