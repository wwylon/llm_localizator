## Practice: right-to-left languages (Arabic, Hebrew, Persian, Urdu, Thaana)

## For people

- Mirror the layout: use `start`/`end` (CSS logical properties, Android `start`/`end`, Swift `leading`/`trailing`) and set the document direction to `rtl`.
  Mirror icons that show direction (arrows, back buttons) but not icons of real objects, play buttons or clocks.
- Digits: apps usually keep ASCII digits (native digits are under 1.3 percent of strings). Let the platform format numbers.
- Punctuation: Arabic uses `؟ ، ؛`; Urdu ends sentences with `۔`. Persian uses the zero-width non-joiner (U+200C) inside words in about 28 percent of strings; it is part of the spelling.
- Latin words, numbers and placeholders inside RTL text can jump around. Isolate them (`<bdi>`, `dir="auto"`, Unicode isolates) when a name or number appears in a sentence.
- Do not put text in images; mirrored images are hard to fix.
- Text length is similar to English or 10 to 50 percent longer (Arabic); test short and long.

## For agents

- Zero-width joiners and bidirectional marks (U+200C, U+200D, U+200E, U+200F, U+2066 to U+2069) are valid content: keep them, do not strip them as “invisible junk”.
- Keep placeholders such as `{name}` as they are, even when they look reversed in a terminal.
- V34 checks Arabic punctuation; Arabic needs six plural forms (zero, one, two, few, many, other); Hebrew has `one`, `two`, `many`, `other`; Persian and Urdu have two.
- Run `llm-localizator validate --check-layout` for expansion and overflow on RTL locales.
