## Practice: Cyrillic and Greek

## For people

- About 12 to 14 percent of strings mix in a Latin word (brand, unit, protocol such as `IPv4`). Keep these Latin; do not transliterate product names.
- Greek writes its question mark as `;` (U+037E or `;`). That is punctuation, not code.
- Russian, Ukrainian and Bulgarian use `« »` (Russian also `„ “`), a no-break space before a dash, and `ё` is often written `е`: follow the product style.
- Plurals have three or four forms (Russian: one, few, many, other). Never build “N items” by appending an `s`-like suffix.
- Cases change word endings: a term placed after a number or a preposition may need another form; avoid inserting variables into sentence middles.

## For agents

- Mixed-script strings are normal; V33 (leftover English) looks for English stop words, not for any Latin letters.
- Keep ICU keywords and placeholder names in Latin letters; translate only the text between braces.
- Do not convert Greek `;` to `?` or the reverse.
