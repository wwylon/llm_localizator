# Troubleshooting

Find the message you see (or a phrase from it), then follow the fix. Exit codes:
[exit-codes.md](exit-codes.md). Terms: [concepts.md](concepts.md).

## A run refuses to start

**`interrupted flush from … phase=…; run llm-localizator acknowledge-flush`**
A previous run stopped while writing results. Catalogues and state may disagree for the
keys in that batch. Run `llm-localizator acknowledge-flush` (it deletes the journal and does
not touch catalogues), then `llm-localizator validate` to check the result.

**`another process holds the project mutation lock`**
Only one run may write to a project at a time. Wait for the other run (`tq list`, or the web
Queue page), or stop it. A crashed process releases the lock when it exits.

**`cloud mode is on_request: pass --keys namespace.key or set [budget] mode = "dynamic"`**
The default budget mode spends only on keys you name. Add `--keys …`, or switch to
`dynamic` on purpose. See [cost-and-budget.md](cost-and-budget.md).

**`cloud quote: max_usd=… remaining=…` followed by a refusal**
The run's worst-case cost is above what is left of `[budget] monthly_usd` this month.
Narrow it (`--locales`, `--keys`), raise the budget, or wait for next month.
`estimate-cost` shows the figure without running anything.

**`API key missing — set ANTHROPIC_API_KEY …`**
Export the key in the shell (or the taskqueue environment) that runs the command.

## A run does nothing

**`(100%) Everything is already translated and up to date.`**
Nothing is missing or stale for the chosen locales. `status` shows the breakdown. Frozen
locales are skipped unless you name them in `--locales`.

**`skip N pending < min_keys 50`**
Automated chains (sync → translate) skip small backlogs so the GPU is not woken for a few
keys. Run `translate` yourself, which bypasses the floor, or lower `[translate] min_keys`.

**`left as is: pl N existing translation(s) with no state record`**
These values were written outside the engine, and it will not overwrite them. Run
`adopt` to record them. See [existing-project.md](existing-project.md).

**`skipped N queued cloud batch job(s): run aborted`**
A budget check stopped the run partway. The skipped keys stay pending for the next run.

## Results look wrong

**English text left in the target language**
The check rejected the model's output (placeholder lost, wrong script, or an unchanged
copy of the English) and the key stayed pending. The run log names the rule
(`SKIP ns.key: …`). Try a stronger model for that locale (`improve`), or add context notes for short
ambiguous labels.

**A key keeps coming back after I fixed it by hand**
Mark it verified or locked in the web editor (`llm-localizator web`, the row's actions).
Hand edits without a state record also show as `no_state` until you run `adopt`.

**Low scores on correct translations**
Back-translation penalises idioms and register. Check `review-risk`, then mark the good
ones verified in the web editor. Scores never block a write; they only rank work for `improve` and reviewers.

## Validate and CI

**`validate` exits 2 in CI**
Only warnings remain, often V01 for missing keys in a frozen locale. Pass `--locale` with
your active targets, or treat exit 2 as a pass. See [exit-codes.md](exit-codes.md#in-ci).

**`check` or `run-sync --diff` sees every key as untracked in CI**
State lives in the data home on the machine that ran the translations
(`~/.llm_localize/data/<name>/`), and a fresh CI runner has none. Set
`data_home = "project"` and commit `.llm-state/` if CI needs staleness checks.

## Local models (Ollama)

**`ollama` not reachable / `connection refused`**
Start it (`ollama serve`) and check the URL in `[provider] url`. `llm-localizator doctor`
probes it and names the problem.

**Timeouts on the first batch after a model switch**
Loading weights is slow on small GPUs. The run pins one model per job; split locales that
need different models into separate `--locales` runs.

## Still stuck

Run `llm-localizator doctor` and `llm-localizator guide`. Both print what they checked and the
next step.
