# Taskqueue integration

`llm_localizator` never imports `taskqueue` (ADR-1). The whole integration is a
generated YAML blueprint that lives in the *consumer's* repo, plus a `tq`
subprocess call. That means the queue can be upgraded, replaced, or absent
without touching engine code.

## The submit / execute split

Each LLM-bound capability is two commands:

| Command | Runs where | Needs a GPU |
|---------|-----------|-------------|
| `translate` | your shell | no — submits and exits |
| `run-translate` | the queue worker | yes |

Same for `documents` / `run-documents`, `review` / `run-review`,
`improve` / `run-improve`, and `rescore` / `run-rescore`.

Two reasons (ADR-2). Any workflow — a sync script, a git hook, a CI step — can
trigger translation without occupying a terminal for an hour. And the queue
keeps its single-writer guarantee over the state files: if the human-facing
command also did the work, two developers running it at once would interleave
writes into the same `{state.dir}/<locale>.json` (default `.llm-state/`).

Flags that change *how* the work runs (`--force`, `--flagged`, `--dry-run`,
`--ignore-min-keys`) therefore belong to `run-translate` and reach it through
`overridable_args`. Operator `translate` always sets `--ignore-min-keys` so
`[translate] min_keys` only gates automated sync→translate chains.

## Setup

```bash
llm-localizator init --taskqueue     # base + one translate YAML per target locale
tq sync                           # queue picks them up
llm-localizator translate --locales vi
llm-localizator translate --locales de
tq list --project <name>
```

`init --taskqueue` writes:

| File | Task id |
|------|---------|
| `llm_localizator_translate.yaml` | `localize_ui_messages` (full sweep; sync/improve chain) |
| `llm_localizator_translate_vi.yaml` | `localize_ui_messages__vi` |
| `llm_localizator_sync.yaml` / `…_improve.yaml` / `…_review.yaml` / `…_documents.yaml` / `…_rescore.yaml` | base GPU/CPU jobs |

Missing per-locale YAML is also created on first submit (consumer
`experiments/operator_queue/` — the configured integration path).

## Prefer-queue

Non-dry-run `translate` / `improve` / `review` from CLI ops and the web UI
**submit** when `tq` is on PATH (ADR-15). Dry-run stays local. Without `tq`,
the ops layer runs locally and says so. `run-translate` remains the worker
entrypoint (ADR-2).

## The generated blueprint

```yaml
task_id:          localize_ui_messages
command:          llm-localizator
args:             [run-translate, my-app, --locales, "pl,ar,...", --batch-size, "10", --model, "qwen2.5:7b"]
wall_clock_cap_sec: 14400
idempotent:       true
hung_task_k:      60

requires_services:
  - name:              ollama
    health_url:        "http://localhost:11434/api/tags"
    timeout_sec:       5
    min_vram_free_gib: 5.0

overridable_args: [--locales, --model, --batch-size, --force, --flagged, --dry-run, --namespace, --collection, --ignore-min-keys]

teardown:
  command:     ollama
  args:        [stop, "qwen2.5:7b"]
  best_effort: true

resources:
  gpu_vram_gib: 5.0
  locks:        [ollama]
```

### `requires_services` — health-gated dispatch

The queue probes `health_url` before spending a dispatch slot. If the model
server is down the task stays **queued** with `last_error_code:
tq.block.service_down` rather than failing, and the probe repeats each scheduler
tick until the service returns.

`min_vram_free_gib` (wave 2) also probes Ollama `/api/ps` so a previous job's
`keep_alive` residue cannot admit a second load that will time out
(`tq.block.service_vram`).

`resident_ok_models` lists models whose residency satisfies the VRAM gate
without a free-card reload. For translate jobs where `[quality] score_model`
differs from the pin, **both** models appear — the reservation is the **max**
of the set plus headroom, not the sum (only one model loads at a time).

`resources.locks: [ollama]` serialises all Ollama-backed jobs across projects
while still allowing CPU-only `localize_sync` to overlap. `hung_task_k` raises
the silent-progress grace for long single-key LLM calls. `wall_clock_cap_sec`
defaults to **14400** (4h) so a full-locale thaw (~1k+ keys) is not cut mid-run
the way a 1h cap was. `teardown` runs `ollama stop` after the process exits so
the lock releases against a free card. For deferred translate, teardown stops
the **score** model (phase B leaves it resident), not the translate pin.

