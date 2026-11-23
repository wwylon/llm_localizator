"""The taskqueue bridge.

We never import ``taskqueue`` (ADR-1). The integration is exactly two things: a
YAML blueprint written into the *consumer's* repo, and a ``tq`` subprocess call.

The VRAM table below is load-bearing, not decoration. Bridge's own blueprint
carries a benchmark: without ``resources.gpu_vram_gib`` the queue co-scheduled
translation alongside other GPU work, ~900 MiB spilled to CPU, and throughput
fell from 40 to 5.6 tok/s. Deriving the reservation from the configured model
roster -- and refusing to emit a blueprint for a model we cannot size -- turns
that from a footgun someone had to discover into a default.

Translate jobs are one taskqueue task per locale (ADR-15) so operators can
schedule ``vi`` then ``de`` without colliding on a single task id. Sync still
``on_complete``s the base ``localize_ui_messages`` task; improve ``depends_on``
that same base id.
"""

from __future__ import annotations

import json

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

_log = logging.getLogger(__name__)

from urllib.parse import urlsplit, urlunsplit

from .config import ProjectConfig

__all__ = [
    "MODEL_VRAM_GIB",
    "VRAM_HEADROOM_GIB",
    "OLLAMA_LOCK",
    "GPU_HUNG_TASK_K",
    "DEFAULT_WALL_CLOCK_CAP_SEC",
    "TASK_IDS",
    "TaskqueueNotFound",
    "SubmitOutcome",
    "derive_vram",
    "locale_task_suffix",
    "task_id_for",
    "generate_blueprint",
    "blueprint_filename",
    "write_blueprints",
    "ensure_blueprint",
    "submit",
    "submit_locales",
    "task_state",
    "tq_available",
]


class TaskqueueNotFound(RuntimeError):
    """The ``tq`` command is not on PATH."""


class SubmitOutcome(NamedTuple):
    """Result of ``submit`` — exit code plus a human-readable message."""

    exit_code: int
    message: str = ""
    task_ids: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


_CANNOT_RETRY_ACTIVE = re.compile(
    r"cannot retry.*status ['\"]?(queued|running)['\"]?",
    re.IGNORECASE | re.DOTALL,
)
_STALE_OVERRIDABLE = re.compile(
    r"overridable_args is empty|not in overridable_args|may not be overridden",
    re.IGNORECASE,
)

#: Bound ``tq`` calls so a wedged daemon cannot freeze the web UI.
_TQ_TIMEOUT_S = 60


TASK_IDS = {
    "translate": "localize_ui_messages",
    "documents": "localize_documents",
    "review": "localize_review",
    "sync": "localize_sync",
    "improve": "localize_improve",
    "rescore": "localize_rescore",
    "bakeoff": "localize_bakeoff",
    "agent-hardcoded": "localize_agent_hardcoded",
}

# Measured resident size, GiB, Q4_K_M quantisation on a 6 GB card.
MODEL_VRAM_GIB: dict[str, float] = {
    "llama3.2": 4.1,
    "llama3.1": 5.6,
    "qwen2.5:7b": 4.8,
    "qwen2.5:14b": 9.2,
    "qwen2.5:3b": 2.6,
    "phi3:mini": 2.4,
    "mistral": 4.4,
    "gemma2:9b": 6.1,
    "aya-expanse:8b": 5.2,
    # ollama list ~3.3 GB Q4_K_M (2026-08-30); Winner for ar/fr/th/vi matrix.
    "translategemma:4b": 3.3,
}
VRAM_HEADROOM_GIB = 0.2

#: Named mutex shared by all Ollama-backed jobs (S2). Allows CPU-only sync to
#: overlap while still serialising GPU weight loads across projects.
OLLAMA_LOCK = "ollama"

# Full-locale translate/improve can exceed 1h (e.g. 1300+ keys ≈ 3–4h).
DEFAULT_WALL_CLOCK_CAP_SEC = 14400

#: Per-task hung override (S8). Single-key LLM calls routinely exceed the
#: global default (~25s of silence) without a new ``(N%)`` line.
GPU_HUNG_TASK_K = 60

#: Service name declared in ``requires_services``. Informational to the queue --
#: the ``health_url`` probe is what actually gates dispatch.
SERVICE_NAME = "ollama"


