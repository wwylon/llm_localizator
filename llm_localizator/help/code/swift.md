# iOS and macOS (Swift, Objective-C): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `swift` | basic |
| `objc` | basic |
| `xmlui` | supported |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `Text(`, `Button(`, `Label(`, `TextField(`, `Toggle(`, `.navigationTitle(`, `.alert(`, `UIAlertController(`, `title:`, `message:`, `placeholder:`, `.text =`.

Catalogue formats (`[catalog] format`): `xcstrings`, `ios-strings`, `ios-stringsdict`.
<!-- /generated:code-facts -->

## For people

- SwiftUI `Text("Hello")` already looks the text up as a key in the string catalogue, so it is translatable once the catalogue has the entry.
  The scanner still lists it because nobody has checked that the entry exists. Use `String(localized: "…")` for text outside views and
  `NSLocalizedString` in older code.
- Use one `Localizable.xcstrings` (Xcode 15 and later) or `.strings` plus `.stringsdict`. Plurals belong in the catalogue (variations), not in `if count == 1`.
- Write whole sentences with `%@`, `%lld` or `%1$@` placeholders. Give each string a comment that tells the translator where it appears.
- Do not format numbers or dates into strings by hand; use `FormatStyle`, `Measurement` and `Date.FormatStyle` so the device language decides.
- Use `leading`/`trailing`, never `left`/`right`; SwiftUI mirrors for right-to-left languages automatically.
- Storyboard and xib text (`.storyboard`, `.xib`) is text too.

## For agents

1. Scan with `llm-localizator agent-hardcoded`. Routed calls (`NSLocalizedString`, `String(localized:)`) are not reported; `Text("…")` and the sinks above are.
2. Skip `#Preview` blocks, enum raw values, accessibility identifiers and logging; the scanner already does.
3. Fix by adding a catalogue entry and using `String(localized:)`; run `llm-localizator adopt`, then `llm-localizator validate`.
4. Keep format specifiers (`%@`, `%lld`, `%1$@`) exactly as in the source when you `llm-localizator set` a translation (V02).
5. An `.xcstrings` file holds every locale; edit through `set` so stamps and states stay correct.
