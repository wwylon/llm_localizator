"""Workflow specs and the entry point over the block-script runner (W-10, ADR-62/63).

No new status value; the interpreter lives in :mod:`.workflow_run`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..catalog.io import atomic_write_text
from ..core.workflow_rules import (
    DEFAULT_HIGH,
    DEFAULT_LOW,
    canonical_rules,
    evaluate_rules,
    legacy_script,
    normalize_workflow,
)
from ..projects import ProjectConfig
from .improve import op_improve
from .rescore import op_rescore
from .review import op_review
from .translate import op_translate
from .types import OpResult

__all__ = [
    "WorkflowSpec",
    "WorkflowRequest",
    "route_action",
    "get_workflow",
    "list_workflows",
    "workflow_assignments",
    "workflow_for_locale",
    "op_workflow_run",
    "load_last_runs",
    "op_translate",
    "op_rescore",
    "op_improve",
    "op_review",
]

ACTION_VERIFY = "verify"
ACTION_IMPROVE = "improve"
ACTION_REVIEW = "review"
ACTION_LLM_REVIEW = "llm_review"
ACTION_FLAG = "flag"


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    high: float = DEFAULT_HIGH
    low: float = DEFAULT_LOW
    rules: tuple[dict[str, Any], ...] = ()
    max_improve_loops: int = 2
    notify: str = "none"
    locales: tuple[str, ...] | None = None
    script: tuple[dict[str, Any], ...] = ()

    def active_script(self) -> list[dict[str, Any]]:
        """The block script; ADR-62 rule tables are expanded on the fly."""
        return list(self.script) or legacy_script(self.active_rules())

    def active_rules(self) -> list[dict[str, Any]]:
        """Explicit rules, or the classic high/low pair."""
        return list(self.rules) or canonical_rules(self.high, self.low)


@dataclass
class WorkflowRequest:
    name: str = "default"
    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    dry_run: bool = False
    route_only: bool = False
    submit: bool = False
    #: Run LLM blocks in this process even when taskqueue is available.
    inline: bool = False
    #: Continue a waiting run instead of starting one.
    resume: str | None = None


def _spec_from(name: str, raw: Any) -> WorkflowSpec:
    if isinstance(raw, WorkflowSpec):
        return raw
    raw = raw or {}
    # The config loader stores already-normalised tables (rules *and* script).
    data = raw if "script" in raw and "rules" in raw else normalize_workflow(raw, name)
    return WorkflowSpec(
        name=name,
        high=data["high"],
        low=data["low"],
        rules=tuple(data["rules"]),
        max_improve_loops=data["max_improve_loops"],
        notify=data["notify"],
        locales=tuple(data["locales"]) if data["locales"] else None,
        script=tuple(data["script"]),
    )


def get_workflow(cfg: ProjectConfig, name: str) -> WorkflowSpec | None:
    workflows = getattr(cfg, "workflows", None) or {}
    spec = workflows.get(name)
    if spec is None:
        return None
    return _spec_from(name, spec)


def list_workflows(cfg: ProjectConfig) -> list[WorkflowSpec]:
    workflows = getattr(cfg, "workflows", None) or {}
    if not workflows:
        return [WorkflowSpec(name="default")]
    out: list[WorkflowSpec] = []
    for name in sorted(workflows):
        got = get_workflow(cfg, name)
        if got is not None:
            out.append(got)
    return out


def workflow_assignments(cfg: ProjectConfig) -> dict[str, Any]:
    """Which workflow applies to each active locale (ADR-63).

    A workflow whose ``locales`` include the locale wins (first alphabetically
    when scopes overlap); locales in no scope use the workflow named ``default``.
    Returns ``{"byLocale": {loc: name|None}, "overlaps": {loc: [names]},
    "uncovered": [loc]}``.
    """
    specs = list_workflows(cfg)
    by_name = {s.name: s for s in specs}
    out: dict[str, str | None] = {}
    overlaps: dict[str, list[str]] = {}
    for loc in cfg.active_targets():
        scoped = sorted(s.name for s in specs if s.locales and loc in s.locales)
        if len(scoped) > 1:
            overlaps[loc] = scoped
        if scoped:
            out[loc] = scoped[0]
        elif "default" in by_name and not by_name["default"].locales:
            out[loc] = "default"
        else:
            out[loc] = None
    return {
        "byLocale": out,
        "overlaps": overlaps,
        "uncovered": [loc for loc, n in out.items() if n is None],
    }


def workflow_for_locale(cfg: ProjectConfig, locale: str) -> str | None:
    return workflow_assignments(cfg)["byLocale"].get(locale)


def route_action(score: float, *, high: float, low: float) -> str:
    """Classic three-band routing (kept for callers that only know high/low)."""
    return evaluate_rules(canonical_rules(high, low), {"score": score})


def _runs_path(cfg: ProjectConfig):
    return cfg.state_root() / "workflow" / "runs.json"


def load_last_runs(cfg: ProjectConfig) -> dict[str, dict[str, Any]]:
    """Last real run per workflow name (empty when none)."""
    try:
        data = json.loads(_runs_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_last_run(cfg: ProjectConfig, name: str, record: dict[str, Any]) -> None:
    runs = load_last_runs(cfg)
    runs[name] = record
    atomic_write_text(_runs_path(cfg), json.dumps(runs, ensure_ascii=False, indent=2))


def op_workflow_run(cfg: ProjectConfig, req: WorkflowRequest) -> OpResult:
    """Start (or ``req.resume``) a block-script run. Queue-backed blocks park the run."""
    from . import workflow_run

    spec = get_workflow(cfg, req.name)
    if spec is None:
        # Empty config still allows the implicit default.
        if req.name == "default" and not (getattr(cfg, "workflows", None) or {}):
            spec = WorkflowSpec(name="default")
        else:
            return OpResult(
                ok=False,
                exit_code=64,
                command="workflow",
                summary=f"unknown workflow {req.name!r}",
            )

    if req.resume:
        got = workflow_run.resume_run(cfg, spec, req.resume)
        if got is None:
            return OpResult(
                ok=False, exit_code=64, command="workflow",
                summary=f"unknown workflow run {req.resume!r}",
            )
        return got

    # A workflow's own locale scope narrows the run; an explicit request narrows further.
    if spec.locales:
        scoped = [loc for loc in (req.locales or spec.locales) if loc in spec.locales]
        req = WorkflowRequest(**{**req.__dict__, "locales": scoped})
    return workflow_run.start_run(cfg, spec, req)