def derive_vram(models: set[str], overrides: dict[str, float] | None = None) -> float:
    """Reservation for a job that may load any of ``models``.

    Only one model is resident at a time, so the max governs, plus headroom.
    Raises on an unknown model rather than guessing -- a wrong reservation is
    worse than a missing blueprint, because it fails silently at 7x slower.
    """
    table = {**MODEL_VRAM_GIB, **(overrides or {})}
    unknown = sorted(m for m in models if m not in table)
    if unknown:
        raise ValueError(
            f"cannot size GPU reservation: unknown model(s) {', '.join(unknown)}. "
            f"Add them to MODEL_VRAM_GIB or pass an override."
        )
    return round(max(table[m] for m in models) + VRAM_HEADROOM_GIB, 1)


_CLOUD_KINDS = frozenset({"anthropic", "openai", "deepseek", "deepl", "openai_compat"})


def job_runs_on_cloud(cfg: ProjectConfig, job: str, locale: str | None = None) -> bool:
    """True when every model the job may call is hosted, so it needs no GPU, lock, Ollama probe or teardown.

    Needs ``allow_cloud`` and a budget: without them the run falls back to the local provider at run time,
    and that run must keep its GPU reservation. Bakeoff is Ollama-only (ADR-35) and sync calls no model.
    """
    if job in ("sync", "bakeoff") or getattr(cfg, "local_only", False):
        return False
    if not getattr(cfg, "allow_cloud", False) or float(getattr(cfg, "budget_monthly_usd", 0) or 0) <= 0:
        return False
    from ..pipeline.scoring import score_model_for, score_provider_kind
    from ..providers.preflight import looks_like_cloud_model

    project_kind = (cfg.provider.kind or "ollama").lower()
    score_kind = (score_provider_kind(cfg) or "").lower()
    if job == "translate":
        locales = [locale] if locale else cfg.active_targets()
        if not locales or any(cfg.provider_kind_for(loc) not in _CLOUD_KINDS for loc in locales):
            return False
        if score_kind:
            return score_kind in _CLOUD_KINDS
        # Without score_provider a cloud translator scores BT on the cloud only for a hosted score model.
        return looks_like_cloud_model(score_model_for(cfg))
    if project_kind not in _CLOUD_KINDS:
        return False
    if job in ("improve", "rescore") and score_kind:
        return score_kind in _CLOUD_KINDS
    return True


def locale_task_suffix(locale: str) -> str:
    """Sanitize a BCP-47 locale for use in task ids and filenames."""
    return locale.replace("-", "_")


def task_id_for(job: str, locale: str | None = None) -> str:
    if job not in TASK_IDS:
        raise ValueError(f"unknown job {job!r} (known: {', '.join(sorted(TASK_IDS))})")
    base = TASK_IDS[job]
    if locale is None:
        return base
    if job != "translate":
        raise ValueError(f"per-locale task ids are only defined for translate, not {job!r}")
    return f"{base}__{locale_task_suffix(locale)}"


def blueprint_filename(job: str = "translate", locale: str | None = None) -> str:
    if locale is None:
        return f"llm_localizator_{job}.yaml"
    if job != "translate":
        raise ValueError(f"per-locale blueprints are only defined for translate, not {job!r}")
    return f"llm_localizator_{job}_{locale_task_suffix(locale)}.yaml"


def _score_model_pin(cfg: ProjectConfig, locale: str | None = None) -> str:
    """BT / score model for rescore (score_model → improve_model → locale default)."""
    model = cfg.score_model or cfg.improve_model
    if model:
        return model
    return cfg.model_for(locale or "")


def _pinned_model(cfg: ProjectConfig, job: str, locale: str | None = None) -> str:
    """One model per GPU job — mid-run swaps collide with keep_alive (wave 2)."""
    if job == "rescore":
        return _score_model_pin(cfg, locale)
    if job == "improve" and cfg.improve_model:
        return cfg.improve_model
    return cfg.model_for(locale or "")


