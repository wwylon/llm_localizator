# Go (html/template, templ, go-i18n): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `go` | basic |
| `gotmpl` | basic |
| `templ` | basic |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `http.Error(`, `c.JSON(`, `"error":`, `"message":`, `.Render(`, `key.WithHelp(`, `.Title =`, `Label:`.

Catalogue formats (`[catalog] format`): `go-i18n`, `json-flat`.
<!-- /generated:code-facts -->

## For people

- `go-i18n` (`localizer.Localize(&i18n.LocalizeConfig{MessageID: "…"})`), `golang.org/x/text/message` (`p.Sprintf`) or `gotext` are the common choices.
  `http.Error(w, "…", 400)`, `c.JSON(…, gin.H{"error": "…"})` and text in `.gohtml`/`.tmpl`/`.templ` files are hardcoded text.
- go-i18n catalogues are `active.<locale>.json` or TOML with `one`/`other` forms; templates inside messages use `{{.Name}}`.
- Do not translate log messages, error values compared with `errors.Is`, or JSON field names. Translate at the edge (handler or view), not in libraries.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. Go sources, `html/template` files and templ components are read. Server error text is reported only when it reaches a sink above.
2. Fix by adding a message to the catalogue and calling the localizer; `llm-localizator adopt`, then `llm-localizator validate` (`{{.Name}}` placeholders, V02).
3. Keep `{{.Name}}` names exactly as in the source when you `llm-localizator set`.
