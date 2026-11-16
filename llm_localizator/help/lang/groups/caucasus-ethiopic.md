## Practice: Armenian, Georgian, Ethiopic

## For people

- Armenian ends sentences with `։`; Ethiopic has its own full stop `።`. Georgian has no letter case, so “title case” does not exist.
- Words are separated by spaces. About 40 percent of Armenian strings are one word: give translators context.
- Fonts need explicit script support; check rendering on every platform you ship.
- Sentence marks of any script count as sentence ends, so do not replace them with `.`.

## For agents

- Do not require capital letters or ASCII punctuation to treat a string as text.
- Keep the script's own punctuation unchanged.