def _job_models(cfg: ProjectConfig, job: str, pin: str) -> set[str]:
    """Models that may load for VRAM reservation (max governs)."""
    models = {pin}
    if job == "bakeoff":
        from ..pipeline.bakeoff_ledger import PINNED_MODELS

        # One model resident at a time, so the largest candidate sets the reservation.
        models.update(m for m in PINNED_MODELS if m in MODEL_VRAM_GIB)
        score = (cfg.score_model or "").strip()
        if score:
            models.add(score)
    if job == "rescore":
        judge = (cfg.judge_model or "").strip()
        if judge:
            models.add(judge)
    elif job == "translate":
        from ..pipeline.scoring import (
            judge_model_for,
            score_model_for,
            should_defer_scoring_for_translate,
        )

        score = score_model_for(cfg)
        if score and score != pin and not _hosted_scorer(cfg, score):
            models.add(score)
        # The [locales.roles] secondary pass may load its model in the same run.
        for loc in cfg.targets:
            secondary = cfg.secondary_model_for(loc)
            if secondary and secondary in MODEL_VRAM_GIB:
                models.add(secondary)
        if not should_defer_scoring_for_translate(cfg, pin):
            judge = (judge_model_for(cfg) or "").strip()
            if judge:
                models.add(judge)
    from ..providers.preflight import looks_like_cloud_model

    # A hosted scorer or judge next to a local translator takes no VRAM.
    return {m for m in models if m == pin or not looks_like_cloud_model(m)}


def _translate_score_model(cfg: ProjectConfig, pin: str) -> str | None:
    """Local score model when translate runs deferred BT (phase B); None when scoring is hosted."""
    from ..pipeline.scoring import score_model_for

    score = score_model_for(cfg)
    if score and score != pin and not _hosted_scorer(cfg, score):
        return score
    return None


def _hosted_scorer(cfg: ProjectConfig, model: str) -> bool:
    """The scorer runs on a cloud provider, so it takes no VRAM and Ollama never loads or stops it."""
    from ..pipeline.scoring import score_provider_kind
    from ..providers.preflight import looks_like_cloud_model

    return (score_provider_kind(cfg) or "") in _CLOUD_KINDS or looks_like_cloud_model(model)


def _resident_ok_models(cfg: ProjectConfig, job: str, pin: str) -> list[str]:
    """Models that satisfy the VRAM health gate when already loaded."""
    models = [pin]
    if job == "translate":
        score = _translate_score_model(cfg, pin)
        if score:
            models.append(score)
    return models


def _teardown_model(cfg: ProjectConfig, job: str, pin: str) -> str:
    """Model to unload at job end (phase B leaves score model resident)."""
    if job == "translate":
        score = _translate_score_model(cfg, pin)
        if score:
            return score
    return pin


