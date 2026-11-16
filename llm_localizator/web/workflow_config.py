"""Workflow config view/save (W-10, ADR-62)."""

from __future__ import annotations

from typing import Any

import tomlkit

from ..core.workflow_rules import (
    ACTIONS,
    BLOCK_TYPES,
    FIELDS,
    LLM_BLOCKS,
    MAX_BLOCKS,
    MAX_DEPTH,
    MAX_LOOPS,
    OPS_BY_FIELD,
    is_canonical,
    legacy_script,
    legacy_thresholds,
    presets,
    normalize_workflow,
    script_warnings,
)
from ..ops.workflow import (
    WorkflowSpec,
    get_workflow,
    list_workflows,
    load_last_runs,
    workflow_assignments,
)
from ..projects.config import ProjectConfig
from .config_write import write_config_atomically

__all__ = [
    "workflow_view", "save_workflows", "get_named_workflow", "add_workflow",
    "workflow_summary",
]

STEPS = ["translate", "rescore", "route"]

_COND = ("field", "op", "value")


def _spec_json(spec: WorkflowSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "high": spec.high,
        "low": spec.low,
        "rules": spec.active_rules(),
        "script": spec.active_script(),
        "warnings": script_warnings(spec.active_script()),
        "maxImproveLoops": spec.max_improve_loops,
        "notify": spec.notify,
        "locales": list(spec.locales) if spec.locales else None,
    }


def _tq() -> bool:
    from ..projects.taskqueue import tq_available

    return tq_available()


def _active_run(cfg: ProjectConfig, name: str) -> dict[str, Any] | None:
    from ..ops.workflow_run import describe_run, latest_run

    rec = latest_run(cfg, name)
    return describe_run(rec) if rec else None


def _options(cfg: ProjectConfig) -> dict[str, Any]:
    try:
        from ..catalog import build_catalog

        catalog = build_catalog(
            cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
        )
        namespaces = list(cfg.namespaces_for(catalog))
    except Exception:  # noqa: BLE001 - options are advisory; never fail the view
        namespaces = []
    return {
        "fields": list(FIELDS),
        "actions": list(ACTIONS),
        "blocks": list(BLOCK_TYPES),
        "presets": presets(),
        "llmBlocks": list(LLM_BLOCKS),
        "ops": {k: list(v) for k, v in OPS_BY_FIELD.items()},
        "maxDepth": MAX_DEPTH,
        "maxBlocks": MAX_BLOCKS,
        "taskqueue": _tq(),
        "locales": list(cfg.active_targets()),
        "namespaces": namespaces,
        "statuses": ["machine", "human", "intentional"],
        "maxLoops": MAX_LOOPS,
        "webhookConfigured": bool(getattr(cfg, "notify_webhook", "")),
    }


def workflow_view(cfg: ProjectConfig) -> dict[str, Any]:
    specs = list_workflows(cfg)
    runs = load_last_runs(cfg)
    return {
        "ok": True,
        "workflows": [
            {**_spec_json(s), "lastRun": runs.get(s.name), "run": _active_run(cfg, s.name)}
            for s in specs
        ],
        "steps": STEPS,
        "addRuleEnabled": True,
        "options": _options(cfg),
        "assignments": workflow_assignments(cfg),
    }


def workflow_summary(cfg: ProjectConfig) -> dict[str, Any]:
    """Light per-locale view for the dashboard / operations / editor chip."""
    assign = workflow_assignments(cfg)
    runs = load_last_runs(cfg)
    rows = {}
    for loc, name in assign["byLocale"].items():
        last = runs.get(name) if name else None
        rows[loc] = {
            "workflow": name,
            "lastRun": last,
            "run": _active_run(cfg, name) if name else None,
        }
    return {
        "ok": True,
        "locales": rows,
        "names": [s.name for s in list_workflows(cfg)],
        "overlaps": assign["overlaps"],
        "uncovered": assign["uncovered"],
    }


def get_named_workflow(cfg: ProjectConfig, name: str) -> dict[str, Any]:
    spec = get_workflow(cfg, name)
    if spec is None and name == "default" and not (cfg.workflows or {}):
        spec = WorkflowSpec(name="default")
    if spec is None:
        return {"ok": False, "error": f"unknown workflow {name!r}"}
    return {
        "ok": True,
        **_spec_json(spec),
        "lastRun": load_last_runs(cfg).get(spec.name),
        "run": _active_run(cfg, spec.name),
        "steps": STEPS,
    }