`localize_sync` is gather-only (`--no-translate`) and lists
`on_complete: [localize_ui_messages]`. `localize_improve` uses
`depends_on` + `rearm_on: upstream_success` and a nightly `schedule.cron`.
Some dogfood blueprints ship with `enabled: false` until you enable them in
the queue — operator `llm-localizator translate` still works via `tq retry`.

### Automated quality loop (one picture)

1. **`run-sync … --no-translate`** — gather missing/stale (CPU).
2. **`on_complete` → `run-translate`** — fill catalogues (GPU / Ollama).
3. **`on_complete` → `run-review`** (when the translate blueprint wires it).
4. **`run-improve`** — nightly or `depends_on` translate (GPU).

Operator shortcut (skips the cron): `llm-localizator translate --locales pl`
then `improve` / `review` as needed. Requires Ollama
([getting-started.md](getting-started.md) §2). `[translate] min_keys` only
gates the automated chain; operator submit bypasses it (per-locale blueprints
bake `--ignore-min-keys`).

### `overridable_args` — scoped runs

```bash
# Preferred: one queue task per locale (ADR-15)
llm-localizator translate --locales vi
# -> tq retry <project>/localize_ui_messages__vi

llm-localizator translate --locales vi,de
# -> retry …__vi and …__de

# Plain retry uses the blueprint args as-is:
tq retry <project>/localize_ui_messages__pl
```

If your `tq` build still supports `tq retry … --set --flag=value`, overrides
apply to that run only and never rewrite the blueprint. Newer CLIs dropped
`--set`; use per-locale blueprints (or HTTP/MCP `args_override`) instead. A
flag not on `overridable_args` is refused. Per-locale blueprints bake
`--locales` (and `--ignore-min-keys` for operator thaw).

Regenerate it after changing `[locales]`, `[locales.models]`, or
`[quality] score_model` — the locale list and the VRAM figure are both derived
from the config.

## Deferred translate scoring

Dogfood on a 6 GiB card exposed the dominant cost when translator ≠
scorer: **per-key model swap** (translate on TG → BT on aya → unload → repeat).
Taskqueue metrics for `localize_ui_messages__ar` showed ~**49% average GPU
util** and ~25 s/key with 297/297 effective batch size 1 on short UI strings.

Fix (2026-09-01): one `run-translate` job, two **sequential** GPU phases inside
the engine — not a separate translate→rescore chain (that would double warmup /
teardown).

```
Phase A (pin = translategemma:4b)
  translate all pending keys
  score: heuristic only → .llm-scores scorer=heuristic
  flags: deferred

  ollama stop <pin>
  ensure_ready <score_model>

Phase B (score_model = aya-expanse:8b)
  batch back-translate bt_batch_size keys per call
  overwrite scores, append low-score flags

  ollama stop <score_model>
```

**Auto-trigger:** `defer_scoring` unset, `score_model ≠` pin, `multi_sample < 2`.
**Restart:** catalogue + state current, `scorer=heuristic` → phase B only.
**Manual:** `llm-localizator rescore my-app --locales ar`.

Blueprint changes for dual-model translate (example: ar):

```yaml
min_vram_free_gib: 5.4          # max(translategemma:4b, aya-expanse:8b) + headroom
resident_ok_models: ["translategemma:4b", "aya-expanse:8b"]
gpu_vram_gib: 5.4
teardown:
  args: [stop, "aya-expanse:8b"]   # score model, not the pin
```

Consumer config (example):

```toml
[quality]
score_model = "aya-expanse:8b"

[translate]
short_batch = true    # batch short UI labels; ICU stays single-key
```

### Observed GPU behaviour (6 GiB, Windows)

| Symptom | Likely cause |
|---------|----------------|
| Dedicated VRAM ~5.4 GiB during aya/rescore/phase B | Full 8B Q4 weights + KV in VRAM (expected reservation) |
| Shared GPU memory 0.5–1 GiB | WDDM spill / unified pool when VRAM is tight — not proof of intentional partial offload, but often co-occurs with it |
| Task Manager GPU ~30%, Compute/CUDA ~90% | Wrong graph selected (3D vs Compute) or idle gaps between decode steps |
| Memory controller load ~15–20% | Not VRAM-bandwidth saturated; fits autoregressive decode + CPU bookkeeping |
| Phase A TG 4B | Should show higher util than old per-key swap path |
| Phase B / rescore aya 8B | ~60–100% Compute util in taskqueue samples; 6 GiB is marginal for fully on-GPU 8B |

