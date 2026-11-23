# Model evaluation procedure

**When a new local LLM appears — or a monthly recheck is due — follow this
checklist before changing `[locales.models]`, `[locales.roles]`, or
`[quality] judge_model`.**

Policy: [ADR-12](decisions/ADR-12-local-model-bakeoff-defaults.md)
(gates) · [ADR-23](decisions/ADR-23-prompt-families.md) (stripped vs
consumer) · [ADR-22](decisions/ADR-22-tm-and-ctranslate2.md) (CT2/VRAM).
Runner: `llm-localizator bakeoff` / `run-bakeoff` ([cli.md](cli.md#bakeoff--run-bakeoff)).
Reports and the coverage ledger land in `--out` (default: the project state
dir under `bakeoff/`).

## 1. Triggers

Do this procedure when any of the following is true:

- A new Ollama tag or CT2 weight set is a candidate for dogfood/consumer defaults
- Monthly recheck is due (or sooner when a strong new candidate appears)
- You are about to edit models / roles / `judge_model` in any project TOML

## 2. Always include the incumbent

Never run a candidate-only bakeoff. Default matrix already includes
`aya-expanse:8b` (incumbent). For ad-hoc runs, `--models` must list the current
Winner **and** the candidate(s).

## 3. Install

```bash
ollama pull <candidate-tag>
# keep the incumbent installed as well
```

Pinned comparison set (matrix default):

- `aya-expanse:8b`
- `qwen2.5:7b`
- `translategemma:4b`
- `llama3.2`

**CTranslate2 / MADLAD** is not an Ollama bakeoff tag. The public
`bakeoff` / `run-bakeoff` commands compare **local Ollama models only**.
Install CT2 under `--ct2-path` / `[provider] model_path` for production use,
but do **not** co-resident a heavy Ollama load and MADLAD on 6 GB VRAM
(ADR-22). Unload Ollama first: `ollama stop <tag>` (or wait for keep-alive
expiry).

## 4. Preferred: full matrix (quality + speed)

Start with **`pl`**. Records quality (mean BT, gate) and speed (wall_s, keys/s)
into JSONL + `LEDGER.md`. Standard cells per model:

```bash
llm-localizator bakeoff --matrix --locales pl --models qwen2.5:7b --dry-run
llm-localizator run-bakeoff --matrix --locales pl --models qwen2.5:7b
```

The command adds the locale's current model to every run, samples your own
strings evenly across UI roles, and appends a dated section to `REPORT.md`
without touching the Winners table.

| prompt_mode | family |
|-------------|--------|
| stripped | chat |
| consumer | chat |
| consumer | mt_chat |

Expand languages later: `--locales pl,ar,de,…`. LEDGER “Coverage by locale”
shows which model×locale cells exist. Point `--out` at a durable folder if you
want to keep reports across machines.

Ctrl-C / `tq stop` is safe: JSONL flushes per **cell**; retry the same task
and finished cells are **skipped** (checkpoint). Use `--force-cells` to redo.
Progress lines use taskqueue’s `(N%)` form when queued.

## 5. Lighter dual-track (two models)

```bash
llm-localizator run-bakeoff \
  --locales pl \
  --models <incumbent>,<candidate> \
  --family both
```

| Track | Meaning |
|-------|---------|
| `stripped` | Raw fluency (SaaS domain, empty glossary). Fine for smoke. |
| `consumer` | Production-like domain / glossary / key / context. **Winner ranking.** |
| `both` / `--matrix` | Several prompt cells; prefer consumer for swaps. |

Stripped-only must **not** drive model swaps (ADR-23).

## 6. Gates

Per cell (ADR-12):

- mean back-translation score ≥ **0.70**
- **zero** glossary-blocking rejects on the corpus

Prefer **consumer/chat** when ranking Winner vs incumbent. Also compare
**keys/s** — a slightly lower mean with much higher speed may still be useful
as secondary, but primary TOML swaps need consumer quality.

## 7. Human spot-check

Record in `REPORT.md` at least:

- one ambiguous / polysemous UI string
- one long string
- one account / destructive UI string

If consumer sense is still wrong on ambiguous keys, try step 8 before discarding
the candidate.

## 8. Prompt family A/B

Matrix already runs `consumer/mt_chat`. For a single model:

`--family mt_chat` or `--family both`.

Do **not** flip dogfood `[prompt] family` without that evidence (ADR-23). CT2
ignores instruction text — family does not apply.

## 9. Decide

1. Write / keep a **Winner** note in `REPORT.md` dated after the candidate was
   considered (locale + track + mean + speed).
2. Only then edit `[locales.models]`, `[locales.roles]`, or
   `[quality] judge_model`. Or print a snippet with
   `llm-localizator bakeoff --propose-config` (reads the Winners table; writes
   nothing).
3. Role shapes: [examples/locale-roles.md](examples/locale-roles.md).
4. If the candidate does not win on consumer quality (or fails spot-check),
   keep defaults and journal only. LEDGER still records the run.

## 10. Cloud escape hatch

Anthropic / DeepL only when the locale **fails** the local bakeoff gate, **or**
an operator sets `[locales.providers]` with `[budget] monthly_usd > 0`.

## 11. Hygiene

- Record the result and the reason in your project notes
- Hermetic `pytest` stays untouched — bakeoff / matrix needs live GPU/Ollama

## 12. Tracked metrics (audit A4)

Record in REPORT / LEDGER (by locale, content type, model, prompt/context version):

| Metric | Notes |
|--------|-------|
| Structural / hard-gate pass rate | Placeholders, ICU, HTML, script |
| Glossary violation rate | Blocking V13-style |
| Unexpected-script rate | Locale policy |
| Mean BT (and LQS when judge on) | Not interchangeable; store `scorer_version` |
| Human acceptance / spot-check | North-star |
| Exact-TM / fuzzy-TM reuse % | ContextAssembler / TM |
| Review / retranslate rate | From improve flags + review |
| Latency, keys/s, tokens | Privacy class stays local-first |

Gold-set calibration (publish/review/retranslate P/R) is a maintainer
exercise: expand a labelled set before treating judge thresholds as measured.

## Non-goals

- Auto-switching models on reject
- Per-Ollama-tag prompt files
- Evaluating CT2 via Ollama `--models` (CT2 is outside the public bakeoff
  matrix; use `[provider]` / `--ct2-path` for production)
