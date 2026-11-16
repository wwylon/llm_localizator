## Practice: Thai, Lao, Khmer, Burmese

## For people

- No spaces between words: the median string is one or two “words”. Do not rely on spaces to measure length or to wrap lines. Let the platform break lines (CSS `word-break`, `overflow-wrap`, ICU line breaking); do not insert your own breaks.
- Sentence ends are weak or absent in Thai (spaces separate clauses); Khmer `។` and Burmese `။` end about a quarter of strings.
- Combining marks (tone marks, vowels) make up 55 to 92 percent of the text. Cut only at grapheme boundaries.
- Fonts need script coverage and enough line height for stacked marks.
- Plurals: one form (`other`). Use classifiers/words that do not change with the number.
- Latin product names and numbers stay as they are; put a space around them only if the style requires it.

## For agents

- Do not require spaces, ASCII punctuation or letter case to decide that a string is prose.
- Do not truncate by character count; use grapheme clusters.
- One plural category (`other`) is correct; V03 does not expect `one`. Only Thai has a full profile; Khmer, Lao and Burmese use defaults until profiles are added.
