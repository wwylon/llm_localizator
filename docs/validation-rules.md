# Validation rules

`llm-localizator validate` runs every check below. None needs an LLM.

**Errors** mean the translation is broken and would render incorrectly. During
translation they cause the candidate to be discarded and the previous value
kept, leaving the key stale for the next run. **Warnings** are advisory.

Exit codes: `0` clean, `1` errors, `2` warnings only, `64` usage error.
`--strict` turns 2 into 1.

## Errors

| ID | Check | Fires when |
|----|-------|-----------|
| V01 | Missing key | The source has a key the target locale does not |
| V02 | Placeholder mismatch | The translation drops a placeholder the source has, or invents one it does not |
| V03 | Plural categories incomplete | The source is an ICU plural and the translation omits a CLDR category the target language requires |
| V04 | Glossary violation (blocking) | A do-not-translate term vanished, or an explicitly forbidden variant was used |
| V05 | Output shape | The translation is over `max(6 × source, 200)` characters (the model explained itself), contains newlines the source lacks, or is empty/whitespace-only |
| V16 | Source message syntax | The source string is not valid for `[catalog] standard` (unclosed token, or a plural form that standard does not have) |
| V27 | HTML tag integrity | The source contains HTML tags and the translation drops or invents tags. Not gated by `--semantic` |

### V02 — placeholder mismatch

Which tokens count depends on `[catalog] standard`. The default is ICU
(`{name}`, `{n, plural, ...}`). `printf`, `brace`, `i18next`, `go-template`,
and `laravel` compare their own tokens. `po` and `android-xml` are already ICU
after load, so they stay on `icu`. See [adding-a-parser.md](adding-a-parser.md).

Extraction for ICU is brace-depth aware. In `{n, plural, one {# trick} other {# tricks}}`
only `n` is a placeholder; branch bodies are not scanned. This matters for
languages whose plural branches are single words — Arabic `two {عضوان}` is one
Unicode token, and a naive `\{(\w+)\}` regex reads it as a placeholder named
`عضوان`.

### V03 — plural categories

Required sets come from CLDR: Polish needs `one/few/many/other`, Arabic needs all
six, Japanese needs only `other`.

ICU explicit-value selectors satisfy the equivalent category: a translation using
`=0` satisfies a requirement for `zero`, and `=1` satisfies `one`. `=0` is in
fact the stronger construct — it matches exactly zero, whereas `zero` is a
grammatical class.

### V04 — blocking glossary rules

Two rules block, because both are exact string facts:

- a term in `doNotTranslate` appears in the source but not the output;
- a string listed in `<locale>_forbidden` appears in the output.

Both are **conditional on the source actually containing the glossary term**.
Without that gate, any homonym trips the check: bridge's glossary forbids Arabic
`عرض` as a rendering of *bid*, but the same word ordinarily means *view*, so
"Public view only" was reported as a bid mistranslation.

Word boundaries use `(?<!\w)term(?!\w)`, not `\b`. Python's `\b` is defined
against `\w`, and for Arabic, Hebrew, and CJK the resulting positions are wrong —
the search silently fails, so glossary rules never fire at all. For genuinely
unsegmented scripts (Chinese, Japanese, Thai, Lao, Khmer, Burmese) no boundary
concept exists, and matching falls back to plain substring containment.

## Warnings

| ID | Check | Fires when |
|----|-------|-----------|
| V06 | Untranslated | The target value is byte-identical to the source |
| V07 | Stale | The recorded source hash no longer matches the current source |
| V08 | Structurally stale | The source's ICU *shape* changed, so the old translation is actively wrong rather than merely dated |
| V09 | `maxChars` exceeded | The translation is longer than a budget declared in a context note |
| V10 | Naive plural | The source looks like a counted noun (`{n} tricks`) without ICU plural syntax |
| V11 | Counted noun, no context | A numeric placeholder with no context note, so a translator cannot tell what is being counted |
| V12 | Orphan key | The target has a key the source no longer has; it is pruned on the next write |
| V13 | Approved term absent | The glossary has an approved translation for a term the source uses, and it does not appear in the output |
| V14 | Expansion band | The length ratio falls outside the locale's expected band — **opt-in**, see below |
| V18 | Duplicate source | The same source text appears on another key. One warning names every key |
| V19 | Placeholder, no context note | The source has a placeholder and the key has no context note. A sentence with no note stays silent |
| V20 | Raw HTML in a plain message | The source contains an HTML tag and the context note does not mark the key as HTML |

### Semantic / advisory (opt-in)

Enable all of these with CLI `--semantic`, or individually from Operations → Validate
(Length / Script / Digraphs checkboxes).

