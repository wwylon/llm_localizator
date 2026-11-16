# Dart and Flutter: localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `dart` | basic |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `Text(`, `SnackBar(`, `AlertDialog(`, `Tooltip(`, `hintText:`, `labelText:`, `title:`, `message:`.

Catalogue formats (`[catalog] format`): `arb`.
<!-- /generated:code-facts -->

## For people

- Use the official `flutter_localizations` with `.arb` files (`lib/l10n/app_en.arb`) and read text as `AppLocalizations.of(context)!.key`
  (or `context.l10n.key`). `Text('Save')`, `SnackBar(content: Text('…'))`, `hintText: '…'` are hardcoded text.
- ARB placeholders use `{name}` and a `placeholders` block with a type; plurals use ICU `{count, plural, one{…} other{…}}`. Do not use `if (count == 1)`.
- Put a `@key` description beside each entry: it is the translator's comment.
- Format numbers and dates with `intl` (`NumberFormat`, `DateFormat`) and the current locale. Use `EdgeInsetsDirectional` and `AlignmentDirectional` so layouts mirror.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. Dart is a basic-tier scanner language (held-out precision too low to call it supported), so review its hits; generated files (`*.g.dart`, `app_localizations*.dart`) are not user text.
2. Fix by adding the key to the template ARB (`app_en.arb`), re-running `flutter gen-l10n`, replacing the literal; then `llm-localizator validate`.
3. Keep placeholder names and the `placeholders` block when you `llm-localizator set` an ARB value (V02); `@key` descriptions are kept as notes.
