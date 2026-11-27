# Concepts

The words the rest of the docs use, in the order you meet them. Each entry says what it is,
where it lives, and which command or config key controls it.

## Project and config

| Term | Meaning |
|---|---|
| **consumer** | Your app's repository. It holds the catalogues and `.llm-localize.toml`; llm-localizator supplies only the machinery. |
| **`.llm-localize.toml`** | The project config: catalogue format and path, source and target locales, models, budget. Reference: [configuration.md](configuration.md). |
| **source locale** | The language the strings are written in (usually `en`). Never translated, only read. |
| **target locale** | A language being translated into (`pl`, `de`, …), listed in `[locales] targets`. |
| **frozen locale** | A target listed in `[locales] frozen`. Default sweeps (translate, improve, `agent-backlog`, queue blueprints) skip it (ADR-16). Missing keys there are warnings (V01), not errors. Name it in `--locales` to work on it anyway. |
| **namespace** | One message file per locale (`auth`, `nav`, …). Single-file projects have one unnamed namespace. Keys are written `namespace.key`. |
| **catalogue** | The message files themselves (JSON, PO, ARB, XLIFF, …). See [catalog-adapters.md](catalog-adapters.md). |

## Who translates

| Term | Meaning |
|---|---|
| **approach** | Who writes the words: `local`, `cloud`, `agent`, `human` or `hybrid`. `llm-localizator approach` lists them with what each needs; `approach --set ID` records your choice. |
| **engine** | A named, benchmarked bundle of models and roles (`claude-haiku`, `local-8gb`, …). `engine recommend` picks one for this machine; `engine apply ID` writes it into the config. Engines change only with bakeoff evidence (ADR-12). |
| **provider** | The backend an engine talks to: `ollama`, `anthropic`, `openai`, `deepseek`, `deepl`, `ctranslate2`. See [providers.md](providers.md). |
| **roles** | Per-locale model roles in `[locales.roles]`: primary translator, optional secondary pass, judge and scorer. |
| **cloud opt-in** | Cloud providers run only with `allow_cloud = true` and a `[budget] monthly_usd` ceiling. Spend is metered and a run that would pass the ceiling is refused. See [cost-and-budget.md](cost-and-budget.md). |

## State and quality

| Term | Meaning |
|---|---|
| **data home** | Where state, history, scores, translation memory and review tickets live. Default `data_home = "engine"`: `~/.llm_localize/data/<name>/` on this machine. `data_home = "project"`: beside the config, committed with the repo (ADR-112). |
| **state** | Per key: the source hash it was translated from, the model, the status. This is how "stale" is detected. The key and hash format is frozen (ADR-7). |
| **status** | `missing`, `stale`, `untranslated`, `machine`, `llm_reviewed`, `agent`, `human`, `verified`, `needs_better_model`. Keys marked verified or locked (web editor row actions) are never overwritten without `--force`. |
| **stale** | The source text changed after the translation was made, so it needs retranslating. |
| **no state record** | A target value exists but the engine never recorded it (hand or agent edit). Translate leaves it alone and says so; `adopt` records it. See [existing-project.md](existing-project.md). |
| **provenance stamp** | Who wrote a value: `machine`, `agent` or `human` (ADR-19). Out-of-band edits get stamped by `adopt`. |
| **quality score** | 0–1 per key from back-translation and, for risky keys, an LLM judge (LQS, ADR-158). Below the cut, `improve` retries with a stronger model. |
| **draft** | A proposed value waiting for a reviewer (`hybrid` approach, review queue). |
| **glossary** | Approved terms and do-not-translate words (the file named by `[prompt] glossary`), fed into every prompt. `glossary-learn` proposes terms from human corrections. |
| **translation memory (TM)** | Earlier accepted translations, reused exactly or as few-shot examples. |

## Running work

| Term | Meaning |
|---|---|
| **taskqueue (`tq`)** | The scheduler for long GPU or cloud runs (ADR-1). `translate` queues through it when installed, and runs inline when it is not. |
| **blueprint** | The generated task YAML for one job, in `experiments/operator_queue/`. Regenerate it; never hand-edit it. |
| **flush** | Writing a batch of results to catalogues and state. An interrupted flush leaves a journal that blocks the next run until you run `acknowledge-flush`. |
| **mutation lock** | One writer per project at a time. A second run waits, then fails with "another process holds the project mutation lock". |
| **pseudo-locale (`en-XX`)** | A fake locale that wraps every string, so untranslated (hardcoded) text stands out in the running app. |
| **hardcoded string** | UI text in source code instead of the catalogue. `agent-hardcoded` reports them; `explain-scan FILE:LINE` says why a line was or wasn't reported. |
