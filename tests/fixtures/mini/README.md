# mini fixture

A hand-built, hermetic catalogue. **Authored, not captured** — every file here
encodes a specific edge case, so it must be maintained deliberately (ADR-4).

Layout: `messages/{locale}/{namespace}.json`, source locale `en`.

| Locale | Why it is here |
|--------|----------------|
| `en` | Source |
| `pl` | Four plural categories (`one/few/many/other`); glossary term with a forbidden variant |
| `ar` | Six plural categories; RTL; explicit `=0` selector; the glossary word-boundary case |
| `de` | Missing a namespace file entirely |
| `cs` | Present in the roster with empty state — never translated |

| Case | Where |
|------|-------|
| Nested keys flattened to dotted paths | `en/play.json` → `tactics.claim` |
| ICU plural, all Polish categories | `pl/play.json` → `tricks` |
| ICU plural, all six Arabic categories | `ar/play.json` → `tricks` |
| Explicit `=0` selector satisfying `zero` | `ar/play.json` → `watching` |
| Do-not-translate term preserved | `*/play.json` → `convention` |
| Orphan key absent from source | `pl/play.json` → `removedKey` |
| Untranslated value identical to source | `pl/nav.json` → `home` |
| Naive plural in the source | `en/nav.json` → `unreadCount` |
| Locale missing a whole namespace | `de/` has no `nav.json` |
| Skip key | `en/nav.json` → `brand` |
