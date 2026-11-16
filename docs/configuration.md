# Configuration — `.llm-localize.toml`

One file per project, at the project's own repository root. It is the source of
truth (ADR-3); the registry at `~/.llm_localize/projects.yaml` only maps a name
to a location. Catalogue, glossary, context, and document **source** paths are
relative to the directory containing the file. Engine sidecars default under
`~/.llm_localize/data/<name>/` ([ADR-112](decisions/ADR-112-engine-data-home.md)).

Commands find it three ways, in order: a registered project name, an explicit
`--config PATH`, or an upward walk from the current directory. The third means
CI and fresh clones work with no machine-level state (catalogues still live in
the clone; sidecars follow `data_home`).

## Field reference

### `[project]`

| Field | Default | Notes |
|-------|---------|-------|
| `name` | *required* | Registry key and taskqueue project name |
| `source_locale` | `"en"` | The language file catalogues are authored in. Must not appear in `targets`. Remote units carry their own `source_locale` and are not limited to this value. |
| `data_home` | `"engine"` | `engine` stores state/history/scores/TM/review/budget (and related sidecars) under `~/.llm_localize/data/<name>/` (or `$LLM_LOCALIZE_HOME/data/<name>/`). `project` keeps them beside this config (legacy). Catalogues and editorial prompt files always stay in the consumer. |

### `[catalog]`

| Field | Default | Notes |
|-------|---------|-------|
| `format` | `"json-nested"` | Adapter name or framework alias — see below. Validated at load, so a typo fails immediately with the alternatives listed. |
| `path` | `"messages/{locale}/{namespace}.json"` | Template. Must contain `{locale}`; omit `{namespace}` for single-file layouts. |
| `namespaces` | `"*"` | `"*"` discovers them from the source locale; a list restricts. |
| `skip_keys` | `[]` | Keys never translated — brand names, identifiers. |
| `skip_namespaces` | `[]` | Namespace, and every child, never translated. `admin` skips `admin/users`. |
| `standard` | `"icu"` | Message syntax. `po` and `android-xml` may only use `icu`. JSON, YAML, and ARB may use any registered standard. See [adding-a-parser.md](adding-a-parser.md). |

Supported formats, with the aliases you may use instead:

| `format` | Aliases | Typical `path` |
|---|---|---|
| `json-nested` | `next-intl`, `react-intl` | `messages/{locale}/{namespace}.json` |
| `json-flat` | `i18next` | `public/locales/{locale}/{namespace}.json` |
| `yaml` | `vue-i18n`, `rails`, `yml` | `config/locales/{locale}/{namespace}.yml` |
| `po` | `gettext` | `locale/{locale}/LC_MESSAGES/{namespace}.po` |
| `arb` | `flutter` | `lib/l10n/{namespace}_{locale}.arb` |
| `android-xml` | `android` | `res/values-{locale}/{namespace}.xml` |

The `path` template is what makes the tool portable across layouts, and
`llm-localizator init` detects all of the above automatically. Formats that are not
ICU-native (`po`, `android-xml`) have their plurals translated in both
directions — read [catalog-adapters.md](catalog-adapters.md) before relying on
gettext, because gettext declares fewer plural forms than CLDR requires and the
round-trip is lossy in one direction.

`source_branch` (default `"main"`) is the branch source strings are meant to be synced
from. `sync` warns on any other branch and `sync --strict-branch` fails there.

### `[locales]`

| Field | Default | Notes |
|-------|---------|-------|
| `targets` | `[]` | Locales to translate into. |
| `frozen` | `[]` | Subset of `targets` skipped by default LLM sweeps (translate / improve / review / sync / documents / rescore and base taskqueue blueprints). Still appear in status, validate, and the web UI. Explicit `--locales` (or checking a frozen locale in Ops) still runs them. Leave at least one non-frozen target. See [ADR-16](decisions/ADR-16-frozen-locales.md). |
| `asap` | `[]` | Subset of `targets` preferred first in default sweeps (after pivot dependencies). Mutually exclusive with `frozen`. See [ADR-47](decisions/ADR-47-settings-providers-and-asap.md). |
| `pivots` | `{}` | `{ "pt-BR" = "pt-PT" }` translates the variant with the reference supplied as context rather than from the source alone. The reference must itself be a target (or the source locale), and is automatically ordered first in a run. |

### `[locales.models]`

Per-locale model, with `default` as the fallback.

```toml
[locales.models]
default = "llama3.2"
ar = "qwen2.5:7b"     # RTL and CJK need the larger model
```

This table also drives the GPU reservation in a generated taskqueue blueprint,
so a model missing from the VRAM table causes blueprint generation to fail
loudly. See [taskqueue-integration.md](taskqueue-integration.md).

### `[locales.roles.<locale>]`

Optional per-locale translator / judge roles ([ADR-21](decisions/ADR-21-locale-model-roles.md)).
When set, `primary` wins over `[locales.models]` for that locale; `judge` wins
over `[quality] judge_model`.

| Field | Default | Notes |
|-------|---------|-------|
| `primary` | none | Translator for this locale |
| `secondary` | none | Second candidate on high-risk / low-band strings (Ollama-first; sequential load) |
| `judge` | none | Locale-specific LQS judge |
| `prefer_secondary` | `false` | Always spend a secondary candidate for this locale |

