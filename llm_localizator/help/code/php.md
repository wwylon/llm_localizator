# PHP (Laravel, Symfony, WordPress): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `php` | basic |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `echo`, `->with(`, `->flash(`, `abort(`, `->json(`, `'message' =>`.

Catalogue formats (`[catalog] format`): `php-array`, `po`.
<!-- /generated:code-facts -->

## For people

- Laravel: `__('messages.welcome')` or `trans_choice` for plurals, Blade `@lang('…')`, files in `lang/<locale>/*.php` or `lang/<locale>.json`.
  WordPress: `__('Text', 'domain')`, `_e`, `esc_html__`, `_n` and a `.po` file per language.
- Text after `echo`, in `->with('status', '…')`, `abort(…, '…')` or `'message' => '…'` is shown to a person; route it.
- Placeholders: Laravel `:name`, WordPress `%s` or `%1$s`. Never concatenate translated pieces.
- Escape on output (`esc_html__`, `{{ }}` in Blade) after translating, not before.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. PHP is read by the literal detector plus the sink table above; Blade (`.blade.php`) markup text is read as a template.
   A lone word right after `echo` is deliberately not reported (it is usually HTML or a variable).
2. Fix by adding a key to `lang/en/…php` (or a `msgid` for WordPress); `llm-localizator adopt`, then `llm-localizator validate` (Laravel `:name` placeholders, V02).
3. `php-array` catalogues keep nesting; do not flatten keys by hand.
