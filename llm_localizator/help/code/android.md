# Android (Kotlin and Java): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `kotlin` | basic |
| `java` | basic |
| `xmlui` | supported |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `Toast.makeText(`, `Snackbar.make(`, `Text(`, `.setText(`, `contentDescription =`, `label =`, `hint =`, `.setContentTitle(`.

Catalogue formats (`[catalog] format`): `android-xml`.
<!-- /generated:code-facts -->

## For people

- Put every sentence the user sees in `res/values/strings.xml`; read it with `getString(R.string.key)` or `stringResource(R.string.key)`.
  A literal in `Text("...")`, `Toast.makeText(...)`, `setText("...")` or a layout `android:text="Save"` is hardcoded text.
- One string per whole sentence. Do not build a sentence from pieces (`"Delete " + name + "?"`); use `%1$s` placeholders so
  word order can change.
- Plurals go in `<plurals>` with `quantity` items, never `if (n == 1)`. Languages need up to six forms (Arabic) or one (Chinese).
- Add `translatable="false"` to strings that must not change (brand, keys). Add a `<!-- comment -->` above strings whose meaning is unclear.
- Use `start`/`end` instead of `left`/`right` in layouts and set `android:supportsRtl="true"` so Arabic and Hebrew mirror correctly.
- Text grows: allow 30 to 40 percent more room (German, Finnish) and test with a long language.
- Do not put words in images. Content descriptions are text too.

## For agents

1. Run the scan: `llm-localizator agent-hardcoded` (add `--help` for output formats). Kotlin and Java are read by the shared literal detector
   plus the sink table above; Android layouts (`res/layout/*.xml`) are read for `android:text`, `hint`, `contentDescription`.
2. Treat a hit as real when the literal reaches one of the sinks above or a layout attribute. Skip log calls, `@Preview`, `contentDescription = null`,
   resource ids and test sources: the scanner already does.
3. Fix by adding the string to `values/strings.xml` and replacing the call with `getString(R.string.key)`; then
   `llm-localizator adopt` to stamp the catalogue edit, `llm-localizator validate` to check placeholders (V02) and plurals (V03).
4. Keep `%1$s`-style placeholders and `<plurals>` intact when you `llm-localizator set` a translation.
5. Do not edit `values-<locale>/strings.xml` by hand except through `set`; hand edits need stamps.
