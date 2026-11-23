# Template engines (Jinja, ERB, Handlebars, Razor, Freemarker, Blade): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `jinja` | basic |
| `erb` | supported |
| `handlebars` | basic |
| `gotmpl` | basic |
| `razor` | basic |
| `freemarker` | basic |

Calls recognised as already translated: `$_`, `$format`, `$formatMessage`, `$t`, `L`, `_`, `__`, `formatMessage`, `getTranslations`, `gettext`, `gettext_lazy`, `i18n._`, `i18n.__`, `i18n.__n`, `i18n.t`, `i18next.t`, `intl.formatMessage`, `ngettext`, `npgettext`, `pgettext`, `props.t`, `t`, `this.$t`, `this.L`, `this.props.t`, `tr`, `translate`, `uiLocale.t`, `uiT`, `useTranslations`.

Catalogue formats (`[catalog] format`): `po`, `json-flat`.
<!-- /generated:code-facts -->

## For people

- Plain words between tags are shown to a person: `<h1>Welcome</h1>`, `<button>Save</button>`, and attributes `title`, `placeholder`, `alt`, `aria-label`.
- Use the engine's translate tag or function: Jinja `{% trans %}` / `_()`, ERB `t('.key')`, Handlebars helper `{{t "key"}}`, Razor `@Localizer["…"]`,
  Freemarker `<@spring.message "key"/>`, Blade `@lang('…')`.
- Put variables inside one message (`{% trans name=user %}Hello {{ name }}{% endtrans %}`); never split a sentence around a variable.
- Keep HTML out of translated text where possible; if inline tags are needed (`<b>`), keep them as named tags that translators must preserve (V27 checks them).

## For agents

1. Scan: `llm-localizator agent-hardcoded`. Template delimiters (`<% %>`, `{{ }}`, `{% %}`) are blanked and the remaining markup is read like HTML.
   Text already inside a translate tag or function is skipped.
2. A string split by an expression is reported as one message with a placeholder.
3. Fix by moving the sentence to the catalogue and calling the translate function; run `llm-localizator adopt`, then `llm-localizator validate`.
4. HAML, Slim, Pug, Astro and MDX are not scanned; `agent-hardcoded` lists such files under “NOT scanned”.
