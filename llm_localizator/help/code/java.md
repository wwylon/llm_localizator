# Java (Spring, Swing, JavaFX): localization notes

<!-- generated:code-facts -->
| Scanner language | Tier |
|---|---|
| `java` | basic |
| `erb` | basic |

Calls that show text to a person (a literal given to one is reported at medium or high confidence): `JOptionPane.showMessageDialog(`, `Toast.makeText(`, `Snackbar.make(`, `.setText(`, `.setTitle(`, `.setToolTipText(`, `new JLabel(`, `new JButton(`, `.setContentTitle(`.

Catalogue formats (`[catalog] format`): `properties`.
<!-- /generated:code-facts -->

## For people

- Keep text in `messages.properties` (plus `messages_<locale>.properties`) and read it through `ResourceBundle` or Spring's `MessageSource`.
  In Thymeleaf use `#{key}`; in JSP use `<fmt:message key="…"/>`.
- Use `MessageFormat` placeholders (`{0}`, `{1}`) and choice formats or ICU for plurals. Never concatenate sentences.
- Swing and JavaFX: `new JLabel("Save")`, `setText("…")`, `JOptionPane.showMessageDialog(…, "…")` are hardcoded text.
- Properties files are read as UTF-8 only from Java 9 on; older code needs `\uXXXX` escapes. Check which one your runtime uses.
- Use `NumberFormat`, `DateTimeFormatter.ofLocalizedDate` and `Collator` with an explicit `Locale`; use `Locale.ROOT` for machine text.

## For agents

1. Scan: `llm-localizator agent-hardcoded`. Java uses the shared literal detector plus the sink table above; JSP and Freemarker templates are read as templates.
2. A hit is real when the literal reaches a sink above. Annotations (`@Query`, `@RequestMapping`), constants (`static final String`) and logs are skipped.
3. Fix by adding a key to `messages.properties`; run `llm-localizator adopt`, then `llm-localizator validate` (placeholders V02).
4. `.properties` files do not carry comments for translators in the catalogue model: put the context in `context_dir` notes instead.
