# Ruby and Rails: localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `ruby` | basic |
| `erb` | basic |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `flash[:notice] =`, `render json:`, `.errors.add(`, `notice:`, `alert:`.

Catalogue formats (`[catalog] format`): `yaml`.
<!-- /generated:code-facts -->

## For people

- Use I18n: `t('.title')` (lazy lookup inside a view), `I18n.t('users.show.title')`, files in `config/locales/<locale>.yml`.
  `flash[:notice] = "…"`, `render json: { error: "…" }`, `errors.add(:name, "…")` and text in `.erb` views are hardcoded text.
- Interpolation is `%{name}`; plurals are `one:`/`other:` (and more, per language) under the key. Never build sentences with `+` or `#{}` around translated pieces.
- Keep keys in English and organised by view or model (`activerecord.errors.models…`). Use `l(date)` and `number_to_currency` for formats.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. Ruby is read by the literal detector (basic tier); `.erb` views are read as templates.
2. Fix by adding the key to `config/locales/en.yml` and replacing the literal; `llm-localizator adopt`, then `llm-localizator validate`.
3. YAML catalogues keep nesting; `set` writes the right nested key. Do not rename keys without updating the views.
4. Check coverage with `llm-localizator status`; `check-keys` reads `I18n.t('a.b')` calls with full keys but not lazy `t('.key')` lookups, so unused-key results are partial.