def _payload_to_table(row: dict[str, Any]) -> dict[str, Any]:
    """Accept camelCase UI keys as well as the TOML spelling."""
    out = dict(row)
    if "maxImproveLoops" in out:
        out["max_improve_loops"] = out.pop("maxImproveLoops")
    for junk in ("name", "lastRun", "run", "warnings"):
        out.pop(junk, None)
    return out


def _block_table(block: dict[str, Any]):
    item = tomlkit.table()
    item["type"] = block["type"]
    if block["type"] == "improve" and block.get("max_loops") is not None:
        item["max_loops"] = block["max_loops"]
    if block["type"] == "if":
        for k in _COND:
            item[k] = block[k]
        for branch in ("then", "else"):
            if block.get(branch):
                aot = tomlkit.aot()
                for child in block[branch]:
                    aot.append(_block_table(child))
                item[branch] = aot
    return item


def _workflow_table(row: dict[str, Any], name: str):
    """One ``[workflows.<name>]`` table from a UI/TOML payload (raises ValueError)."""
    norm = normalize_workflow(_payload_to_table(row), f"workflow {name!r}")
    inner = tomlkit.table()
    script = norm["script"]
    classic = legacy_thresholds(script)
    if classic or (
        "script" not in _payload_to_table(row)
        and is_canonical(norm["rules"], norm["high"], norm["low"])
    ):
        inner["high"] = norm["high"]
        inner["low"] = norm["low"]
    elif script != legacy_script(norm["rules"]):
        blocks = tomlkit.aot()
        for block in script:
            blocks.append(_block_table(block))
        inner["script"] = blocks
    else:
        rules = tomlkit.aot()
        for rule in norm["rules"]:
            item = tomlkit.table()
            for k in ("field", "op", "value", "action"):
                item[k] = rule[k]
            rules.append(item)
        inner["rules"] = rules
    inner["max_improve_loops"] = norm["max_improve_loops"]
    if norm["notify"] != "none":
        inner["notify"] = norm["notify"]
    if norm["locales"]:
        inner["locales"] = norm["locales"]
    return inner


def save_workflows(
    cfg: ProjectConfig,
    *,
    workflows: dict[str, dict[str, Any]],
    notify_webhook: str | None = None,
) -> dict[str, Any]:
    path = cfg.config_path
    if path is None:
        return {"ok": False, "error": "config path is not set"}
    if not isinstance(workflows, dict) or not workflows:
        return {"ok": False, "error": "workflows must be a non-empty object"}
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    table = tomlkit.table()
    for name, row in workflows.items():
        if not str(name).strip():
            return {"ok": False, "error": "workflow name must not be empty"}
        if not isinstance(row, dict):
            return {"ok": False, "error": f"workflow {name!r} must be an object"}
        try:
            inner = _workflow_table(row, name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        table[str(name).strip()] = inner
    doc["workflows"] = table
    hook = (notify_webhook or "").strip()
    if hook:
        from ..ops.notify import validate_webhook_url

        bad = validate_webhook_url(hook)
        if bad:
            return {"ok": False, "error": f"webhook URL: {bad}"}
        if "notify" not in doc:
            doc["notify"] = tomlkit.table()
        doc["notify"]["webhook"] = hook
    new_text = tomlkit.dumps(doc)
    err = write_config_atomically(path, new_text)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True}


def add_workflow(
    cfg: ProjectConfig,
    *,
    name: str,
    row: dict[str, Any],
    overwrite: bool = False,
) -> dict[str, Any]:
    """Merge one workflow into ``cfg``'s ``[workflows]`` (others untouched).

    Locales outside the project's active targets are dropped and reported.
    """
    path = cfg.config_path
    name = str(name or "").strip()
    if path is None:
        return {"ok": False, "error": "config path is not set"}
    if not name:
        return {"ok": False, "error": "workflow name must not be empty"}
    row = dict(row)
    dropped: list[str] = []
    if row.get("locales"):
        active = set(cfg.active_targets())
        dropped = [x for x in row["locales"] if x not in active]
        row["locales"] = [x for x in row["locales"] if x in active] or None
        if row["locales"] is None:
            row.pop("locales")
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    existing = doc.get("workflows")
    if existing is not None and name in existing and not overwrite:
        return {"ok": False, "error": f"workflow {name!r} already exists in the target project"}
    try:
        inner = _workflow_table(row, name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if existing is None:
        doc["workflows"] = tomlkit.table()
    doc["workflows"][name] = inner
    err = write_config_atomically(path, tomlkit.dumps(doc))
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "name": name, "droppedLocales": dropped}
