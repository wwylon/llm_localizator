# .NET (WinForms, WPF, MAUI, Blazor, ASP.NET): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `csharp` | basic |
| `razor` | basic |
| `xmlui` | supported |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `MessageBox.Show(`, `DisplayAlert(`, `Title =`, `Text =`, `Content =`, `ToolTip =`, `AddModelError(`.

Catalogue formats (`[catalog] format`): `resx`.
<!-- /generated:code-facts -->

## For people

- Keep text in `.resx` files (`Resources.resx`, `Resources.pl.resx`) and read it with `Resources.Key`, `IStringLocalizer<T>["Key"]` or `x:Uid` in XAML.
  `MessageBox.Show("…")`, `Title = "…"`, `Text="…"` in XAML and plain text in Razor are hardcoded text.
- Use composite format `{0}` placeholders and `string.Format(culture, …)`; never build sentences by concatenation.
- Plurals need real support (ICU through a library, or separate keys); `if (n == 1)` fails for most languages.
- Set `CultureInfo` for dates and numbers; never hand-format them. Use `FlowDirection` for right-to-left.
- Resource names are identifiers: keep them stable and in English.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. C#, Razor (`.cshtml`, `.razor`) and XAML are read; resource files themselves are recognised as catalogues and skipped.
2. Fix by adding a `.resx` entry and replacing the literal; then `llm-localizator adopt` and `llm-localizator validate`.
3. Keep `{0}` indexes in the same order as the source when you use `llm-localizator set` (V02).
4. Do not hand-edit generated `Resources.Designer.cs`.