```toml
[locales.roles.pl]
primary = "aya-expanse:8b"
secondary = "qwen2.5:7b"
judge = "qwen2.5:14b"
```

`--model` / Ops model override forces one primary and clears secondary for the
run so dual-pass does not fight the pin. **Simultaneous** multi-model VRAM
residency is still out of scope — but when `[quality] score_model` differs from
the translate pin, `run-translate` loads models **sequentially** in one job
(phase A translate → unload pin → phase B batch BT). See
[taskqueue-integration.md](taskqueue-integration.md#deferred-translate-scoring).

A CTranslate2 MADLAD provider is shipped. Select it with `[provider] kind = "ctranslate2"` and `model_path`. The `[provider]` table lists `ctranslate2` among the kinds.

### `[provider]`

| Field | Default | Notes |
|-------|---------|-------|
| `kind` | `"ollama"` | `ollama`, `null` (tests), `ctranslate2` (MADLAD), `anthropic`, `openai`, `deepseek`, or `deepl`. Cloud kinds need env keys, `[privacy] allow_cloud`, and `[budget] monthly_usd > 0`. |
| `model_path` | `""` | CTranslate2 model directory (when `kind = "ctranslate2"`). |
| `url` | `"http://localhost:11434"` | Base URL, no path (Ollama) |
| `keep_alive` | `"30m"` | The 5-minute default evicts the model between locale groups and forces a 13–18 s reload |
| `options` | `{temperature = 0.1, top_p = 0.9, num_gpu = 99}` | Low temperature because translation wants literal output — the 0.8 default is why models invent placeholders. `num_gpu = 99` forces full GPU offload. |
| `timeout_batch_s` | `600` | Batch request |
| `timeout_single_s` | `300` | Per-key fallback |
| `timeout_shorten_s` | `120` | Shorten pass |

Unknown fields in this table are an error, so a typo in a tuning knob fails
loudly instead of being silently ignored.

### `[providers.<id>]`

Optional named endpoint registry (ADR-47). When absent, the loader synthesizes
`id = "default"` from `[provider]`. Each table may set `name`, `kind`, `url`,
`model_path`, and the same tuning fields as `[provider]`. Unset fields inherit
from `[provider]`.

```toml
[providers.local]
name = "Local Ollama"
kind = "ollama"
url = "http://127.0.0.1:11434"

[providers.gpu]
name = "Remote GPU"
kind = "ollama"
url = "http://192.168.1.42:11434"
```

`[locales.providers]` values are provider **ids** when that id exists; otherwise
they remain kind strings (legacy). `provider_for_locale` uses the resolved
entry’s URL and kind. OpenAI-compat / LM Studio is `kind = "openai"` with a
custom `url`.

### `[prompt]`

| Field | Default | Notes |
|-------|---------|-------|
| `domain` | `"a software application"` | One sentence describing the product, injected into every prompt. **The single biggest lever on terminology quality.** |
| `glossary` | none | Path to a glossary JSON **file** or a **directory** (`global.json` + `<domain>.json`). Directory mode injects global + matching domains only (R-10). Terms that match the English source are injected **per string**; the preamble only lists do-not-translate terms present in the batch. |
| `glossary_domains` | `{}` | Namespace → domain name or list; merged with per-key context `domain`. |
| `tm_dir` | `<data_root>/.llm-tm` | Translation memory (exact reuse + near few-shot). See ADR-22; path follows `data_home` (ADR-112). |
| `tm_shared` | none | One path or a list of read-only translation memories searched after the project TM, in order ([ADR-95](decisions/ADR-95-several-shared-tms.md)). |
| `tm_write` | none | One extra memory that also receives human-approved text (never machine output); one memory per client or product line. |
| `tm_semantic` | `false` | Use embedding similarity for TM near matches (n-gram default; MiniLM when `LLM_LOCALIZE_EMBEDDINGS=1`). |
| `catalogue_semantic` | `false` | Inject similar live-catalogue English neighbours as few-shot examples (same embedding stack). Exact same-source siblings are always considered. |
| `context_dir` | none | Directory of `<namespace>.json` translator notes. Optional for `po`/`arb`/`android-xml`. |
| `examples_file` | none | JSON map `{locale: [[source, target], ...]}` of few-shot pairs (max 5 per locale). |
| `register` | `"informal"` | `informal` or `formal` second-person guidance (and DeepL formality). |
| `family` | `"chat"` | Prompt instruction family: `chat` (full rules) or `mt_chat` (shorter, sense-focused). See [ADR-23](decisions/ADR-23-prompt-families.md). |

Optional per-locale style (ADR-38). A locale with no table keeps the global `register`. `notes` is capped at 500 characters and is injected into the prompt preamble.

```toml
[prompt.styles.pl]
register = "formal"
notes = "Use Pan/Pani. Avoid anglicisms."
```

### `[voice]`

Optional. Tells the model what the product is, who reads it and how it should sound ([ADR-68](decisions/ADR-68-voice-section.md)). The lines are added to every translation prompt; a project without `[voice]` gets byte-identical prompts.

| Field | Default | Notes |
|-------|---------|-------|
| `description` | none | What the product is. Max 2000 characters. Same field as `[prompt] description`. |
| `audience` | none | Who reads the text. Max 300 characters. Same field as `[prompt] audience`. |
| `tone` | none | How it should sound, for example `"friendly and direct"`. Max 300 characters. Prompt line `Tone: ...`. |

Setting `description` or `audience` in both `[voice]` and `[prompt]` is a load error. Project config in the web UI writes to `[voice]` once that table holds the key. Guided setup shows an optional "Describe your product's voice" step.

```toml
[voice]
description = "A hotel booking app for business travellers."
audience = "Frequent travellers"
tone = "friendly and direct"
```

### Style presets

Optional ([ADR-89](decisions/ADR-89-style-presets.md)). `[prompt] style_preset` adds one `Style:` line to every prompt: `faithful` (stay close to the source), `fluid` (natural, idiomatic) or `creative` (adapt for impact). `[prompt.style_presets]` overrides it per locale. With no preset the prompts are byte-identical. Changing the default needs a bakeoff ([ADR-12](decisions/ADR-12-local-model-bakeoff-defaults.md)).

```toml
[prompt]
style_preset = "fluid"

[prompt.style_presets]
de = "faithful"
```

### `[locales.prompt_family]`

Optional per-locale override of `[prompt] family`:

```toml
[prompt]
family = "chat"

[locales.prompt_family]
# After a consumer bakeoff, try mt_chat for TranslateGemma-heavy locales.
# pl = "mt_chat"
```

Does not change which model runs — only the instruction shape. CT2/MADLAD
ignores the text prompt entirely (ADR-22).

### `[locales.providers]`

Optional per-locale provider kind override:

```toml
[locales.providers]
ar = "anthropic"   # requires ANTHROPIC_API_KEY and budget.monthly_usd > 0
de = "deepl"       # requires DEEPL_AUTH_KEY
```

**Privacy:** cloud providers receive source UI strings (and the full prompt for
Anthropic, OpenAI, and DeepSeek). Prefer local Ollama unless bakeoff evidence
says otherwise
([ADR-12](decisions/ADR-12-local-model-bakeoff-defaults.md)). Link your
org's DPA before enabling. Keys stay in the environment: `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `DEEPL_AUTH_KEY`.

### `[budget]`

| Field | Default | Notes |
|-------|---------|-------|
| `monthly_usd` | `0` | Cloud stays on the local provider until this is above 0. |
| `mode` | `"on_request"` | `on_request` spends only for `--keys` (translate, improve, review, rescore). `dynamic` may send every due string whose ceiling fits the remainder. |
| `output_expansion` | `2.0` | Output-token multiplier used only for the pre-flight ceiling. |
| `thinking_tokens` | `1024` | Extra output tokens per request for adaptive-thinking models. Not the model's max output. |
| `cloud_batch` | `true` | Prefer Anthropic Message Batches / OpenAI Batch (~50% off) when a cloud translate run has multiple LLM batches. DeepSeek has no Batch API. |
| `rates` | none | Optional per-model overrides (`input` / `output` USD per 1M tokens, or `usd_per_million_chars` for `deepl`). |

`estimate-cost` prints `max_usd` (one request per string) and `batch_usd` (one preamble per batch). The recorded bill is actual token usage (including prompt-cache hits when the vendor reports them), not the ceiling. See [ADR-35](decisions/ADR-35-cloud-cost-and-agent-mcp.md) and [ADR-111](decisions/ADR-111-cloud-token-efficiency.md).

### Cheap cloud models (rough sync list, USD / 1M tokens)

Prefer local Ollama/CT2 when quality is fine. Package Anthropic default is
`claude-haiku-5-5`. Do **not** change `[locales.models]` without an ADR-12
bakeoff — use named `[providers.<id>]`, `--model`, or on_request instead.

| Vendor | Model / product | Sync (approx) | Cache | Async batch |
|--------|-----------------|---------------|-------|-------------|
| Anthropic | `claude-haiku-5-5` | $0.10 / $0.50 (≤100k) | Opt-in `cache_control` | Message Batches **50%** |
| OpenAI | `gpt-5.6-luna` | $0.20 / $1.20; cached in $0.02 | Auto ≥~1024 tokens | Batch **50%** |
| DeepSeek | `deepseek-flash` | Peak miss $0.30 / $1.20; hit $0.006 | Automatic disk KV | None — use off-peak + cache |
| DeepL | Classic MT API | ~$25–27.50 / **1M source chars** | N/A | Up to **50** texts / request |

Portable rules: stable system prefix first, pack strings per call, async Batch
when latency can wait, low/no thinking for bulk MT, meter cache fields into
`actual_usd`. ADR-35 ceilings stay conservative (no assumed cache/batch discount).

### `[quality]`

| Field | Default | Notes |
|-------|---------|-------|
| `threshold` | `0.55` | BT/heuristic cut: below this → flag / improve candidates |
| `thresholds` | none | Per-locale override of `threshold`, a table of `locale = number` (`[quality.thresholds]` then `ar = 0.45`). Keys must be target locales. There are no built-in per-locale defaults: measure first (`llm-localizator bakeoff`), then set the ones you need. Does not change the LQS bands. |
| `band_approve` / `band_flag` / `band_retranslate` | `0.95` / `0.90` / `0.80` | LQS bands when `judge_model` is set (ADR-20). Improve queue uses `band_retranslate` as the cut. **Not** applied to BT Jaccard scores. |
| `judge_risky` | `true` | Judge one- and two-word keys (labels, buttons, frames) with the scoring model when no `judge_model` is set; a short key whose back-translation shares no word with the source is capped at 0.6 (ADR-125) |
| `write_floor` | `0.5` LQS / `0.35` BT | Candidates scoring below this are held as drafts (ADR-91), not written. A rerun of an unchanged source is also held unless it beats the stored score of the current text (ADR-117). |
| `judge_model` | none | Opt-in LQS judge (structured JSON dimensions). Unset keeps BT scoring. |
| `high_risk_patterns` | built-in list | Regexes that trigger a secondary-model candidate when roles.secondary is set. Empty array disables the defaults. |
| `improve_model` | none | Stronger local model for `run-improve` |
| `improve_limit` | `50` | Cap per improve run |
| `improve_skip_rejected` | `true` | Skip keys whose latest history is KEEP (`improve-reject`) or FAIL (`improve-fail`) for the same source, so repeated `--limit` runs rotate through the backlog instead of re-trying the same stuck 100 |
| `improve_reject_cooldown_hours` | `168` | How long that skip lasts (hours). `0` = skip until the source text changes or `--include-rejected`. A later successful `improve` clears the skip |
| `multi_sample` | `1` | When ≥ 2, best-of-N at temperature 0.3 with BT scoring + refine loop (cap 3), for `run-translate`. Also via `run-translate --multi-sample N`. |
| `improve_multi_sample` | none (falls back to `multi_sample`) | Best-of-N sample count for `run-improve` specifically, so raising quality on the slow retranslate path doesn't also multiply cost on the fast translate path. Highest BT-scored candidate is kept. |
| `score_model` | none (falls back to `improve_model`, then locale default) | Back-translation / rescore model. When it differs from the translate pin, `run-translate` auto-defers LLM scoring to an in-process phase B (see `defer_scoring`). |
| `defer_scoring` | auto | `true` / `false` / unset. Unset: defer when `score_model ≠` translate pin and `multi_sample < 2`. Phase A writes `scorer=heuristic`; phase B batch-BT rescored keys. Restart resumes phase B from heuristic rows. |
| `bt_batch_size` | `5` | Keys per batch back-translation call in phase B and `run-rescore`. |
| `vision_model` | none | Vision-capable model for screenshot-context translation. Unset means screenshot attachment never runs, even if `[prompt] context_dir` entries set `screen`/`image` — this is opt-in, not automatic, since most local text models can't accept images. See [ADR-17](decisions/ADR-17-screenshot-context-opt-in-vision.md). |

### `[quality.tiers]`

How much human involvement a string needs, by namespace or key glob. First match wins; keys
that match nothing are `auto`.

```toml
[quality.tiers]
"legal/**"  = "human"    # never machine-translated; a review ticket is queued instead
"marketing" = "review"   # translated, then queued for a human to review
"*"         = "auto"
```

`legal/**` covers the namespace `legal` and its children; other patterns are matched against
the namespace, `namespace.key`, `namespace/key` and the bare key. A context note can override
a single key: `{"note": "...", "tier": "human"}`. A tier never changes a key's status
(ADR-48).

### `[ownership]` and `[review]`

```toml
[ownership]
"legal/**"    = "translator-legal"
"marketing.*" = "translator-marketing"
"*"           = "translator-default"

[review]
escalate_after_days = 3
sample_percent = 100
```

New review tickets get the assignee of the first matching pattern. `escalate_after_days`
(default 0 = off) makes `sync` post the `[notify] webhook` once for each ticket open longer
than that. The payload includes a `supervisor` (the first approved Supervisor for the
locale); there is no other per-user routing. `sample_percent` (default 100) is the share of
`review`-tier keys that get a ticket after translation; the rest are chosen by a stable hash of
the locale and key, so a key is always in or always out. `sync --diff` also posts
`{"event": "source.changed", "added", "changed", "removed"}` to the `[notify] webhook` when the
English changed since the last sync.

`[notify] format` is `json` (default: envelope `{event, project, ts, data}` with the older flat
fields kept alongside, HMAC-signed when `LLM_LOCALIZE_WEBHOOK_SECRET` is set) or `slack`
(`{"text": ...}` for incoming webhooks, never signed). Any other value is a config error. Events:
`translate.done` (once per translate run), `review.pending` (once per run and reason),
`source.changed`, `review-escalation`, `workflow.*`.

### `[translate]`

| Field | Default | Notes |
|-------|---------|-------|
| `batch_size` | `10` | Keys per LLM request on a local model. Queue blueprints pass it as `--batch-size`. |
| `cloud_batch_size` | `50` | Keys per request for a cloud (paying) locale. Measured on Haiku 5.5: no parse misses, same BT, half the wall time of 10 (`experiments/quality_bakeoff/HAIKU_BATCH_PROBE_2026-11-14.md`). |
| `short_batch` | `false` | When true, strings under four words batch together even when the default planner would keep them single-key (UI label catalogues). ICU strings always stay single-key. |
| `enabled` | `true` | When false, sync will not enqueue translate. |
| `soft_retry` | `true` | Retry once when an accepted translation carries a soft defect (Latin words the source lacks in a non-Latin locale, English stopwords, the source echoed back, an approved glossary term missing). The retry is kept only when it has fewer issues; nothing is rejected (ADR-8, ADR-57). |
| `min_keys` | `50` | Per-locale pending-key floor for **automated** sync→translate chains only. Below this, `run-translate` exits 0 (`skip 2 pending < min_keys 50`) so tiny overnight backlogs do not warm the GPU. `0` disables. Operator-initiated translate (web ▶, Ops, `llm-localizator translate`) always bypasses via `--ignore-min-keys`. Also bypassed by `--force`, `--flagged`, and dry-run listing. |
| `max_consecutive_rejects` | `10` | Abort a run after this many consecutive rejects/skips (junk model output). Keeps already-written keys; exit 1. `0` disables. |

### GPU sizing and deferred scoring

When translator and scorer are different models (typical: `translategemma:4b` for
ar/fr/th/vi, `aya-expanse:8b` for BT), set **`[quality] score_model`** explicitly
rather than relying on `improve_model` alone. **`defer_scoring`** (auto when
`score_model ≠` translate pin and `multi_sample < 2`) runs LLM scoring in a
second in-process phase so the card is not idle while models swap every key.

| Phase | Model (ar example) | VRAM (table) | Notes |
|-------|---------------------------|--------------|-------|
| A — translate | `translategemma:4b` | ~3.3 GiB | Heuristic scores only (`scorer=heuristic`); flags deferred |
| B — batch BT | `aya-expanse:8b` | ~5.2 GiB | `[quality] bt_batch_size` keys per BT call (default 5) |

**6 GiB cards:** phase A fits comfortably. Phase B / `run-rescore` with
`aya-expanse:8b` sits at ~5.4 GiB dedicated VRAM — near the limit. Windows may
also show **shared GPU memory** (~0.5–1 GiB): WDDM spill when VRAM is full, not
necessarily a misconfigured `num_gpu`. Task Manager **3D** util can read ~30%
while **Compute/CUDA** is 80–100% during decode; use `nvidia-smi` or the
taskqueue metrics dialog for honest GPU util.

If sustained Compute util stays low with shared memory present, some weights or
KV cache are likely on host RAM despite `[provider.options] num_gpu = 99`. That
is expected on 6 GiB for 8B Q4 models; options are a smaller score model, a
quantization tier that fits fully in VRAM, or a larger GPU — not unifying
translator and scorer (ADR-20 keeps them separate).

**Restart:** keys with catalogue text but `scorer=heuristic` in `.llm-scores`
resume phase B only. Manual fallback: `llm-localizator rescore <project> --locales
<locale>`.

**UI catalogues:** `[translate] short_batch = true` batches strings under four
words that the default planner would keep single-key (ICU always stays
single-key). Helps `[translate] batch_size` matter for label-heavy namespaces.

Regenerate taskqueue blueprints after changing models or `score_model`:
`llm-localizator init --taskqueue` in the consumer repo, then `tq sync`.

### `[state]`

| Field | Default | Notes |
|-------|---------|-------|
| `dir` | `<data_root>/.llm-state` | Per-locale state files. With `data_home = "engine"` (default) that is `~/.llm_localize/data/<name>/.llm-state`. Relative paths resolve against the data root. |
| `flags` | none | JSONL of developer-flagged bad translations, consumed by `--flagged`. |
| `history` | `<data_root>/.llm-history` | Per-locale history JSONL. |
| `scores` | `<data_root>/.llm-scores` | Per-locale score files. |

**Run analytics.** Each translate / improve / review / rescore run writes
`{state.dir}/_runs/{run_id}.json` with `wall_s`, throughput, and context metrics
(ADR-37). Query with `llm-localizator analytics <project>` — see [cli.md](cli.md).

**State is not a cache.** Without it every run re-translates everything. Under
the default `data_home = "engine"` it lives on the machine beside the registry,
not in the consumer git tree. With `data_home = "project"`, keep `.llm-state/`
out of `.gitignore` and commit it if you want clone-to-clone continuity; the
files are deterministic JSON (whitespace-stable, sorted by key). A CI
`--dry-run` that diffs the catalogue (and project-local state when used) is the
completeness gate.

Do **not** commit the `flags` file if it may contain developer notes about
translation quality that you do not want in the repo history.

### `[documents]`

Long-form Markdown (terms of service, privacy policy), translated
section-by-section rather than key-by-key. Optional — omit the table entirely if
the project has no such documents.

| Field | Default | Notes |
|-------|---------|-------|
| `dir` | `<root>/content/legal` | Holds `<source_locale>/*.md`; translations are written to `<locale>/*.md` alongside |
| `state_dir` | `<data_root>/documents-state` when `data_home = "engine"`; else `<dir>/.state` | One `<locale>.json` per locale, recording each section's source hash |
| `model` | the locale's catalogue model | Legal register is where a small model's output stops being acceptable, so documents get their own default |

```toml
[documents]
dir = "apps/web/content/legal"
state_dir = "apps/web/content/legal/.state"
model = "qwen2.5:14b"
```

Only sections whose source changed are retranslated, and the previous
translation of a section is offered to the model as an update target so wording
stays stable across revisions. If **any** section fails, the entire locale file
is deleted so the page falls back to the source language — a half-translated
privacy policy looks authoritative and is wrong.

`[documents]` is the collection `legal`. `[catalog]` is the collection
`messages`. Add another tree without a code change:

```toml
[collections.help]
dir = "apps/web/content/help"
format = "markdown"
```

HTML help pages (arena bots) use the same documents path with
`format = "html"` (or a mixed tree). The engine translates `.md`, `.html`, and
`.htm` under the source locale (ADR-113); ids are path stems without extension.

```toml
[collections.help]
dir = "arena/web/help"
format = "html"
```

`llm-localizator discover` proposes roots (locale-named sibling directories) and
writes nothing. Copy only the ones you confirm. Commands take `--collection`;
omitting it means `messages`.

Database text is not a directory. Declare a remote collection and point the
engine at the project's API with `LLM_LOCALIZE_CONTENT_URL` and
`LLM_LOCALIZE_CONTENT_TOKEN`. The contract is
[content-api.md](content-api.md).

```toml
[collections.live]
kind = "remote"
```

| Field | When |
|-------|------|
| `dir` | File collection. Required unless `kind` is `remote`. |
| `format` | File format. Default `markdown`. |
| `kind` | `remote` for a content API. Do not set `dir`. Do not put the URL or token here. |

A token in the toml is a config error.

### `[exclude]`

Strings that are never translated, improved, validated or exported (ADR-71). Separate from the
glossary do-not-translate list (terms inside a sentence) and from `status = "intentional"`
(one cell, decided by a person). `skip_keys` and `skip_namespaces` under `[catalog]` keep working.

| Key | Type | Meaning |
|-----|------|---------|
| `keys` | list of strings | Globs tested against the namespace, `namespace.key`, `namespace/key` and the bare key. `legal/**` covers a namespace and its children |
| `source_regex` | list of strings | Python regexes; a source string that matches anywhere is excluded |

```toml
[exclude]
keys = ["legal/**", "*.brand_name"]
source_regex = ["^https?://", "^[A-Z0-9_]{6,}$"]
```

A bad regex is a load error that names the pattern. The Project config page shows the rules read-only.

### `[validate.severity]`

Re-grades advisory checks for one project (ADR-72). Each key is a check id from
[checks.md](checks.md), each value `off`, `warning` or `error`. The report, `--strict`, CI
exit codes and the web findings list all see the changed severity; `checks.md` keeps the defaults.

```toml
[validate.severity]
V13 = "error"    # approved glossary term absent: block the release
V06 = "off"      # identical to source is fine here
```

V02 (placeholders), V03 (plurals), V27 (HTML) and V39 (stray backslash) protect output
that would break at runtime and cannot be changed; asking for it is a load error.

A check graded `error` also blocks an editor save (`/api/save`) with that finding; import and sync are never blocked. `off` and `warning` do not relax the editor's hard save gate.

### `[delivery]`

| Field | Default | Notes |
|-------|---------|-------|
| `require` | `none` | `verified` or `reviewed`. Exports and the content bundle (`GET /api/bundle`) then ship only approved translations: `verified` needs a verification stamp, `reviewed` also needs no open review ticket. Unapproved cells are blank in an export and fall back to the source text in the bundle ([ADR-74](decisions/ADR-74-approved-only.md)). |

```toml
[delivery]
require = "verified"
```

`export --approved-only` applies the same rule to one export without changing the config.

### `[privacy]`

| Field | Default | Notes |
|-------|---------|-------|
| `allow_cloud` | `false` | Lets cloud providers run when a budget is set. Without it a cloud kind falls back to the local provider. Dogfood ships named cheap-cloud providers (`anthropic_haiku`, `openai_luna`, `deepseek_flash`) with `allow_cloud = false` until you opt in. |
| `local_only` | `false` | Hard block ([ADR-69](decisions/ADR-69-local-only.md)). Loading fails if `allow_cloud = true`, if any `[provider]` / `[providers.<id>]` uses a cloud kind, if an Ollama URL is not `localhost`/loopback, or if `[notify] webhook` is not loopback. A provider built for a cloud kind raises instead of falling back. |

Example (env keys only — never put secrets in TOML):

```toml
[privacy]
allow_cloud = true

[budget]
monthly_usd = 5.0
mode = "on_request"
cloud_batch = true

[providers.anthropic_haiku]
name = "Anthropic Haiku 5.5"
kind = "anthropic"

# Optional: route one locale, or pass --model claude-haiku-5-5
# [locales.providers]
# pl = "anthropic_haiku"
```

```toml
[privacy]
local_only = true
```

Existing TM and glossary files stay readable; `local_only` limits what leaves the machine, not what is read.

### `[tasks]`

| Field | Default | Notes |
|-------|---------|-------|
| `contribute_in_tasks_only` | `false` | A Translator may write a key only when a task (`llm-localizator task`) lists it and assigns that locale to them ([ADR-93](decisions/ADR-93-tasks-only-contributing.md)). |

```toml
[tasks]
contribute_in_tasks_only = true
```

Enforced on the web save, verify and revert routes and on `draft accept`, not only in the editor. Admin, Supervisor and Developer are unaffected; reading stays open.

### `[web]`

| Field | Default | Notes |
|-------|---------|-------|
| `runtime_path` | `""` | Where `llm-localizator runtime install` puts the shipped `i18n.js`, relative to the project root: a directory or a `.js` path ([web-runtime.md](web-runtime.md), ADR-118) |
| `qa_locales` | `[]` | Marker locales for painted-English QA (`en-XX` / `en-XA`). Enables the review-app language picker and `/en-XX/…` URL prefixes (ADR-110). **Omit or `[]` in production.** Never put these codes in `[locales].targets`. SPA consumers without llm_localizator web use `pseudo --locale en-XX` + storage-mode crawl instead — [consumer-localization-checklist.md](consumer-localization-checklist.md) |

```toml
# Local QA only — clear before shipping
[web]
qa_locales = ["en-XX"]
```

### `[qa]`

How the QA crawl reaches the app (ADR-119). Optional; used by
`hardcoded-hunt` and `experiments/hardcoded_visible/crawl.py --project <name>`.

| Field | Default | Notes |
|-------|---------|-------|
| `base_url` | required | `http://` or `https://` origin of the running app |
| `pages` | `["/"]` | Paths under `base_url` (may carry `?query` / `#hash`) |
| `start` | `[]` | Command (array) that starts the app, run in the project root; only used when the app is not already answering and the crawl may serve (`hardcoded-hunt --serve`) |
| `locale_mode` | `"query"` | `query` (`?lang=xx`), `path` (`/xx/page`) or `storage` (localStorage before load) |
| `query_param` | `"lang"` | Query mode parameter |
| `storage_key` | — | Required for `storage` mode |
| `qa_locale` | `"en-XX"` | Marker locale for the leftover pass |
| `layout_locales` | ar/zh among the project's locales | Locales that get the layout pass and screenshots; `[]` turns it off |
| `ready_timeout` | `60` | Seconds to wait for `start` to answer |
| `[qa.clicks]` | — | `"<page>" = ["#selector", …]`: clicked in order on that page, text collected after each |
| `[qa.wait_for]` | — | `"<page>" = "#selector"`: wait for it before collecting (lists filled by a fetch); a timeout marks the page not ready |

The crawl records the JSON responses each page loads. Leftovers equal to an API value, repeated rows and pure
measurements go to `data_text.json`; `dynamic_text.json` keeps only API copy (message-like fields, with a
`producer: api:<path>#<field>`) and text of unknown origin (ADR-133).

```toml
[qa]
start = ["npm", "run", "dev"]
base_url = "http://127.0.0.1:7474"
pages = ["/"]
locale_mode = "query"
[qa.clicks]
"/" = ["#tab-threads", "#tab-knowledge"]
```

### `[apply]`

| Field | Default | Notes |
|-------|---------|-------|
| `mode` | `manual` | What accepting a scan result does: `manual` (recorded; you run `apply --confirm`), `request` (a review ticket on the source locale; closing it applies the key), `auto` (the key is added and translation queued at once). Any other value is a config error |

Source code is never edited in any mode (ADR-32, ADR-55).

### `[scan]`

| Field | Default | Notes |
|-------|---------|-------|
| `adapter` | none | `next-intl`, `react-intl`, `raw-js`, or `source` |
| `src_dirs` | `[]` | Source roots to scan |
| `server_dirs` | `[]` | Python server packages; `server-copy` lists the people-facing strings they write into responses, and crawl leftovers are located there too (ADR-134) |
| `exclude` | `[]` | Extra path fragments to skip, matched on whole path segments (`features/design` skips `features/design/x.tsx`, not `features/designSystem.tsx`). Cannot undo a built-in skip |
| `unused_allow` | `[]` | Key globs that `validate --unused` (V41) never reports, for keys built at run time |
| `unskip` | `[]` | Same segment matching. Put a soft-skipped path (docs, scripts, …) back. Cannot resurrect `node_modules` |
| `t_functions` | `[]` | Names of your own translate wrappers (`trKey`, `myT`, `ui.say`): a literal passed to one is already routed, not hardcoded. A dotted name matches its last part too. |
| `content_globs` | `[]` | Opt-in: files whose text people read although they are not pages, e.g. `["bot/replies/*.yml", "api/openapi.yaml"]`. Markdown, TOML and YAML matching a glob are read by the content scanner (YAML: `title`, `description`, `summary`, `label` … including `>`/`\|` blocks). Off by default because OpenAPI and config YAML are usually developer docs. Markdown under `content/`, `posts/`, `pages/`, `resources/`, `templates/` is read without it. A theme or starter repository ships sample posts there that are demo data, not its UI: add `"content/**"` to `exclude` |
| `out_dir` | none | Where usage backreference artefacts are written |

## `[engine]` — one switch for every model (ADR-156)

```toml
[engine]
id = "claude-haiku"   # llm-localizator engine list
```

The engine's settings are layered *under* this file: provider kind, `[locales.models] default`, the `[quality]`
improve/score/judge models, `score_provider`, `threshold` and batch sizes. Any of those you write here explicitly wins,
so a frozen locale can stay on a local model (`[locales.models] de = "aya-expanse:8b"` with
`[locales.providers] de = "local"`). Engines never set `[privacy]`, `[budget]`, URLs or keys.

## Glossary format

```json
{
  "doNotTranslate": ["Stayman", "Blackwood", "PBN"],
  "terms": {
    "trick":  { "pl": "lewa", "pl_forbidden": ["sztuczka", "trik"] },
    "bridge": { "pl": "brydż", "ar": "بريدج" }
  }
}
```

`doNotTranslate` entries must survive verbatim. `<locale>` supplies the approved
translation (advisory, V13). `<locale>_forms` lists inflected forms you accept
(`"pl_forms": ["zapowiedzi", "zapowiedzią"]`): any of them satisfies V13, and the prompt
shows them as `(also: ...)`. It is exact and project-maintained; for `pl` and `ar` the
automatic stem match still runs as a fallback. CSV export/import carries the forms in an
optional `forms` column (`;`-separated); TBX does not. `<locale>_forbidden` lists renderings that are
wrong (blocking, V04). Both `terms` rules only apply when the source actually
uses that term.

**How these appear in the prompt.** The model sees a `GLOSSARY` block injected
before the keys it must translate:

```
GLOSSARY:
- "Stayman", "Blackwood", "PBN" — copy these exactly, do not translate
- "trick" → "lewa" (Polish approved), never "sztuczka" or "trik"
- "bridge" → "brydż" (Polish approved)
```

`doNotTranslate` terms also appear in the validation error message if the model
translates them anyway, so the reviewer (or re-run) knows which rule fired. The
effect is conservative: the model may still render `Stayman` slightly differently
inside an ICU plural branch if it is translating the surrounding text. The
validator catches the verbatim case; the `review` pass catches the rest.

## Context notes

`<context_dir>/<namespace>.json`. A value is either a bare string or an object:

```json
{
  "claim": "Declaring the remaining tricks without playing them out.",
  "shortLabel": { "note": "Button on the bidding box", "screen": "table", "maxChars": 12, "html": false }
}
```

Set `"html": true` when markup must be preserved; V27 also auto-runs whenever the
source already contains HTML tags (comparisons like `a < b` are ignored).

`screen` groups keys that appear on the same UI surface (used for batch
translation). It is **not** an image filename. To attach a screenshot, place a
PNG/JPEG/WebP at `<context_dir>/screenshots/<screen>.png` (e.g.
`screenshots/table.png`) or set an explicit `"image": "path/under/context.png"`
field. The web UI offers **📷 attach screenshot** on rows that have a `screen`
id.

`maxChars` is a hard budget: exceeding it warns (V09) and triggers a shorten
pass during translation. The translator sees it in the prompt as `[max N chars]`.
`maxLength` and `max_length` are accepted as aliases for the same field
(`maxChars` wins when several are set); the length is counted in characters.

Three optional fields go straight into the prompt for that key:

| Field | Prompt line | Use |
|-------|-------------|-----|
| `register` | `[register: formal]` | `formal` or `informal`, for a key whose tone differs from the locale default (legal text, marketing) |
| `gender` | `[gender: feminine]` | Grammatical gender of the entity a placeholder stands for, so Slavic and Romance languages can agree |
| `group` | `[sentence fragment: ...]` | The same name on several keys says they are pieces of one sentence; each prompt lists the other pieces so the translator can make them read as one |

A reserved `"_note"` entry holds a translator note for the whole namespace. Strings that carry
HTML also get a worked example of moving tags with the words (`Click <b>here</b>` in German).
Changing `register`, `gender` or `group` does not mark a translation stale; use `--force`.

With ``--check-layout`` (or Ops → Layout), keys that resolve a screenshot also
run advisory **V28** layout heuristics (`core/layout_qa`). Consumer Playwright
capture writes findings JSONL for ``llm-localizator ingest-visual`` — see
[visual-findings.md](visual-findings.md) and [ADR-27](decisions/ADR-27-consumer-visual-capture.md).

Optional:

```toml
[visual]
findings_path = "apps/web/messages/.visual_findings.jsonl"
```

Default findings path is ``{context_dir}/../.visual_findings.jsonl``.

## Full example

A production configuration typically covers a dozen locales, two models, a pivot,
a glossary, and context notes; combine the sections above.

## Minimal json-flat example

A common layout for plain JS/HTML projects: one flat JSON file per locale, no
namespaces, strings like `{ "nav.queue": "Queue", "status.running": "Running" }`.

```toml
[project]
name = "myapp"
source_locale = "en"

[catalog]
format = "json-flat"
path = "static/locales/{locale}.json"
namespaces = "*"

[locales]
targets = ["pl", "de"]

[locales.models]
default = "llama3.2"

[provider]
kind = "ollama"
url = "http://localhost:11434"

[prompt]
domain = "a task queue monitoring web UI for scheduling GPU and ML workloads"
```

Generate this automatically:
```bash
llm-localizator init . --format json-flat --path "static/locales/{locale}.json"
```

The `namespaces = "*"` setting discovers namespace files from the source locale.
For a single-file layout (one `en.json` with no per-namespace split), there will
be a single implicit `default` namespace.

## `[source_policy]`

```toml
[source_policy]
source_edits = "patch"      # never | patch | agent-branch
decisions_in = "state"      # state | code
target_branch = "l10n/auto" # bot branch for target-locale files
```

`never` makes `patch` refuse; `agent-branch` adds an `agent_task` block to the patch output.
The engine never writes source files in any mode (ADR-107).

## `[places]` — per-place translation policy (ADR-104)

```toml
[places]
default = "auto"                 # auto | request | review | never
[places.legal]
policy = "request"
[places."app:debug*"]            # NS-glob:KEY-glob, most specific wins
policy = "never"
```

`never` skips the place in every sweep and in validation. `request` places are skipped by translate, improve, rescore and scoring unless their keys are named (`--keys`); `review` places are translated but always ticketed for review (review tier). `discover` prints a `[places]` snippet (policy `request`) for unclaimed collections and writes nothing. Edit with `llm-localizator places set|unset` (comments in the toml are kept).
