## Practice: Indic scripts (Hindi, Marathi, Nepali, Bengali, Tamil and others)

## For people

- Vowel signs and the virama are combining marks: 86 to 93 percent of the characters in a typical string are marks or letters that combine. Never cut a word by characters; cut only at grapheme boundaries.
- The sentence end is `।` (danda) in Hindi, Marathi, Nepali and Bengali (about 24 percent of strings); Tamil uses `.`.
- Fonts matter: use a font that covers the script (Noto Sans Devanagari, Bengali, Tamil) so conjuncts render.
- Native digits exist but apps mostly show ASCII digits; follow the platform formatting.
- Word spaces are used; text length is close to English or somewhat longer.
- Latin product names and units inside strings stay Latin.

## For agents

- Count text length in grapheme clusters, not code points, when you check limits.
- Do not normalise away combining marks; keep NFC.
- Plural forms: Hindi, Bengali, Marathi and Nepali use `one` and `other`; Tamil `one` and `other`. Check the profile table above.