def _url_without_userinfo(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


#: Flags a caller may override for one run, per job (default: locales and dry-run).
_OVERRIDABLE: dict[str, tuple[str, ...]] = {
    "agent-hardcoded": ("--adapter", "--limit", "--dry-run"),
    "translate": ("--locales", "--model", "--engine", "--batch-size", "--force", "--flagged", "--dry-run", "--namespace",
                  "--collection", "--ignore-min-keys", "--manifest", "--keys", "--only-missing", "--sync"),
    "improve": ("--locales", "--model", "--engine", "--limit", "--dry-run", "--include-rejected"),
    "sync": ("--locales", "--dry-run", "--no-translate", "--strict-branch", "--diff", "--exit-nonzero"),
    "rescore": ("--locales", "--namespace", "--model", "--engine", "--dry-run"),
    "bakeoff": ("--locales", "--models", "--limit", "--corpus", "--family", "--matrix", "--force-cells",
                "--dry-run"),
    "documents": ("--locales", "--model", "--engine", "--dry-run", "--doc-dir"),
    "review": ("--locales", "--namespace", "--model", "--engine", "--dry-run", "--keys"),
}
_PRIORITY = {"sync": 30, "improve": 20}
_PLAIN_YAML = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


def _yaml_str(value: str) -> str:
    """A double-quoted YAML scalar (JSON quoting is valid YAML): quotes, backslashes and ``#`` cannot break the file
    (M3: values were pasted between hand-written quotes)."""
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_scalar(value: str) -> str:
    """Plain when it is a simple word (``bridge``), quoted otherwise (``my app: beta``)."""
    return value if _PLAIN_YAML.match(value) else _yaml_str(value)


def generate_blueprint(
    cfg: ProjectConfig,
    job: str = "translate",
    *,
    locale: str | None = None,
    batch_size: int | None = None,
    wall_clock_cap_sec: int = DEFAULT_WALL_CLOCK_CAP_SEC,
    vram_overrides: dict[str, float] | None = None,
    task_id: str | None = None,
    extra_args: dict[str, str] | None = None,
) -> str:
    """Render the blueprint YAML for one job.

    When ``locale`` is set (translate only), emit a single-locale task with no
    ``on_complete`` chain so operators can queue locales independently.

    ``task_id`` + ``extra_args`` render a one-off task (``submit_one_off``): the
    per-run options are baked into ``args`` (``tq retry --set`` only reaches
    ``overridable_args`` and terminal tasks), and no schedule or chain is attached.

    A job that runs entirely on a cloud provider (:func:`job_runs_on_cloud`) gets
    no GPU reservation, ``ollama`` lock, Ollama health probe, teardown or baked
    ``--model`` pin: the run resolves its models from the config.
    """
    if job not in TASK_IDS:
        raise ValueError(f"unknown job {job!r} (known: {', '.join(sorted(TASK_IDS))})")
    if locale is not None and job != "translate":
        raise ValueError(f"per-locale blueprints are only defined for translate, not {job!r}")

    cloud = job_runs_on_cloud(cfg, job, locale)
    llm_job = job != "sync"
    gpu_job = llm_job and not cloud
    pin = _pinned_model(cfg, job, locale) if gpu_job else ""
    models = _job_models(cfg, job, pin) if gpu_job else set()
    vram = derive_vram(models, vram_overrides) if gpu_job else 0.0

    if locale is not None:
        locales = locale
        desc_locales = locale
    else:
        active = cfg.active_targets()
        locales = ",".join(active[:1] if job == "bakeoff" else active)
        frozen_n = len(cfg.frozen)
        desc_locales = (
            f"{len(active)} active locale{'s' if len(active) != 1 else ''}"
            + (f" ({frozen_n} frozen)" if frozen_n else "")
        )

    one_off = task_id is not None
    tid = task_id or task_id_for(job, locale)
    if job == "agent-hardcoded":
        args = ["run-agent-hardcoded", _yaml_scalar(cfg.name), "--llm"]
    else:
        args = [f"run-{job}", _yaml_scalar(cfg.name), "--locales", _yaml_str(locales)]
        # Per-job extra args (values filled from the config).
        extra = {
            # No --model: run-translate resolves model_for(locale) and keeps the [locales.roles] secondary pass.
            # [translate] batch_size (it used to be a hardcoded 10); cloud locales use cloud_batch_size at run time.
            "translate": ["--batch-size", _yaml_str(str(batch_size or cfg.translate_batch_size or 10))],
            "review": ["--model", _yaml_str(pin)],
            "improve": ["--limit", _yaml_str(str(cfg.improve_limit)), "--model", _yaml_str(pin)],
            "rescore": ["--model", _yaml_str(pin)],
            "bakeoff": ["--limit", '"30"'],
            "sync": ["--no-translate"],   # S6: gather-only; translate is re-queued via on_complete.
        }
        job_extra = extra.get(job, [])
        if cloud and "--model" in job_extra:
            at = job_extra.index("--model")
            job_extra = job_extra[:at] + job_extra[at + 2:]
        args += job_extra
        if job == "translate" and locale is not None:
            # Per-locale tasks are the operator thaw/submit path (ADR-15): a plain `tq retry` runs small backlogs too.
            args.append("--ignore-min-keys")
    overridable = list(_OVERRIDABLE.get(job, ("--locales", "--dry-run")))

    if extra_args:
        args = _apply_extra_args(args, extra_args)

    priority = _PRIORITY.get(job, 50)

    health_block = ""
    if gpu_job:
        health_url = _url_without_userinfo(f"{cfg.provider.url.rstrip('/')}/api/tags")
        residents = _resident_ok_models(cfg, job, pin)
        resident_yaml = ", ".join(_yaml_str(m) for m in residents)
        # S1: block while keep_alive residue leaves too little free VRAM.
        health_block = f"""
requires_services:
  - name:              {SERVICE_NAME}
    health_url:        {_yaml_str(health_url)}
    timeout_sec:       5
    min_vram_free_gib: {vram}
    # Pass when the pinned model is already loaded (keep_alive); no unload/reload.
    resident_ok_models: [{resident_yaml}]
"""

    resources = f"""resources:
  cpu_cores:    1
  ram_gib:      0.5
"""
    if cloud:
        resources += """  # Cloud job: hosted models only, no GPU reservation or ollama lock.
"""
    if gpu_job:
        resources += f"""  # Pinned model: {pin}.
  gpu_vram_gib: {vram}
  locks:        [{OLLAMA_LOCK}]
"""

    # Base translate keeps on_complete for sync/improve chaining. Per-locale
    # translate jobs do not — they are operator-scheduled independently.
    chain_block = ""
    if one_off:
        pass  # one-off runs never schedule or chain other tasks
    elif job == "sync":
        chain_block = f"""
# S4: re-queue translate when gather finishes (do not call tq from the task).
on_complete: [{TASK_IDS['translate']}]

# S3: nightly gather before improve.
schedule:
  cron: "30 1 * * *"
"""
    elif job == "improve":
        chain_block = f"""
# S4: wake again whenever translate completes successfully.
depends_on: [{TASK_IDS['translate']}]
rearm_on:   upstream_success

# S3: overnight polish when the card is free.
schedule:
  cron: "0 2 * * *"
"""
    elif job == "translate" and locale is None:
        chain_block = f"""
# Phase 2: automated LLM review after translate completes.
on_complete: [{TASK_IDS['review']}]
"""

    hung_block = ""
    if llm_job:
        hung_block = f"""
# S8: LLM single-key calls can exceed the global hung default (~25s silence).
hung_task_k: {GPU_HUNG_TASK_K}
"""

    teardown_block = ""
    if gpu_job:
        teardown_pin = _teardown_model(cfg, job, pin)
        teardown_block = f"""
# S5: free VRAM before releasing the ollama lock (best-effort).
teardown:
  command:     ollama
  args:        [stop, {_yaml_str(teardown_pin)}]
  best_effort: true
  timeout_sec: 30
"""

    header = (
        "# One-off run generated by llm-localizator submit; removed once it settles.\n"
        if one_off else
        "# Generated by `llm-localizator init --taskqueue` -- do not hand-edit.\n"
        "# Regenerate after changing [locales] or [locales.models] in .llm-localize.toml.\n"
    )
    kind = ("one-off " if one_off else "") + ("cloud " if cloud else "")
    return f"""{header}task_id:          {tid}
description:      {_yaml_str(f"llm_localizator {kind}{job} for {cfg.name} ({desc_locales})")}
command:          llm-localizator
args:             [{', '.join(args)}]
wall_clock_cap_sec: {wall_clock_cap_sec}
idempotent:       true
priority:         {priority}
{health_block}{hung_block}{chain_block}{teardown_block}
# Flags a caller may override for a single run:
#   tq retry {cfg.name}/{tid} --set --locales=pl
# Overrides apply to that run only and never rewrite this file.
overridable_args: [{', '.join(overridable)}]

{resources}"""


def _apply_extra_args(args: list[str], extra: dict[str, str]) -> list[str]:
    """Bake per-run options into a blueprint ``args`` list.

    A flag already present gets its value replaced; a new one is appended.
    ``"true"`` means a bare boolean flag.
    """
    out = list(args)
    for flag, value in extra.items():
        # json.dumps escapes backslashes and quotes the way a YAML double-quoted scalar
        # reads them (a Windows path broke the blueprint before).
        rendered = None if value == "true" else json.dumps(str(value), ensure_ascii=False)
        if flag in out:
            i = out.index(flag)
            has_value = i + 1 < len(out) and out[i + 1].startswith('"')
            if rendered is None:
                if has_value:
                    del out[i + 1]
            elif has_value:
                out[i + 1] = rendered
            else:
                out.insert(i + 1, rendered)
        else:
            out.append(flag)
            if rendered is not None:
                out.append(rendered)
    return out


def write_blueprints(cfg: ProjectConfig, target_dir: Path | None = None) -> list[Path]:
    """Write base job blueprints plus one translate blueprint per target locale."""
    from llm_localizator.catalog.io import atomic_write_text

    out_dir = target_dir or (cfg.root / "experiments" / "operator_queue")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for job in ("translate", "sync", "improve", "review", "documents", "rescore"):
        if job == "documents" and cfg.documents_dir is None:
            continue  # no [documents] dir configured: the job could only fail
        path = out_dir / blueprint_filename(job)
        atomic_write_text(path, generate_blueprint(cfg, job))
        written.append(path)
    for loc in cfg.targets:
        path = out_dir / blueprint_filename("translate", loc)
        atomic_write_text(path, generate_blueprint(cfg, "translate", locale=loc))
        written.append(path)
    return written


def ensure_blueprint(
    cfg: ProjectConfig,
    job: str = "translate",
    *,
    locale: str | None = None,
) -> Path:
    """Write the blueprint if missing or if generated content drifted."""
    from llm_localizator.catalog.io import atomic_write_text

    path = cfg.root / "experiments" / "operator_queue" / blueprint_filename(job, locale)
    desired = generate_blueprint(cfg, job, locale=locale)
    if not path.exists() or path.read_text(encoding="utf-8") != desired:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, desired)
    return path


