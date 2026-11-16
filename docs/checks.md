# Validation checks (V-codes)

Every finding from `llm-localizator validate` (and the web UI) carries a V-code.
*Error* findings reject a translation; *warning* findings are advisory.

| Code | Severity | Meaning | How to fix |
|------|----------|---------|-----------|
| <a id="v01"></a>V01 | error | Key missing from a target locale | Translate the key |
| <a id="v02"></a>V02 | error | Placeholder set differs from source | Restore the missing / remove the extra placeholder |
| <a id="v03"></a>V03 | error | Plural lost, or required CLDR plural categories missing | Add every category the locale requires |
| <a id="v04"></a>V04 | error | Glossary: do-not-translate term dropped or forbidden variant used | Use the glossary form |
| <a id="v05"></a>V05 | error | Empty, over-long, or unexpected-newline output | Retranslate |
| <a id="v06"></a>V06 | warning | Translation identical to source | Translate, or mark `intentional` |
| <a id="v07"></a>V07 | warning | Stale: source changed since translation | Retranslate |
| <a id="v08"></a>V08 | warning | Structure signature no longer matches source | Retranslate; run `migrate-state` if source is unchanged |
| <a id="v09"></a>V09 | warning | Exceeds `maxChars` budget | Shorten |
| <a id="v13"></a>V13 | warning | Approved glossary term absent (inflected forms for pl/ar are accepted by stem match) | Use the approved term |
| <a id="v14"></a>V14 | warning | Length outside the locale expansion band (uses rendered display width; opt-in via `--check-expansion`) | Check for truncation or padding |
| <a id="v17"></a>V17 | warning | Leading/trailing whitespace differs from source | Match source whitespace |
| <a id="v21"></a>V21 | warning | Unexpected script / Latin-only output | Check the model used the target script |
| <a id="v22"></a>V22 | warning | `maxChars` budget exceeded | Shorten |
| <a id="v23"></a>V23 | warning | Word count far from source | Check for omission or padding |
| <a id="v24"></a>V24 | warning | Short form diverges from `fullKey` sibling | Align the two |
| <a id="v25"></a>V25 | warning | Suspicious digraphs | Review spelling |
| <a id="v26"></a>V26 | warning | Differs from a high-score TM exact match | Prefer the TM text |
| <a id="v27"></a>V27 | error | HTML tag structure differs from source | Restore tags |
| <a id="v32"></a>V32 | error | A verbatim literal from the source (URL, email, `snake_case` identifier) is missing | Copy it verbatim |
| <a id="v33"></a>V33 | warning | Two or more English stopwords in a non-English translation. Words that are ordinary in the target language (Italian "a", Dutch "is") are ignored. Only with `--semantic` | Translate the leftover English |
| <a id="v34"></a>V34 | warning | A typography rule of the target language is violated, e.g. fr: space before `: ; ! ?`; es: opening `¿ ¡`; el: `;` as question mark; ar: `؟ ؛ ،`; zh/ja: full-width punctuation; de-CH: no `ß`. Rules live in the language's profile. Runs on every `validate` | Fix punctuation/spacing |
| <a id="v43"></a>V43 | error | Agent or model artefact: the whole value wrapped in quotes ("Zapisz") or a `[key:…]` trailer left in the text | Strip the quotes or trailer; `cycle --repair` or `set` |
| <a id="v45"></a>V45 | warning | A grammar heuristic of the target language fires, e.g. pl: "dwa gracze" (people after 2–4 take "dwóch graczy"), "5 pliki" (5+ takes the genitive "5 plików"). Rules live in the language's profile (`grammar_checks`); the same profile's `grammar_prompt` goes to the translate and judge prompts, so most agreement errors are caught by the judge (`grammar_error`) instead | Fix the agreement, or rerun `improve` |
| <a id="v46"></a>V46 | error | Prompt leak: a source of one or two words (outside placeholders) became six or more words, or a short label grew past 2.2x + 15 characters. The model echoed prompt or domain text, key/context annotations (`[klucz: …]`), or explained the term. ICU plurals are exempt | Retranslate; for placeholder frames give the key a context note |
| <a id="v49"></a>V49 | error | Project description leaked: the output carries two or more distinctive words of `[prompt] domain` that the source lacks (the model echoed the app description, often translated around its proper nouns) | Retranslate; `cycle --repair` |
| <a id="v50"></a>V50 | error | Invented markup: `**`, `__` or backticks absent from the source, or text moved outside a whole-ICU message | Retranslate or `set` the plain text |
| <a id="v51"></a>V51 | error | A leading `~ ≈ ± < > ×` was dropped or spelled out ("Około {t}"); the normalizer restores the common spellings | Keep the symbol |
| <a id="v48"></a>V48 | warning | One glossary term is rendered several ways across keys (for example "bid" as zapowiedź, licytacja and oferta). Reported per term with the keys using a minority rendering; `term-report --json` lists them | Use the approved term, or the majority rendering when none is approved |
| <a id="v47"></a>V47 | error | ICU structure changed: an argument's kind differs (`select` became `plural`), an ICU argument was dropped, or a `select`'s branch keys differ from the source | Restore the source's ICU structure; only plural categories may differ by locale |
| <a id="v35"></a>V35 | warning | A source string reads as a fragment of a longer sentence (ends in a conjunction, comma or colon, or starts with a preposition) | Make it one sentence with placeholders |
| <a id="v36"></a>V36 | warning | Short source strings end with a full stop in some places and not in others; the rarer style is flagged | Pick one convention |
| <a id="v37"></a>V37 | warning | Lists use the serial comma in some places and not in others; the rarer style is flagged | Pick one convention |
| <a id="v42"></a>V42 | warning | An inline do-not-translate element (`translate="no"` or `class="notranslate"`) of the source is missing or changed in the translation. The whole element, tags and content, must appear verbatim. Translate and improve keep these elements out of the model's reach, so this mostly catches hand edits and imports | Restore the element exactly as in the source |
| <a id="v41"></a>V41 | warning | A source key that no scanned code references (opt-in: `validate --unused`; needs `[scan]`). Plural-suffixed keys count as used when their base key is. Keys matching `[scan] unused_allow` are skipped | Delete the key, or add it to `unused_allow` if it is built dynamically |
| <a id="v40"></a>V40 | warning | A pronoun of the other register appears (e.g. German `du` when `register = "formal"`). Runs only when a register is set explicitly in `[prompt]` or `[prompt.styles.<locale>]`; languages without pronoun markers (everything but de, fr, pl) are skipped | Use the configured form of address |
| <a id="v39"></a>V39 | error | A backslash in the translation that the source does not have: the text was cut or an escape leaked in (typically an agent-written CSV with `\,`) | Retype the text; import quotes commas and unescapes `\,` for you |
| <a id="v38"></a>V38 | warning | Decimal mark or date order does not match locale (opt-in) | Localise the number/date |
| <a id="v98"></a>V98 | warning | More than 10% of a target namespace's keys do not exist in the source (a flattened or re-nested file shows up here) | Check the target file for extra or flattened keys |
| <a id="v99"></a>V99 | warning | Target namespace holds under half of the source keys | Check for a truncated or partial catalogue file |

