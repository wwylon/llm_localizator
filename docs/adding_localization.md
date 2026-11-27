# Localizing a project with llm_localizator

This guide covers everything needed to add, maintain, and extend translations
in any project using llm_localizator. It is written for agents and developers who
are new to the tool.

---

## Concepts

| Term | Meaning |
|---|---|
| **source locale** | The language the project is authored in (almost always `en`) |
| **target locale** | A language being translated into (`pl`, `de`, `ar`, …) |
| **namespace** | A logical group of strings — one file per namespace per locale (e.g. `auth`, `nav`). Single-file projects use one unnamed namespace |
| **state file** | `.llm-state/<locale>.json` — records what was translated, when, and by which model. Not a cache. Lives in the data home (`~/.llm_localize/data/<name>/`) by default; see [section 14](#14-state-files-and-git) |
| **status** | One of: `missing`, `stale`, `untranslated`, `machine`, `llm_reviewed`, `human`, `needs_better_model` |
| **stale** | The source string changed after the translation was produced — needs retranslating |

---

## 1. Install

```bash
pip install llm_localizator          # or: pip install -e . from the repo
```

Requires Python 3.11+. Translation uses Ollama by default (local LLM, no cloud
spend). Ollama must be running with at least one model pulled:

```bash
ollama pull llama3.2
```

---

## 2. Initialize a project

Run once in the project root:

```bash
llm-localizator init .
```

This auto-detects the message format from files already on disk and writes
`.llm-localize.toml`. If auto-detection fails (no files yet, or an unusual
layout), pass the format and path explicitly:

```bash
llm-localizator init . --format json-flat --path "locales/{locale}.json"
```

### Supported formats

| Format | Typical stack | Path template |
|---|---|---|
| `json-nested` | Next.js / next-intl / react-intl | `messages/{locale}/{namespace}.json` |
| `json-flat` | i18next, plain JS, no build step | `locales/{locale}.json` |
| `arb` | Flutter | `lib/l10n/{namespace}_{locale}.arb` |
| `android-xml` | Android | `res/values-{locale}/{namespace}.xml` |
| `po` | Python/Django, GNU gettext | `locale/{locale}/LC_MESSAGES/{namespace}.po` |
| `yaml` | Ruby on Rails, vue-i18n | `config/locales/{locale}/{namespace}.yml` |

### The config file

`.llm-localize.toml` is the contract between the project and llm_localizator. A
typical config:

```toml
[project]
name = "myapp"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl", "de", "ar", "ja"]

[locales.models]
default = "llama3.2"
ar = "qwen2.5:7b"     # Arabic benefits from a larger model
ja = "qwen2.5:7b"     # so does Japanese

[provider]
kind = "ollama"
url = "http://localhost:11434"

[prompt]
domain = "a project management web application"
glossary = "i18n/glossary.json"   # or a directory: global.json + <domain>.json
# tm_dir = ".llm-tm"              # exact/near translation memory (default)
context_dir = "i18n/context"
```

**`domain`** is the single most important field — one noun phrase describing
what the app does. It anchors register and tone across all locales.

**`[locales.models]`** — model selection per language matters:

| Language group | Languages | Recommended | Why |
|---|---|---|---|
| Latin-script European | pl, de, fr, es, it, pt, cs, sk, ro, nl, sv, da, fi, no, hu, tr, id, vi | `llama3.2` | Well represented in Western LLM training; fast 3B model is sufficient |
| Cyrillic | ru, uk | `llama3.2` | Good coverage in most Western models |
| Greek | el | `llama3.2` | Adequate coverage |
| Arabic / Hebrew | ar, he | `qwen2.5:7b` | Right-to-left script, complex morphology, diacritics; Qwen trains on far more Arabic data than Llama |
| CJK | zh, zh-TW, ja, ko | `qwen2.5:7b` | Qwen (Alibaba) is trained on vastly more Chinese/Japanese/Korean data |
| Devanagari | hi | `qwen2.5:7b` | Complex script handling |
| Thai | th | `qwen2.5:7b` | No word spaces; complex script |

If `qwen2.5:7b` is unavailable, `phi3:mini` (2.7B) is a viable fallback for Latin
scripts but noticeably weaker on Arabic and CJK. Larger variants (`qwen2.5:14b`,
`mistral:7b`) improve quality at the cost of throughput — useful for high-stakes
copy like legal text or marketing.

**`[prompt] domain`** anchors register, tone, and vocabulary in the model
prompt. Write it as a user-facing description: `"a task queue monitoring UI"`,
`"a card game for bridge players"`, `"an e-commerce checkout flow"`.

For day-one setup and the self-localize (dogfood) loop, prefer
[getting-started.md](getting-started.md). Coding agents: [agents.md](agents.md).

---

## 3. Register the project

`llm-localizator init` writes `.llm-localize.toml` and, unless you pass
`--no-register`, adds the project to `~/.llm_localize/projects.yaml`. There is
no `register` command. Run `init` again with `--force` if the project root
moves.

---

## 4. Mark strings for translation

Every user-visible string must live in the source locale file, not inline in
code. Replace hardcoded strings with `t()` calls and add the key to the source
file.

**Next.js / next-intl (json-nested)**:
```tsx
// WRONG
<button>Sign in</button>

// CORRECT — key lives in messages/en/auth.json
const t = useTranslations("auth");
<button>{t("signIn")}</button>
```

**Plain JS with a flat JSON runtime**:
```js
// WRONG
el.textContent = "No tasks found";

// CORRECT — key lives in locales/en.json
el.textContent = i18n.t("noTasksFound");
```

**Source file** (`messages/en/auth.json` or `locales/en.json`):
```json
{
  "signIn": "Sign in",
  "noTasksFound": "No tasks found"
}
```

A namespace may be a directory. `messages/en/admin/users.json` is the namespace
`admin/users`, not a dot inside the key. The state key stays
`admin/users.signIn` (ADR-7). Dots are not allowed in the namespace id.

### Find the strings that are still hardcoded

The engine does not rewrite source and does not invent keys (ADR-32). Full
ordered checklist: [consumer-localization-checklist.md](consumer-localization-checklist.md).

```bash
# from the consumer root — aim for 0 high/medium parts
llm-localizator agent-hardcoded myapp --split auto --out-dir reports/hardcoded --refresh
llm-localizator agent-hardcoded myapp --show-low --out-dir reports/hardcoded-low --refresh
llm-localizator scan-decide myapp ignore --confidence low    # protocol/API/docs noise
# agent wires t() / i18n.t / data-i18n / uiT in source
llm-localizator scan-decide myapp accept --confidence high
llm-localizator apply myapp --confirm                        # EN keys when mode=manual
llm-localizator translate myapp
```

Painted English the static scanner misses: `pseudo --locale en-XX` then browse
or crawl (dogfood: `hardcoded-hunt` + `[web] qa_locales`; SPA consumers: storage
mode crawl — see the checklist). Leave `--llm` off on `agent-hardcoded` unless
you want the slow second pass. `scan --strict` never calls a model. Details:
[scanners.md](scanners.md), [agents.md](agents.md).

### Collections other than the message catalogue

`[catalog]` is the collection `messages`. `[documents]` is read as the
collection `legal`. Further roots go under `[collections.<name>]`. Omitting
`--collection` means `messages`, so existing commands keep their meaning.
`llm-localizator discover` only proposes; copy a confirmed root into the config.
Help articles stay out of the key table: the web UI lists path, coverage, and
stale, and opens one file. Markdown and HTML are shown as source plus a
preview. The stored file is what is translated and exported. ICU plurals on
the key table show a sample for each category (Polish `n=1,2,5,1.5` is
one/few/many/other). Adding another preview format is a renderer registration,
not a table change. See [scanners.md](scanners.md) and
[configuration.md](configuration.md).

### Text that lives in a database

User-authored text (a club description, a tournament name) is not a file and
often is not English. The project that owns the database hosts the content
API. This engine calls it from the machine that has the model. Declare
`[collections.<name>]` with `kind = "remote"`, and set
`LLM_LOCALIZE_CONTENT_URL` and `LLM_LOCALIZE_CONTENT_TOKEN` on that machine.
Do not put the token in the toml, and do not point this at `llm-localizator web`.

```bash
llm-localizator status myapp --collection live
llm-localizator translate myapp --collection live --dry-run
```

Each unit's `source_locale` is the author's language. A name with
`translate: false` is skipped. The contract, including what the other project
must implement, is [content-api.md](content-api.md).

### Counted nouns need plural syntax

Never write `"{n} errors"` — many languages have 3–6 plural forms. Use ICU
plural syntax in the source:

```json
{
  "errorCount": "{n, plural, one {# error} other {# errors}}"
}
```

Translators (human or LLM) then supply the forms their language needs. Plain
`{n}` stays fine for identifiers that aren't counted quantities: `Step {n} of
{total}`, `Level {n}`.

### Keep placeholders intact

Placeholders `{name}`, `{n}`, `{total}` must appear verbatim in both source
and translated strings. The tool validates this and rejects any translation
that drops or renames a placeholder.

---

## 5. Check status

```bash
llm-localizator status myapp
```

Output:

```
myapp — 4 locales

locale   total   done    stale   missing  coverage
──────── ─────── ─────── ─────── ──────── ────────
pl         412     409       1       2      99.3%
de         412     410       0       2      99.5%
ar         412     401       3       8      97.3%
ja         412     380      12      20      92.2%
```

List each problem key:

```bash
llm-localizator status myapp --missing
# [missing] auth.signIn
# [stale]   nav.dashboard
```

### Agent / Cursor localization

If catalogues were edited outside llm-localizator (or you want an agent to finish
a locale), adopt existing strings into state first, then emit a backlog prompt:

```bash
llm-localizator adopt myapp --locales es
llm-localizator agent-backlog myapp --locales es          # paste into Cursor
# agent writes apps/web/messages/es/…
llm-localizator adopt myapp --locales es
llm-localizator status myapp
```

`adopt` only stamps catalogue values that lack state (ADR-19 agent
provenance). `agent-backlog` lists `missing` / `empty` / `no_state` / `stale`
keys with English source text. See [cli.md](cli.md).

---

## 6. Translate

```bash
# Translate all missing/stale keys in all target locales
llm-localizator translate myapp

# One locale only
llm-localizator translate myapp --locales pl

# Force retranslate even keys that are already done
llm-localizator translate myapp --force

# Dry run — show what would happen, translate nothing
llm-localizator translate myapp --dry-run
```

Translation is incremental: only missing and stale keys are sent to the model.
Running `translate` twice is safe (idempotent on already-translated keys). Exact
hits in `[prompt] tm_dir` (default `.llm-tm`) skip the LLM; near matches only
seed few-shot examples. Glossary may be a single JSON file or a directory
(`global.json` + domain files) — see [configuration.md](configuration.md).

### Queue via taskqueue (recommended for GPU projects)

If the project uses taskqueue, queue the translation job instead of blocking
the terminal:

```bash
tq add --project myapp localize_ui_messages
```

The job runs on the GPU worker. Check progress with `llm-localizator status`.

---

## 7. Review and edit

```bash
llm-localizator web myapp     # opens http://127.0.0.1:8770
```

The web interface shows:
- **Coverage cards** — per-locale percentage done
- **Namespace selector** — browse one namespace or all at once
- **Compare columns** — view two locales side by side
- **Status filter** — show only missing / stale / has problems / etc.
- **Inline editing** — click a translation to edit; saves on blur

The save path runs the same validation as the model: a hand-typed string that
drops a placeholder is refused with the reason shown inline.

Click **↺** to reload state from disk after a translate job finishes, without
restarting the server.

---

## 8. Context notes — guiding the model

Context notes are the most reliable way to prevent mistranslations. They appear
in the model's prompt alongside the string, and in the web UI below the source
text.

### Sidecar directory (works with all formats)

Create `i18n/context/<namespace>.json` (or `i18n/context/.json` for
single-namespace projects):

```json
{
  "signIn": {
    "note": "Button label on the login screen. Imperative verb. Keep under 12 characters.",
    "maxChars": 12
  },
  "errorCount": {
    "note": "Inline error summary shown below a form. Must match the badge label in validation.badgeLabel."
  },
  "dashboard": {
    "note": "Navigation item. Noun, not verb. This is a proper noun in this app — keep as 'Dashboard' in languages that use Latin script."
  }
}
```

Point the config at it:
```toml
[prompt]
context_dir = "i18n/context"
```

### Inline notes (ARB, gettext-po, XLIFF)

These formats carry notes natively and no separate directory is needed:

**ARB** (`lib/l10n/app_en.arb`):
```json
{
  "signIn": "Sign in",
  "@signIn": { "description": "Button label. Imperative, max 12 chars." }
}
```

**gettext** (`locale/en/LC_MESSAGES/app.po`):
```
#. Button label. Imperative, max 12 chars.
msgid "signIn"
msgstr "Sign in"
```

### What makes a good note

| Do | Don't |
|---|---|
| State the UI context: `"button label"`, `"table column header"`, `"error message"` | Describe the English word (`"signIn means to authenticate"`) |
| Give length constraints: `"max 15 chars — fits a mobile button"` | Leave constrained strings without a note |
| Name the grammatical form: `"imperative verb"`, `"noun phrase"`, `"adjective"` | Assume the model can infer grammar from context |
| Cross-reference related strings: `"must match status.badgeLabel"` | Leave consistency requirements implicit |
| Explicitly list do-not-translate terms: `"keep 'Glicko' exactly as written"` | Rely on the glossary alone for strings with critical terms |

---

## 9. Strings that should not be translated

Some strings are correctly identical to the source in every locale:
- Proper nouns that happen to have no native form (`"Glicko"`, `"llm-localizator"`)
- Technical identifiers used in UI but not translated by convention (`"GPU"`, `"API"`, `"JSON"`)
- Strings whose English value is the universal standard (`"OK"`, `"HTTP 404"`)

Left alone, these show as **untranslated** (yellow warning). There are two ways to handle them:

### Option A — `skip_keys` (key excluded from all locale files)

```toml
[catalog]
skip_keys = ["brand", "appName", "version"]
skip_namespaces = ["admin"]
```

`skip_keys` matches one key in any namespace. `skip_namespaces` matches that
namespace and every child (`admin` skips `admin/users`). `--namespace` does
not override either. `[scan] exclude` only skips source directories; it does
not stop `translate`.

The key is completely excluded from translation status and web UI. Target locale files
will not have it — the app must handle fallback to English at runtime. Use this for
keys that will always be the same and that your i18n runtime handles via fallback.

### Option B — "keep as-is" in the web UI (key stays in locale files, marked intentional)

In the web UI, rows with status `untranslated` show a **keep as-is** button next to
the status badge. Clicking it:
1. Writes the source value to the target locale file (if absent)
2. Records `status: intentional` in the state file
3. Changes the badge from yellow `untranslated` to green `intentional`
4. Counts the key as done in coverage

The mark survives re-translation — `translate` skips `intentional` keys the same way
it skips `human`-edited ones. If the source string later changes, the key is
automatically marked stale and must be re-confirmed.

Use **Option A** when the key should not appear in locale files at all. Use **Option B**
when the key must appear (because your runtime reads it directly without fallback) and
the English value is correct for all languages.

## 10. Glossary

Project-wide terms that must be handled consistently across all strings:

```json
{
  "doNotTranslate": ["Glicko", "IMP", "GPU", "API"],
  "terms": {
    "dashboard": { "pl": "pulpit" }
  }
}
```

```toml
[prompt]
glossary = "i18n/glossary.json"
```

`"doNotTranslate"` entries must appear unchanged in every translation. A `terms`
entry supplies the approved translation for that locale. The model is shown the
matching terms in every prompt so violations are caught before writing.

---

## 11. Adding a new language

Add the language with the CLI, or use **+ Locale** in the review UI
(`POST /api/add-locale`). Either appends it to `[locales] targets` in
`.llm-localize.toml`; regional variants such as `fr-CA` work too. Then translate:

```bash
llm-localizator add-locale --locale de
llm-localizator run-translate --locales de
```

Not sure what is left to do? `llm-localizator guide` shows the next step.

**From the web UI:**
Click **+ Locale**, pick the language from the dropdown, pick a model, click
**Add & queue**. The TOML is patched automatically.

**Checklist for adding a locale:**
1. Add the locale to `[locales] targets` (or **+ Locale** in the web UI)
2. Wire the locale into the app's runtime (add to routing config, middleware, etc.)
3. `llm-localizator translate myapp --locales <code>`
4. `llm-localizator web myapp` → review machine translations, fix problems manually
5. Optional: consumer Playwright capture → `llm-localizator ingest-visual` →
   `validate --check-layout` (see [visual-findings.md](visual-findings.md))
6. `llm-localizator status myapp` shows coverage; `llm-localizator validate myapp --strict` must pass before shipping

---

## 12. Keeping translations current

After any edit to the source locale file:

- **Wording tweak (same meaning)** — just re-run `translate`. Unchanged source
  strings are not retranslated.
- **Meaning change** — edit the source and run `translate` again. Staleness follows the stored source hash (`src_sha`). There is no `.invalidate` file.
- **Added placeholder or plural category** — the tool detects structural changes
  automatically and marks affected translations stale.

---

## 13. CI gate

```yaml
- name: Check translation coverage
  run: llm-localizator validate myapp --strict
```

`validate` exits non-zero when a target locale is missing keys (V01) or has
errors; `--strict` also fails on warnings such as stale translations (V07).
`status --missing` prints one `[reason] namespace.key` line per problem — pipe it
to a PR annotation action to post inline comments on the diff. `status` itself
only reports; it never fails the build.

---

## 14. State files and git

`.llm-state/<locale>.json` records the source hash and model for every
translated key. It is not a build artifact or cache: without it every run
would retranslate the whole catalogue, and "stale" detection would not work.

Where it lives depends on `data_home` (ADR-112, see
[configuration.md](configuration.md)):

- `data_home = "engine"` (default): state, history, scores and TM live under
  `~/.llm_localize/data/<name>/` on this machine, not in your repository.
  Back that folder up; do not commit it.
- `data_home = "project"`: state lives beside the config as `.llm-state/`.
  Commit it, and do not add it to `.gitignore`. Use this when CI needs the
  state (staleness gates such as `check` or `run-sync --diff`): a fresh CI
  runner has no data home, so it would see every key as untracked.

---

## 15. Quick reference

```bash
llm-localizator init .                        # set up a new project (registers unless --no-register)
llm-localizator add-locale myapp --locale de  # append a target locale to the config
llm-localizator status myapp                  # coverage summary
llm-localizator status myapp --missing        # list each problem key
llm-localizator status myapp --collection live  # database units; see content-api.md
llm-localizator adopt myapp --locales es      # stamp catalogue-only keys into state
llm-localizator agent-backlog myapp --locales es  # Cursor-ready key list
llm-localizator translate myapp               # translate missing/stale keys
llm-localizator translate myapp --locales pl  # one locale only
llm-localizator translate myapp --force       # retranslate everything
llm-localizator web myapp                     # open review UI at :8770
llm-localizator migrate-state myapp           # fix state file after tool upgrade
```

**Large catalogues (~3k keys):** use `llm-localizator status` and the queue
(see [taskqueue-integration.md](taskqueue-integration.md)) rather than one long session.