| ID | Check | Gate |
|----|-------|------|
| V17 | Whitespace / end-punctuation parity | `--semantic` |
| V21 | Unexpected script / leftover Latin | `--semantic` or Script |
| V22 | `maxChars` via detailed path | `--semantic` (V09 always runs) |
| V23 | Word-count band | `--semantic` or Length |
| V24 | fullKey coherence | `--semantic` |
| V25 | Suspicious digraphs (stacked diacritics / garble) | `--semantic` or Digraphs |
| V28 | Screenshot layout QA | `--check-layout` when context `screen`/`image` resolves |
| V30 | Same English source, different translations | `--semantic` |
| V31 | Similar English sources, divergent translations | `--semantic` |

**V21** covers three script-family sub-checks (message text distinguishes them):

- *unexpected script* — e.g. CJK inside `ar` / Cyrillic inside `pl` (also a translate hard-gate)
- *latin not in source* — Latin runs or `SCREAMING_SNAKE` identifiers in non-Latin locales that are not present in the English source (e.g. `التournaments`)
- *latin-only* — UI string with no letters in the expected script

**V30 / V31** use a catalogue coherence index: exact `src_hash` groups (V30) and English `semantic_overlap` neighbours (V31). Exact same-source siblings are also injected into translate prompts; fuzzy neighbours need `[prompt] catalogue_semantic = true`.

V26 is advisory: live text ≠ high-score TM exact for the same source+context.
V28 is advisory: `core.layout_qa` (maxChars, expansion band, script profiles,
PNG IHDR heuristics). Capture is consumer-owned — see
[visual-findings.md](visual-findings.md).

Soft quality signals (used by the auto-score / improve loop):

| Signal | Effect |
|--------|--------|
| Identical to English source (multi-word) | Lowers `quality_score`; auto-flags |
| Unexpected script / latin leftover (V21 family) | Lowers `quality_score` |
| Whitespace / end-punctuation mismatch | Small penalty |
| Batch duplicate outputs for distinct sources | Rejected at translate time; single-key fallback |

Scores live in `.llm-scores/<locale>.json`. Low scores feed `llm-localizator improve`.

### V07 vs V08

`src_hash` fingerprints content; `structure_signature` fingerprints ICU shape.
A reworded string changes the first only, and its existing translation is
probably still serviceable while it waits to be redone. A string whose
placeholders or plural categories changed will render wrong immediately, which
is a stronger signal and justifies falling back to the source.

### V13 — why this is not an error

The comparison is exact substring, so it cannot see inflection. Arabic
`التوزيعة` carries a definite-article prefix and will not match an inflected
form; Polish declines. Measured on a production card-game catalogue this rule fires 155 times
across `pl`+`ar` — a mix of genuine mistranslations (the Arabic for *board*
rendered as `لوحة`, a whiteboard, instead of the bridge term) and ordinary
morphology. Real signal, unsafe as a build-breaker.

### V14 — why this is off by default

Enable with `--check-expansion`. `--semantic` also enables V14.

The bands describe how much longer translated text tends to *look*, but the
check compares character counts, and the two diverge badly for scripts that are
visually wide yet character-sparse. Measured on a production card-game catalogue V14 fires on
872 of ~1794 `pl`+`ar` keys, 782 of them "suspiciously short" — almost entirely
because Arabic omits short vowels and ligates, not because anything is wrong.

`maxChars` (V09) stays on, because that is a real constraint from a real UI
element rather than a statistical expectation.

### V38 — number and date order

Enable with `--check-numbers`. It is not part of `--semantic` and it does not
run in the editor's live check.

The check compares a number that uses both `.` and `,` with the same digits
in the source. German `1.234,56` for an English `1,234.56` is fine. Keeping
the English decimal mark in German is a warning. A different amount is not.
A date is a warning only when the same three numbers change order
(`01/02/2026` versus `02/01/2026`).

## Not a catalogue check

| ID | Check | Command |
|----|-------|---------|
| V15 | Hardcoded source string | `llm-localizator agent-hardcoded` (report) or `scan` (usage artefacts) |

A user-visible string that never reaches the catalogue cannot be translated, and
no catalogue check can see it. Detection reads source code, so it lives in the
framework-specific [scanner](scanners.md). The agent report is
`agent-hardcoded`; it does not rewrite the consumer's source. The procedure
is [adding_localization.md](adding_localization.md) §4.

## Scoping

```bash
llm-localizator validate --locale pl --locale ar     # only these locales
llm-localizator validate --namespace auth            # only this namespace
llm-localizator validate --diff-scope $(git diff --name-only origin/main)
llm-localizator validate --format github             # workflow annotations
llm-localizator validate --format json               # machine-readable
```