def tq_available() -> bool:
    return shutil.which("tq") is not None or shutil.which("taskqueue") is not None


def _tq_command() -> list[str]:
    for name in ("tq", "taskqueue"):
        if shutil.which(name):
            return [name]
    raise TaskqueueNotFound(
        "the 'tq' command is not on PATH. Install the taskqueue package, or run the "
        "'run-' variant directly to translate in the foreground."
    )


ONE_OFF_LEDGER = "one_off_jobs.jsonl"
_UNKNOWN_PROJECT = re.compile(r"unknown project", re.I)


def _register_hint(cfg: ProjectConfig) -> str:
    return (
        f"taskqueue does not know project {cfg.name!r}. Add it to ~/.taskqueue/projects.yaml:\n"
        f"  {cfg.name}:\n    root: {cfg.root}\n    queue_dir: experiments/operator_queue\n"
        "then reload the daemon (`tq restart` when idle) and submit again."
    )


def _default_runner(cmd, **kwargs):
    timeout = kwargs.pop("timeout", _TQ_TIMEOUT_S)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)


def _remove_task_row(task: str, *, runner=None) -> None:
    """Best-effort ``tq remove <project/task>`` for a settled one-off; a failure leaves the row for a later sweep."""
    if not task:
        return
    try:
        cmd = [*_tq_command(), "remove", task]
    except TaskqueueNotFound:
        return
    try:
        (runner or _default_runner)(cmd)
    except (OSError, subprocess.SubprocessError):
        pass


