# Remote content API

File catalogues keep one source language in `.llm-localize.toml`. Text that
lives in another project's database does not. That project hosts a small HTTP
API. llm_localizator calls it. The two sides do not share a disk, and the review
UI on `127.0.0.1` is not this API.

See [ADR-34](decisions/ADR-34-remote-content-api.md).

## Config

```toml
[collections.live]
kind = "remote"
```

On the machine that runs llm_localizator:

| Variable | Role |
|----------|------|
| `LLM_LOCALIZE_CONTENT_URL` | Base URL, any host. Example: `https://app.internal` |
| `LLM_LOCALIZE_CONTENT_TOKEN` | Bearer token. Never put this in the toml |

Target locales and models stay in the toml. The API does not choose the model.

## Read

`GET {base}/v1/units?limit=100&cursor=`

`Authorization: Bearer <token>`

```json
{
  "units": [
    {
      "id": "club/018f.../description",
      "source_locale": "pl",
      "source_text": "Turniej dla początkujących.",
      "translate": true,
      "note": "club description",
      "targets": {
        "en": { "status": "missing" },
        "de": { "status": "stale", "text": "...", "src_sha": "abc123abc123" }
      }
    }
  ],
  "next_cursor": null
}
```

`source_locale` is required. `translate: false` is a name that must stay as
written (skipped, not missing). `src_sha` is `sha256(source_text)` hex, first
12 characters — the same frozen `src_hash` file catalogues use. A mismatch is
stale. `human` and `human_verified` are a lock.

The engine asks for every catalogue target, plus the catalogue source language.
That source language cannot also be a file-catalogue target, but a unit written
in Polish still needs an English translation. Cells are:

| Status | Meaning |
|--------|---------|
| `source` | This target is the author's language. Not a gap. |
| `skipped` | `translate` is false, or the source text is empty. |
| `missing` | No row for this locale. |
| `stale` | `src_sha` does not match the current source. A human row with a bad hash stays locked. |
| `machine` | Pipeline wrote it, and the hash matches. |
| `human` | Owner or admin override. Not overwritten unless `--force`. |

```bash
llm-localizator status --collection live
llm-localizator status --collection live --missing
```

```
live: 1 unit(s)
live: 1 unit(s)  missing=2 stale=0 machine=0 human=0 skipped=0 source=1
  club/018f.../description  source=pl
    en missing
    de missing
    pl source
```

`--missing` prints only the gap lines. `--format json` returns `counts` and
`units` instead of the file-catalogue locale table. A missing URL or token
exits 1 and names the environment variable. It does not fall back to English.

## Write

`PUT {base}/v1/units/{id}/{locale}`

```json
{
  "text": "...",
  "src_sha": "0123456789ab",
  "source_locale": "pl",
  "provider": "ollama",
  "model": "qwen2.5:7b",
  "status": "machine"
}
```

`llm-localizator translate --collection live` translates from `source_locale`
into the catalogue targets and, when that is a different language, into the
catalogue source language. It does not pivot through English. It does not
write the author's own language, a skipped name, or a human row. `--force`
is the only way to overwrite a human row. `--dry-run` lists the writes and
sends nothing.

When `tq` is on `PATH`, `translate` (not `run-translate`) queues the job.
The blueprint must allow `--collection`. Regenerate it, or `tq add` the
current file, so an older registration accepts the flag. `run-translate
--collection live` does the work in the foreground.

## What the other project implements

The engine does not open the database and does not know table names. The
project exposes the two routes above, on a host the model machine can reach
(LAN, VPN, or an SSH tunnel). It decides which fields are units. Chat and
other text that stays in the language it was sent in is simply not listed.
A name that must not change is `translate: false`.

State stays in the project's side-tables. The engine does not copy it into
`.llm-state`. `human` / `human_verified` must survive a later PUT unless the
body asks to overwrite; the engine does not send that PUT unless `--force`.

Bridge does not host this API yet. Its in-process translator still calls
Ollama directly.
