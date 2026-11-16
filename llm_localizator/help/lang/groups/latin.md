## Practice: Latin-script languages

## For people

- The same letters can be capital or lower case in different positions: month, day and language names are lower case in Spanish, Catalan, Finnish and Polish.
  Do not force capitals when a translation looks "wrong" next to English.
- Accents and special letters (`ł ś ž ğ ø ß`) are part of the word. Save files as UTF-8 and normalise to NFC.
- Spanish opens questions and exclamations with `¿` and `¡`. French puts a space (often a no-break or narrow no-break space) before `? ! : ;` and uses `« »`. Those spaces are correct.
- German capitalises nouns and makes long compounds; allow 30 to 40 percent more room than English. Finnish and Hungarian also grow.
- One-word labels are common (15 to 24 percent of strings): give translators context for words such as “Open”, “Post”, “Light”.
- Formal or informal “you” differs (tu/vous, du/Sie, ty/Pan): choose one register for the whole product.

## For agents

- Do not “fix” no-break spaces before `? ! : ;` in French; V34 expects them.
- Keep placeholders (`{name}`, `%s`, `%1$s`) and ICU plural keywords (`one`, `few`, `many`, `other`) untranslated; plural categories vary (Polish needs four, French and Portuguese add `many`).
- A lone lower-case word is normal text in these languages, not code.
- Set `register` once; V40 warns when pronouns mix registers.