def sweep_one_off_jobs(cfg: ProjectConfig, *, runner=None) -> int:
    """Delete settled one-off blueprints (data home + the copy tq keeps in queue_dir).

    ``tq add`` copies the file into the project's ``queue_dir``; leaving it there
    would litter the consumer repo, so it goes once the task is done or failed.
    """
    import json

    ledger = cfg.state_root() / ONE_OFF_LEDGER
    if not ledger.exists():
        return 0
    settled: set[str] = set()
    removed = 0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        state = task_state([row.get("task", "")], runner=runner)
        if state == "pending":
            continue
        for path in (Path(row.get("file", "")), cfg.root / "experiments" / "operator_queue" / Path(row.get("file", "")).name):
            try:
                if path.name and path.is_file():
                    path.unlink()
            except OSError:
                pass
        # The YAML is gone, so the row would only pile up (queue triage 2026-11-14: one consumer kept one).
        _remove_task_row(row.get("task", ""), runner=runner)
        settled.add(line)
        removed += 1
    from llm_localizator.catalog.io import update_text_locked

    # Re-read under the lock and drop only the rows settled here: a job submitted while the tq status calls
    # ran was appended meanwhile and must stay (M0, audit ops #17).
    update_text_locked(ledger, lambda text: "".join(
        f"{row}\n" for row in text.splitlines() if row.strip() and row not in settled))
    return removed


