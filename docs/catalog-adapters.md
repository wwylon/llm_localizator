# Catalog formats

A catalog adapter presents any on-disk message format as one flat mapping of key
to string, in ICU message syntax. Everything above it — validation, the
translation pipeline, the CLI — sees only that flat ICU form and never learns
what the file on disk actually looks like.

## Supported formats

| `format` | Aliases | Typical layout | Notes in file |
|---|---|---|---|
| `json-nested` | `next-intl`, `react-intl` | `messages/{locale}/{namespace}.json` | no |
| `json-flat` | `i18next` | `public/locales/{locale}/{namespace}.json` | no |
| `yaml` | `vue-i18n`, `rails`, `yml` | `config/locales/{locale}/{namespace}.yml` | no |
| `po` | `gettext` | `locale/{locale}/LC_MESSAGES/{namespace}.po` | **yes** |
| `arb` | `flutter` | `lib/l10n/{namespace}_{locale}.arb` | **yes** |
| `android-xml` | `android` | `res/values-{locale}/{namespace}.xml` | **yes** |
| `ios-strings` | | `{locale}.lproj/{namespace}.strings` | **yes** |
| `ios-stringsdict` | | `{locale}.lproj/Localizable.stringsdict` | no |
| `xcstrings` | | `Localizable.xcstrings` (one file, every locale inline) | **yes** (`comment`) |
| `qt-ts` | `qt`, `linguist` | `translations/app_{locale}.ts` | **yes** (`<extracomment>`) |
| `chrome-messages` | `chrome`, `webextension` | `_locales/{locale}/messages.json` | **yes** (`description`) |
| `xliff` | `xlf` | `i18n/{namespace}.{locale}.xlf` (1.2 or 2.0 per file) | **yes** (`<note>`) |
| `resx` | `dotnet` | `Resources/{namespace}.{locale}.resx` | **yes** |
| `properties` | | `src/main/resources/{namespace}_{locale}.properties` | no |
| `php-array` | `laravel` | `lang/{locale}/{namespace}.php` | no |
| `go-i18n` | | `active.{locale}.json` | no |
| `csv` | | `i18n/{namespace}.csv` | no |
| `multilang-json` | `glossary` | one file, every locale inline | no |

```toml
[catalog]
format = "po"
path = "locale/{locale}/LC_MESSAGES/{namespace}.po"
```

`llm-localizator init` probes for all of these and writes the config for you.

### Single-file projects

Omit `{namespace}` and the whole catalogue is one unnamed namespace. With
`{namespace}`, a slash is a real directory: `messages/en/admin/users.json` is
namespace `admin/users`. The state key is still `{namespace}.{key}`
(`admin/users.signIn`). A dot in the namespace id is rejected, because it would
make that split ambiguous. Nested objects inside one file (`tactics.claim` via
flatten) are a different thing and still work. `skip_namespaces` drops a
namespace and its children from translation; see
[configuration.md](configuration.md).

```toml
path = "locales/{locale}.json"
```

## Notes carried by the file

Three formats store translator guidance alongside the message. Where they do,
that guidance goes into the prompt automatically and the project needs no
sidecar `context_dir`:

- **gettext** — `#.` extracted comments
- **ARB** — the `@key` block's `description`
- **Android** — an XML comment immediately above the resource

When both a native note and a `context_dir` note exist, both are used, native
first.

## Plurals

Everything above the catalog layer speaks ICU. Formats that don't are translated
in both directions by `core/plurals.py`.

| Format | Native plural model |
|---|---|
| `json-*`, `yaml`, `arb` | ICU already — passes through |
| `po` | `msgid_plural` + indexed `msgstr[0..N]` |
| `android-xml` | `<plurals><item quantity="one">` |
| `ios-stringsdict` | `NSStringPluralRuleType` dict with one `%#@var@` token |
| `xcstrings` | `variations.plural.<category>.stringUnit`, one ICU message per key |

Android's `quantity` values *are* the CLDR names, so that mapping is direct.
gettext is the hard one, and worth understanding before trusting it.

### gettext plurals are indexed, not named

A `.po` file numbers its plural forms — `msgstr[0]`, `msgstr[1]` — and a
`Plural-Forms` header gives a C expression mapping a number to a slot. **Which
CLDR category a slot means is convention, not data.** We recover it from the
locale's CLDR category list, the same source the validator uses, so the two
cannot disagree.

### gettext usually has fewer forms than CLDR

Polish is the standard case. CLDR requires `one/few/many/other`; Polish `.po`
files declare `nplurals=3`. The missing category is `other`, which for Polish
covers fractional quantities ("1.5 lewy") that gettext's integer-only expression
cannot select.

Read back naively, such a message would be missing a category the validator
requires, and **every counted noun in the catalogue would fail validation**
through no fault of the translation. So on load, the last slot — gettext's
catch-all, the branch its expression falls through to — is copied into any
required category with no slot of its own.

The consequence, stated plainly: **ICU → po → ICU is lossy.** A distinct `other`
branch collapses into the catch-all text. That is a limit of the format, not
something an adapter can fix. If you need `other` to differ, gettext cannot
express it.

### Placeholders

gettext has no `#`. ICU `#` becomes `%(n)s` on write and back on read, which is
the Python-style named interpolation gettext tooling expects. Android uses `%d`
inside `<item>` bodies, and its positional arguments (`%1$s`) are preserved
untouched — they are not ICU placeholders.

## Round-trip safety

**A write must never destroy a translator's work.** Adapters for formats
carrying content we do not model read the existing file and merge into it.

