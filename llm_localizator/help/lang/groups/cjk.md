## Practice: Chinese, Japanese, Korean

## For people

- Chinese and Japanese have no spaces between words: 78 to 79 percent of strings are one “word”. Korean uses spaces and ASCII punctuation.
- Use full-width punctuation in Chinese and Japanese text (`，。！？：；` and `、`); half-width marks next to Chinese or Japanese letters look wrong. Quotes: `「」` (Japanese, Traditional Chinese) or `“”` (Simplified).
- Labels can be one or two characters (`删`, `예`). They are real text.
- Text is much shorter than English (about 0.5 to 0.8 times) but needs more line height and a font with the right regional forms (Simplified vs Traditional, Japanese vs Chinese glyphs). Set the `lang` attribute so the correct glyphs are used.
- No plural forms (`other` only); no capitals.
- Write Latin words and digits with consistent spacing as the style guide says; do not mix full-width and half-width digits.
- Input methods compose text: do not act on a key press while composition is active (`isComposing`).

## For agents

- V34 flags half-width punctuation after CJK letters; keep file names and code like `設定.json` unchanged.
- Never split a string on spaces to count words. Use the profile's `segmented` flag.
- Chinese variants differ (`zh-Hans`, `zh-Hant`, `zh-HK`, `zh-TW`): do not copy one into another; Traditional Chinese is not a character-by-character conversion.