Measured on a production card-game catalogue (2026-09-29, hand-labelled samples of 60): V13 fired 562 times
across pl and ar and about 62% were false positives (case, Polish endings, Arabic article and plural).
After the matcher fix it fires 268 times, about 23% false positives, mostly verbs (`bid` as
"licytuj") and Arabic broken plurals. Both are still above the 5% gate, so V13 stays advisory.
V14 fires on 42% of keys (gate 10%), so it stays opt-in. The V13 hits that are real are mostly
untranslated or truncated strings.

Changing V13 to blocking or V14 to default-on waits on measurement. Run
`python scripts/measure_validation.py --project <name> --locales pl,ar --out v13.csv`, label the
`verdict` column (`ok` or `fp`), and re-run with `--labelled v13.csv`. Gates: V13 false-positive
rate under 5%; V14 firing on under 10% of keys.

Incremental runs: `llm-localizator validate --diff-only` skips keys that validated
clean last time with identical text, context, state signatures, glossary and check
flags (cache: `<state_dir>/.validate-cache/<locale>.json`). Keys with findings are
always re-checked. Not tracked: translation-memory changes (V26) — run without
`--diff-only` after TM edits.

Source-change history: state records keep `src_text`; when a key is retranslated
after its English changed, the history event carries `prev_src` / `next_src`
(`prevSource` / `nextSource` in the web history API). Keys translated before this
change have no `src_text`, so their first re-translation records no old text.

Language rules (V13 stem matching, V14 bands, V25, V33, V34, V38, V40, V45) come from the language
profiles in `llm_localizator/core/locales/`; see [adding-a-language.md](adding-a-language.md).

Notes:
- V32 is blocking, so it only covers things that must never change: URLs, emails and
  `snake_case` identifiers. Acronyms such as "OK" are not checked because they are
  routinely localised.
- Translator-context changes (`note`, `screen`, `maxChars`) are tracked through an
  optional `context_sha` in state records (`catalog.state.make_entry`).

## Normalizer repairs

Before the checks, model output is cleaned (`core/normalize.py`); every repair is followed by the full gate:
`first_line` (one-line source, explanation under the answer), `quotes` and `icu_quotes` (wrapping quotes),
`plural_fill` (plural categories the locale needs, copied from `other` when no branch prints `#`),
`ellipsis`, `symbol` (a leading `~` spelled out) and `case` (first letter follows the source). ADR-117,
ADR-130, ADR-137. A key whose translation a person approved in its context entry
(`context-note --approve`) skips the model entirely.

## Score dimensions

Every quality score stores what it was made of (`ScoreStore` entry `dimensions`, shown as
chips in the editor's quality card):

| Dimension | Meaning |
|-----------|---------|
| `placeholder_ok` | Placeholders and plural categories match the source |
| `glossary_ok` | No glossary problem (a blocking one makes the score 0.0) |
| `script_ok` | No foreign or unexpected script |
| `length_ok` | Within `maxChars`; only present when the key has a limit |
| `bt_overlap` | Back-translation token overlap, when a back-translation ran |
| `consistency` | Agreement between multi-sample candidates (`[quality] multi_sample >= 2`); below 0.80 adds a `low-consistency` signal |

A judge adds its own dimensions (`semantic`, `fluency`, ...). `improve` keeps the old
translation unless the new one is better: a clear score win, or inside a 0.02 tolerance more
satisfied dimensions, or a fixed hard failure. Per-locale cut: `[quality.thresholds]`.

Projects can re-grade any check except V02, V03, V27 and V39 with `[validate.severity]` ([configuration](configuration.md#validateseverity)); the table above lists the defaults.