- **gettext** preserves `#` translator comments, `#.` extracted comments, `#:`
  source references, and obsolete `#~` entries. The `fuzzy` flag is cleared on
  the entries we retranslate, since they are no longer fuzzy.
- **Android** carries `translatable="false"` resources through from the source
  file, and never loads them — so they can never be sent to a model.
- **ARB** carries `@key` metadata blocks into the target bundle.
- **YAML** preserves the file's locale-root convention: a file wrapped in `en:`
  stays wrapped, one that isn't stays flat.

## Format-specific traps handled

- **YAML implicit typing.** `No`, `yes`, `on`, `off`, `1.0`, `null` all parse as
  non-strings. Values are written explicitly quoted, so a translation of "No"
  survives as the string `No`.
- **Android escaping.** Apostrophes and quotes are backslash-escaped; a leading
  `@` or `?` is escaped so it is not read as a resource reference.
- **gettext `msgctxt`.** Two identical English strings with different meanings
  ("Pass" the verb, "Pass" the noun) are distinguished by context. The flat key
  becomes `ctxt\x04msgid`, gettext's own internal convention.
- **Android `<string-array>`.** Each item is the flat key `name[i]`; a missing
  index is written as an empty item so later positions do not shift.
- **`.xcstrings` shapes.** A key without a source-language localization uses the key as its source text, like Xcode. Device or width variations, substitutions and `shouldTranslate: false` entries are skipped on load and left untouched on save; `comment` is the note; the `state` of values you did not change is kept. Plural text outside the plural block is copied into every category.
- **`.stringsdict` shapes.** Only one `%#@var@` plural per key flattens to ICU;
  anything else raises instead of being flattened lossily.
- **PHP arrays.** A tokenizer reads `[...]` and `array(...)`, several pairs per
  line, comments and `.` concatenation. Values it cannot read (function calls,
  constants, heredoc) make load and save raise rather than drop entries.
- **gettext wrapping.** `render_po(entries, width=79)` wraps long strings the way
  `msgmerge` does; the adapter default stays unwrapped.
- **Locale qualifiers.** Android writes `pt-BR` as `values-pt-rBR`; the
  transformation is applied on write and reversed during locale discovery.

## Writing a new adapter

A catalog format is the file shape. The message syntax (`{name}`, `%s`,
`{{name}}`) is a standard, not an adapter. The checklist for a new standard is
[adding-a-parser.md](adding-a-parser.md).

```python
class MyCatalog(Catalog):
    carries_notes = False       # does the file store translator guidance?

    def path_for(self, locale, namespace=None) -> Path: ...
    def namespaces(self) -> list[str]: ...
    def load(self, locale, namespace=None) -> dict[str, str]: ...
    def save(self, locale, namespace, messages) -> None: ...

    # Optional, when the format carries per-key metadata:
    def load_entries(self, locale, namespace=None) -> dict[str, Message]: ...
```

Contract:

- `load` on a **missing** file returns `{}` — a locale not started yet is normal.
- `load` on a **malformed** file raises `ValueError` naming the path — a corrupt
  file must not be silently read as empty.
- `save` creates parent directories.
- `load(save(x)) == x` for anything the format can represent.
- If the format is not ICU-native, convert in `load`/`save` using
  `core.plurals`, so the layers above never see a native plural.

Register it:

```python
# llm_localizator/catalog/__init__.py
_ADAPTERS = {..., "my-format": MyCatalog}
_ALIASES  = {..., "my-framework": "my-format"}
```

`tests/catalog/test_formats.py` runs a shared contract over every registered
format. Add yours to `FORMATS` there and it is held to the same standard as the
rest — that parametrised suite is what makes adapters interchangeable.

## `merge_for_write` — do not override

The base class implements it, and the semantics are load-bearing. Per key, in
precedence order: a fresh translation wins; otherwise an existing translation is
preserved; otherwise the source value is used as a visible fallback. And
structurally, **iteration is over the source**, so keys absent from the source
locale are dropped — that is how deleting an English string prunes every locale,
and it guarantees a target file always has exactly the source's key set.

## `resx` (.NET)

Reads and writes `<data>` string entries and their `<comment>` (the key's note). Typed
entries (images, files), designer metadata (`>>name`, `$name`), resheaders and the schema are
left byte for byte; saving splices the changed strings into the existing text. Use the culture
code in the file name, e.g. `Resources/{namespace}.{locale}.resx`. A culture-neutral
`Strings.resx` is not mapped to the source locale: name the source file `Strings.en.resx`.

## gettext `.pot` templates

When the source locale has no `.po` file but a sibling `.pot` (`locale/en/messages.pot`), the `po` adapter reads the template as the source: each `msgid` is the source text and a plural entry becomes an ICU `one`/`other` message. The template is read-only, so saving the source locale into it raises an error. Target locales are ordinary `.po` files.

## `xliff`

One `.xlf` file per locale. The source-locale file holds the text in `<source>`; a target file holds a copy of the source and the translation in `<target>`. XLIFF 1.2 (`trans-unit`) and 2.0 (`unit`/`segment`) are detected per file; new files are written as 1.2. Saving splices into the existing text: file attributes, notes, `approved` and other attributes, inline markup of unchanged values and `translate="no"` units are kept. A changed target gets `state="translated"`. Inline markup (`<g>`, `<x/>`) is flattened when read, and a value the engine rewrites is plain text. `<note>` is the key's translator note. This is the catalogue format; the `export`/`import` handoff files (ADR-97 changes none of that) stay separate.
