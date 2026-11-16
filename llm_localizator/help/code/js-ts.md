# JavaScript and TypeScript (React, Vue, Svelte, Next.js, Node): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `javascript` | supported |
| `typescript` | basic |
| `tsx` | supported |
| `vue` | supported |
| `svelte` | supported |
| `html` | supported |

Calls recognised as already translated: `$_`, `$format`, `$formatMessage`, `$t`, `L`, `_`, `__`, `formatMessage`, `getTranslations`, `gettext`, `gettext_lazy`, `i18n._`, `i18n.__`, `i18n.__n`, `i18n.t`, `i18next.t`, `intl.formatMessage`, `ngettext`, `npgettext`, `pgettext`, `props.t`, `t`, `this.$t`, `this.L`, `this.props.t`, `tr`, `translate`, `uiLocale.t`, `uiT`, `useTranslations`.

Catalogue formats (`[catalog] format`): `json-nested`, `json-flat`.
<!-- /generated:code-facts -->

## For people

- Pick one library and use it everywhere: `i18next`/`react-i18next`, `react-intl` (FormatJS), `next-intl`, `vue-i18n` or `svelte-i18n`.
  Text in JSX, in a Vue or Svelte template, in an attribute (`title`, `placeholder`, `aria-label`, `alt`) or in an `alert(...)` call that is not
  passed through the library is hardcoded text.
- Keep keys stable and meaningful (`settings.profile.save`). Do not use the English sentence as a key unless the library (gettext style) expects it.
- Use the library's interpolation (`{name}`, `{{name}}`) and its plural syntax (ICU `{n, plural, one {…} other {…}}` or i18next `_one`/`_other`).
  Never build sentences with `+` or template literals.
- Format numbers, dates and lists with `Intl.NumberFormat`, `Intl.DateTimeFormat`, `Intl.ListFormat`; set `dir="rtl"` on the document for Arabic and Hebrew
  and use CSS logical properties (`margin-inline-start`).
- Do not translate identifiers, CSS classes, route names or keys of data. Do not store words in images or in SVG text.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. JSX, Vue and Svelte templates, HTML files and plain JS/TS literals are read. Calls listed above as "already translated" are skipped.
2. Check wiring after edits: `llm-localizator check-keys` lists keys used in code but missing from the catalogue, and keys that are never used.
3. When you add a key, add the English source first, then `llm-localizator translate` (or `set`), then `llm-localizator validate`.
4. Keep every placeholder name and ICU branch when you use `set` (V02, V03, V47); do not translate placeholder names.
5. A string in a template tag with a variable inside (`Hello {{ user }}`) is one message: replace it with one key with a placeholder, not two keys.