def submit_one_off(
    cfg: ProjectConfig,
    job: str,
    overrides: dict[str, str],
    *,
    locale: str | None = None,
    runner=None,
) -> SubmitOutcome:
    """Queue one run with per-run options baked into its own blueprint.

    ``tq retry --set`` only reaches a task's ``overridable_args`` and only on a
    terminal task, so options such as ``--keys`` cannot ride on the shared task
    (they used to be dropped silently). Each one-off gets a unique task id,
    lives in the engine data home, and is swept once settled.
    """
    import hashlib
    import json
    import time

    from llm_localizator.catalog.io import atomic_write_text

    run = runner or _default_runner
    base = _tq_command()
    sweep_one_off_jobs(cfg, runner=runner)
    extra = dict(overrides)
    if job == "translate":
        extra.setdefault("--ignore-min-keys", "true")  # operator runs bypass the floor
    digest = hashlib.sha1(
        json.dumps([job, locale, sorted(extra.items()), time.time_ns()]).encode("utf-8"),
    ).hexdigest()[:8]
    tid = f"{task_id_for(job, locale)}__oneoff_{digest}"
    text = generate_blueprint(cfg, job, locale=locale, task_id=tid, extra_args=extra)
    path = cfg.state_root() / "one_off" / f"llm_localizator_{tid}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    task = f"{cfg.name}/{tid}"
    try:
        proc = run([*base, "add", str(path), "--project", cfg.name], timeout=_TQ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return SubmitOutcome(1, f"tq timed out after {_TQ_TIMEOUT_S}s while queueing {task}.", (task,))
    msg = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        if _UNKNOWN_PROJECT.search(msg):
            return SubmitOutcome(proc.returncode, _register_hint(cfg), (task,))
        return SubmitOutcome(proc.returncode, msg or f"tq add failed ({proc.returncode})", (task,))
    ledger = cfg.state_root() / ONE_OFF_LEDGER
    from llm_localizator.catalog.io import append_text_line

    append_text_line(ledger, json.dumps({"task": task, "file": str(path), "args": extra, "ts": time.time()}))
    flags = " ".join(k if v == "true" else f"{k}={v}" for k, v in extra.items())
    return SubmitOutcome(0, f"queued one-off {task} ({flags})", (task,))


def submit(
    cfg: ProjectConfig,
    job: str = "translate",
    overrides: dict[str, str] | None = None,
    *,
    locale: str | None = None,
    runner=None,
) -> SubmitOutcome:
    """Enqueue a job, registering the blueprint on first use.

    ``tq retry`` is the normal path; a project whose task the queue has not seen
    yet needs ``tq add`` once. If the task is already ``queued`` or ``running``,
    that is treated as success — the work is already on the schedule.

    For translate, pass ``locale`` to target ``localize_ui_messages__<locale>``.

    Per-run ``overrides`` always go through :func:`submit_one_off`: the shared
    task is retried as-is, so an option can never be dropped on the way.
    """
    if getattr(cfg, "engine_override", None) and job in ("translate", "improve", "review", "rescore", "documents"):
        # A one-run engine (--engine / web form) must reach the queued run too (ADR-156).
        overrides = {**(overrides or {}), "--engine": cfg.engine_override}
    if overrides:
        return submit_one_off(cfg, job, overrides, locale=locale, runner=runner)
    run = runner or _default_runner
    base = _tq_command()
    tid = task_id_for(job, locale)
    task = f"{cfg.name}/{tid}"
    blueprint = ensure_blueprint(cfg, job, locale=locale)
    try:
        proc = run([*base, "retry", task], timeout=_TQ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return SubmitOutcome(
            1,
            f"tq timed out after {_TQ_TIMEOUT_S}s while contacting the queue "
            f"({task}). Is the taskqueue daemon running?",
            (task,),
        )
    msg = (proc.stdout or proc.stderr or "").strip()

    if proc.returncode == 0:
        out = SubmitOutcome(0, msg or f"queued {task}", (task,))
        _log.debug("taskqueue: %s", out.message)
        return out

    combined = msg.lower()
    # Already on the schedule — "submit" intent is satisfied.
    if _CANNOT_RETRY_ACTIVE.search(msg):
        status = "queued" if "queued" in combined else "running"
        out = SubmitOutcome(
            0,
            f"{task} is already {status} — waiting for the scheduler "
            f"(often blocked on free GPU VRAM). Check with: tq describe {task}",
            (task,),
        )
        _log.debug("taskqueue: %s", out.message)
        return out

    if "not found" not in combined and "unknown" not in combined:
        out = SubmitOutcome(
            proc.returncode,
            msg or f"submit failed ({proc.returncode})",
            (task,),
        )
        _log.warning("taskqueue: %s", out.message)
        return out

    if not blueprint.exists():
        out = SubmitOutcome(
            1,
            f"task {task} is not registered and {blueprint} does not exist. "
            f"Run 'llm-localizator init {cfg.name} --taskqueue' first.",
            (task,),
        )
        _log.warning("taskqueue: %s", out.message)
        return out

    try:
        add = run(
            [*base, "add", str(blueprint), "--project", cfg.name],
            timeout=_TQ_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return SubmitOutcome(
            1,
            f"tq timed out after {_TQ_TIMEOUT_S}s while registering {task}.",
            (task,),
        )
    if add.returncode != 0:
        add_msg = (add.stdout or add.stderr or "").strip()
        out = SubmitOutcome(
            add.returncode,
            _register_hint(cfg) if _UNKNOWN_PROJECT.search(add_msg)
            else add_msg or f"add failed ({add.returncode})",
            (task,),
        )
        _log.warning("taskqueue: %s", out.message)
        return out
    # Registration alone does not enqueue — retry so submit actually queues work.
    try:
        proc = run([*base, "retry", task], timeout=_TQ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return SubmitOutcome(
            1,
            f"tq timed out after {_TQ_TIMEOUT_S}s while retrying {task} after add.",
            (task,),
        )
    msg = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode == 0 or _CANNOT_RETRY_ACTIVE.search(msg):
        out = SubmitOutcome(0, msg or f"queued {task}", (task,))
        _log.debug("taskqueue: %s", out.message)
        return out
    # `tq add` may already have queued the task, so a failing retry is not the outcome (problems_open 2026-11-05):
    # trust the queue's own state.
    if task_state([task], runner=lambda cmd, **_kw: run(cmd, timeout=_TQ_TIMEOUT_S)) == "pending":
        out = SubmitOutcome(0, f"queued {task} (registered by tq add; retry said: {msg or proc.returncode})", (task,))
        _log.debug("taskqueue: %s", out.message)
        return out
    out = SubmitOutcome(
        proc.returncode,
        msg or f"submit failed after add ({proc.returncode})",
        (task,),
    )
    _log.debug("taskqueue: %s", out.message)
    return out


def submit_locales(
    cfg: ProjectConfig,
    locales: list[str],
    job: str = "translate",
    overrides: dict[str, str] | None = None,
    *,
    runner=None,
) -> SubmitOutcome:
    """Submit one queue task per locale (translate). Aggregates messages.

    Overall success if **any** locale newly queued or already active; fail only
    when every locale submit fails.
    """
    if job != "translate":
        return submit(cfg, job, overrides, runner=runner)

    if not locales:
        locales = list(cfg.active_targets())

    per_run = {k: v for k, v in (overrides or {}).items() if k != "--locales"}
    if per_run:
        # One run covers every requested locale with the options baked in.
        return submit_one_off(cfg, job, {**per_run, "--locales": ",".join(locales)}, runner=runner)

    messages: list[str] = []
    task_ids: list[str] = []
    any_ok = False
    for loc in locales:
        # Blueprint already pins --locales; drop override so we don't fight it.
        loc_overrides = {k: v for k, v in (overrides or {}).items() if k != "--locales"}
        out = submit(cfg, job, loc_overrides or None, locale=loc, runner=runner)
        messages.append(out.message)
        task_ids.extend(out.task_ids)
        if out.ok:
            any_ok = True

    summary = "\n".join(m for m in messages if m)
    return SubmitOutcome(0 if any_ok else 1, summary, tuple(task_ids))


def task_state(task_ids, *, runner=None) -> str:
    """Probe queue tasks without blocking: ``done``, ``failed`` or ``pending``.

    Uses ``tq wait --timeout 1`` (exit 0 settled ok, 1 failed, 2 timeout,
    3 not found). A missing task is ``failed``: it can never complete.
    """
    ids = [t for t in task_ids if t]
    if not ids:
        return "done"
    run = runner or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True, timeout=_TQ_TIMEOUT_S,
    ))
    try:
        proc = run([*_tq_command(), "wait", *ids, "--timeout", "1"])
    except (subprocess.TimeoutExpired, TaskqueueNotFound):
        return "pending"
    if proc.returncode == 0:
        return "done"
    if proc.returncode == 2:
        return "pending"
    return "failed"
