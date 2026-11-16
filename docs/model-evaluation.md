# Model evaluation procedure

**When a new local LLM appears — or a monthly recheck is due — follow this
checklist before changing `[locales.models]`, `[locales.roles]`, or
`[quality] judge_model`.**

Policy: [ADR-12](decisions/ADR-12-local-model-bakeoff-defaults.md)
(gates) · [ADR-23](decisions/ADR-23-prompt-families.md) (stripped vs
consumer) · [ADR-22](decisions/ADR-22-tm-and-ctranslate2.md) (CT2/VRAM).
Runner: `llm-localizator bakeoff` ([cli.md](cli.md#bakeoff--run-bakeoff)). The older
[`experiments/quality_bakeoff/run_bakeoff.py`](../experiments/quality_bakeoff/run_bakeoff.py)
still works and is the one that supports the CTranslate2 track.
Latest evidence: [`experiments/quality_bakeoff/REPORT.md`](../experiments/quality_bakeoff/REPORT.md).
Coverage index: [`experiments/quality_bakeoff/LEDGER.md`](../experiments/quality_bakeoff/LEDGER.md).

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

**CTranslate2 / MADLAD** is not an Ollama bakeoff tag. Install under
`--ct2-path` / `[provider] model_path`. Do **not** co-resident a heavy Ollama
load and MADLAD on 6 GB VRAM (ADR-22). Unload Ollama first:
`ollama stop <tag>` (or wait for keep-alive expiry).

## 4. Preferred: full matrix (quality + speed)

Start with **`pl`**. Records quality (mean BT, gate) and speed (wall_s, keys/s)
into JSONL + `LEDGER.md`. Standard cells per model:

```bash
llm-localizator bakeoff --matrix --locales pl --models qwen2.5:7b --dry-run
llm-localizator run-bakeoff --matrix --locales pl --models qwen2.5:7b --out experiments/quality_bakeoff
```

The command adds the locale's current model to every run, samples your own strings evenly
across UI roles, and appends a dated section to `REPORT.md` without touching the Winners
table. The script below does the same and adds the CTranslate2 track.

| prompt_mode | family |
|-------------|--------|
| stripped | chat |
| consumer | chat |
| consumer | mt_chat |

```bash
.venv/Scripts/python.exe experiments/quality_bakeoff/run_bakeoff.py \
  --matrix --locales pl \
  --config <path/to/consumer-or-dogfood/.llm-localize.toml> \
  --write-ledger
```

Optional MADLAD after unloading Ollama:

```bash
.venv/Scripts/python.exe experiments/quality_bakeoff/run_bakeoff.py \
  --matrix --locales pl --config <toml> --write-ledger \
  --ct2-path D:\models\madlad400-3b-ct2
```

Expand languages later: `--locales pl,ar,de,…`. LEDGER “Coverage by locale”
shows which model×locale cells exist.

Ctrl-C / `tq stop` is safe: JSONL flushes per **cell**; retry the same task
and finished cells are **skipped** (checkpoint). Use `--force-cells` to redo.
Progress lines use taskqueue’s `(N%)` form, e.g.
`[3/12] aya-expanse:8b pl [consumer/chat] key 10/76 amb.board (22.5%)`,
plus `TQ_METRIC` and 45s heartbeats so hung detection stays quiet during long
LLM calls. Per-locale queue tasks:
`experiments/operator_queue/quality_bakeoff_matrix_{pl,ar,de,fr,it,nl,pt_PT,pt_BR,cs,es,ru,tr,ko,th,vi}.yaml`
(bridge target locales). Full roster completed 2026-08-30 — see REPORT Winner
table before editing consumer `[locales.models]`.

## 5. Lighter dual-track (two models)

```bash
.venv/Scripts/python.exe experiments/quality_bakeoff/run_bakeoff.py \
  --prompt-mode both \
  --config <path/to/consumer-or-dogfood/.llm-localize.toml> \
  --models <incumbent>,<candidate> \
  --locales pl
```

| Track | Meaning |
|-------|---------|
| `stripped` | Raw fluency (SaaS domain, empty glossary). Fine for smoke. |
| `consumer` | Production-like domain / glossary / key / context. **Winner ranking.** |
| `both` | Two tables. |

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

- one `amb.*` key (sense / polysemy)
- one `long.*` string
- one account / destructive UI string (e.g. `acct.deleteTitle`)

If consumer sense is still wrong on `amb.*`, try step 8 before discarding the
candidate.

## 8. Prompt family A/B

Matrix already runs `consumer/mt_chat`. For a single model:

`--family mt_chat` or `--family both`.

Do **not** flip dogfood `[prompt] family` without that evidence (ADR-23). CT2
ignores instruction text — family does not apply.

## 9. Decide

1. Write / keep a **Winner** note in `REPORT.md` dated after the candidate was
   considered (locale + track + mean + speed).
2. Only then edit `[locales.models]`, `[locales.roles]`, or
   `[quality] judge_model`.
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

Gold-set calibration (publish/review/retranslate P/R) lives under
[`experiments/quality_bakeoff/gold/`](../experiments/quality_bakeoff/gold/) — expand
before treating judge thresholds as measured.

## Non-goals

- Auto-switching models on reject
- Per-Ollama-tag prompt files
- Evaluating CT2 via Ollama `--models` (use `--ct2-path` instead)