Check: `ollama ps`, `nvidia-smi -l 2`, taskqueue **metrics** dialog (Compute
util history). `[provider.options] num_gpu = 99` requests full offload; on 6 GiB
some host spill may still happen for 8B models.

## GPU reservation

`gpu_vram_gib` is derived from the configured model roster, not guessed. For
translate/rescore/improve, the reservation is the **largest** model that may
load during the job plus 0.2 GiB headroom. Deferred translate adds
`score_model` to the set when it differs from the pin — still one resident model
at a time, but the gate must allow either to be loaded from `keep_alive`.

| Model | GiB resident (Q4_K_M) |
|-------|----------------------|
| `phi3:mini` | 2.4 |
| `qwen2.5:3b` | 2.6 |
| `translategemma:4b` | 3.3 |
| `llama3.2` | 4.1 |
| `mistral` | 4.4 |
| `qwen2.5:7b` | 4.8 |
| `aya-expanse:8b` | 5.2 |
| `llama3.1` | 5.6 |
| `gemma2:9b` | 6.1 |
| `qwen2.5:14b` | 9.2 |

A model missing from this table makes blueprint generation **fail**, rather than
emit a blueprint with no reservation. That is deliberate: the failure mode of a
missing reservation is silent. A consumer measured it — the queue co-scheduled other
GPU work, ~900 MiB spilled to CPU, and throughput fell from **40 to 5.6 tok/s**.
A 7× regression that looks like nothing is wrong.

To add a model, extend `MODEL_VRAM_GIB` in
`llm_localizator/projects/taskqueue.py`, or pass an override.

## Being a good queue citizen

The contract is small, and everything in it is independently worth doing:

| Requirement | How it is met |
|-------------|---------------|
| argv-driven CLI | `llm-localizator run-translate ...` |
| Honest exit codes | 0 success; non-zero only if nothing could be written at all. Rejections, needs_context blocks, and provider errors are normal operational outcomes — the previous translation is kept and the key stays stale for the next run. The done-line counts them separately. |
| Progress on stdout | `[{done}/{total}] {ns}.{key} -> {locale} ({pct}%)` plus `(0%)` at job start and before each batch; lines use `flush=True` via `llm_localizator.reporting` |
| Idempotent | State tracking means a re-run translates only what is still stale, so `tq retry` is always safe |
| Survives an abrupt kill | State is flushed after **every batch** |
| Run speed on disk | `{state}/_runs/*.json` from the engine (ADR-37); taskqueue GPU history is ephemeral |

**Durable vs ephemeral:** taskqueue stores task-level elapsed time and GPU util
from stdout while a job runs. The engine additionally writes `_runs/` JSON so
`llm-localizator analytics` can compare keys/s across config changes after the fact.

That last point is why checkpointing is per batch rather than per run. On
Windows `subprocess.terminate` maps to `TerminateProcess` — an unconditional
kill with no chance for a signal handler to run a graceful shutdown. Progress
must already be on disk. Flushing per batch bounds the loss from "the entire
run" to "at most one in-flight batch".

## Visual QA suite

Browse → ingest → validate is three TQ tasks chained with `on_complete` (not one
shell `&&`). Capture is idempotent at the **app** level (`--resume` + checkpoint
JSON); the queue does not store screen progress. `requires_services` is only on
capture. Full procedure: [visual-findings.md](visual-findings.md).

| Step | Consumer task_id | Dogfood task_id |
|------|----------------|-----------------|
| Capture (Playwright) | `i18n_page_review` | `llm_localizator_visual_qa` |
| Ingest | `i18n_visual_ingest` | `llm_localizator_visual_ingest` |
| Validate `--check-layout` | `i18n_visual_validate` | `llm_localizator_visual_validate` |

```bash
# UI must be healthy first
tq sync
tq retry my-app/i18n_page_review
# After CTRL+C mid-capture:
tq retry my-app/i18n_page_review   # resumes screens, then continues chain on exit 0
# Full recapture:
tq retry my-app/i18n_page_review --set --force
```

Blueprints: `experiments/operator_queue/i18n_page_review.yaml` (+ ingest/validate)
in the consumer; dogfood mirrors under this repo’s `experiments/operator_queue/`.

## Running without the queue

The `run-` commands work standalone:

```bash
llm-localizator run-translate --locales pl --namespace auth
```

You give up GPU arbitration and automatic retries (the review web UI still
works). Fine for debugging a
prompt; not how a full sweep should be run on a shared machine.
