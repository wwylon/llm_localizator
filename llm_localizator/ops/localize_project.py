"""``localize-project``: the checklist in one report (scan, gaps, cost, next commands).

Read-only by default. ``submit=True`` enqueues one ``translate --only-missing`` job (the same
path as ``translate --submit``, so the cloud gates and the budget cap still apply). The command
never runs a model itself and never touches existing translations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..catalog import catalog_for
from ..pipeline.translate import missing_keys
from ..projects import ProjectConfig
from .estimate_cost import op_estimate_cost
from .scan import op_scan
from .status import collect
from .types import EstimateCostRequest, OpResult, ScanRequest, TranslateRequest


@dataclass
class LocalizeProjectRequest:
    locales: list[str] | None = None
    submit: bool = False
    baseline: bool = False  # record today's validation errors so a later run can tell new from old


def _baseline_path(cfg: ProjectConfig) -> Path:
    return cfg.state_root() / "localize-baseline.json"


def _error_ids(cfg: ProjectConfig, locales: list[str]) -> set[str]:
    """Validation errors as ``locale|namespace|key|check`` ids (messages change, ids do not)."""
    from .types import ValidateRequest
    from .validate import op_validate

    result = op_validate(cfg, ValidateRequest(locales=locales or None))
    return {
        f"{f['locale']}|{f['namespace']}|{f['key']}|{f['check']}"
        for f in result.data.get("findings", []) if f.get("severity") == "error"
    }


def _save_baseline(cfg: ProjectConfig, locales: list[str]) -> int:
    ids = _error_ids(cfg, locales)
    path = _baseline_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"locales": locales, "errors": sorted(ids)}, indent=1), encoding="utf-8")
    return len(ids)


def _validation_lines(cfg: ProjectConfig, locales: list[str]) -> tuple[list[str], dict]:
    """Compare today's validation errors with the saved baseline, if there is one."""
    path = _baseline_path(cfg)
    if not path.exists():
        return ["   no baseline yet: `--baseline` (or `--submit`) records today's errors so the next run "
                "can separate new ones from old ones"], {}
    try:
        saved = set(json.loads(path.read_text(encoding="utf-8")).get("errors", []))
    except (OSError, ValueError):
        return ["   baseline file unreadable; rerun with --baseline"], {}
    now = _error_ids(cfg, locales)
    new, fixed, old = sorted(now - saved), sorted(saved - now), sorted(now & saved)
    lines = [f"   errors now: {len(now)} = {len(new)} new + {len(old)} already in the baseline "
             f"({len(fixed)} fixed since)"]
    lines += [f"   NEW {i}" for i in new[:20]]
    if len(new) > 20:
        lines.append(f"   ... and {len(new) - 20} more new")
    return lines, {"new": new, "old": len(old), "fixed": len(fixed)}


def op_localize_project(cfg: ProjectConfig, req: LocalizeProjectRequest) -> OpResult:
    catalog = catalog_for(cfg)
    explicit = bool(req.locales)
    locales = list(req.locales or [loc for loc in cfg.targets if not cfg.is_frozen(loc)])
    frozen_skipped = [loc for loc in cfg.targets if cfg.is_frozen(loc) and loc not in locales]
    lines: list[str] = [f"project {cfg.name}: source {cfg.source_locale}, locales {', '.join(locales) or 'none'}"]
    if frozen_skipped and not explicit:
        lines.append(f"frozen, left out (name them with --locales to include): {', '.join(frozen_skipped)}")
    data: dict = {"locales": locales}

    # 1. Hardcoded text.
    lines.append("")
    lines.append("1. Hardcoded text")
    if cfg.scan_adapter and cfg.scan_src_dirs:
        scan = op_scan(cfg, ScanRequest(no_write=True))
        data["scan"] = {k: scan.data.get(k) for k in ("toFix", "byConfidence", "bySurface")}
        lines += [f"   {line}" for line in scan.lines[:4] if not line.startswith("warn")]
        lines.append("   Review the list with `agent-hardcoded --format prompt`; key the real UI text first.")
    else:
        lines.append("   no [scan] adapter configured; skipped")

    # 2. Gaps per locale.
    lines.append("")
    lines.append("2. Keys to translate (absent or empty in the target; existing translations are never touched)")
    namespaces = cfg.namespaces_for(catalog)
    gaps = missing_keys(cfg, catalog, locales=locales, namespaces=namespaces) if locales else {}
    counts = {loc: len(gaps.get(loc, ())) for loc in locales}
    status = {row.locale: row for row in collect(cfg, catalog)}
    for loc in locales:
        row = status.get(loc)
        extra = f"; {row.no_record} have text but no state record (run `adopt`)" if row and row.no_record else ""
        lines.append(f"   {loc}: {counts[loc]} missing{extra}")
    data["missing"] = counts
    total = sum(counts.values())

    # 3. Cost.
    lines.append("")
    lines.append("3. Cost")
    if total == 0:
        lines.append("   nothing to translate")
    else:
        try:
            est = op_estimate_cost(cfg, EstimateCostRequest(locales=locales))
            lines += [f"   {line}" for line in est.lines[:6]]
            lines.append("   (estimate-cost counts keys without a state record; the real job uses --only-missing)")
        except Exception as exc:  # noqa: BLE001 - a missing price must not hide the rest of the report
            lines.append(f"   no estimate: {exc}")

    # 4. Validation against the baseline.
    lines.append("")
    lines.append("4. Validation")
    if req.baseline or req.submit:
        count = _save_baseline(cfg, locales)
        lines.append(f"   baseline saved: {count} existing error(s) in {', '.join(locales)}")
        data["baseline"] = count
    else:
        vlines, vdata = _validation_lines(cfg, locales)
        lines += vlines
        data["validation"] = vdata

    # 5. Next commands, or submit.
    lines.append("")
    lines.append("5. Next")
    loc_arg = ",".join(locales)
    if total == 0:
        lines.append("   validate: `llm-localizator validate`")
        return OpResult(ok=True, exit_code=0, command="localize-project",
                        summary="nothing to translate", lines=lines, data=data)
    if not req.submit:
        lines += [
            f"   translate: `llm-localizator translate --only-missing --locales {loc_arg} --dry-run`",
            f"   then:      `llm-localizator translate --only-missing --locales {loc_arg}` "
            "(or rerun this command with --submit)",
            "   validate:  `llm-localizator validate`; compare with the errors that existed before this run.",
        ]
        return OpResult(ok=True, exit_code=0, command="localize-project",
                        summary=f"{total} key(s) to translate; nothing submitted", lines=lines, data=data)

    from .translate import op_translate

    result = op_translate(cfg, TranslateRequest(locales=locales, only_missing=True, submit=True))
    lines.append(f"   submitted: {result.summary}")
    lines += [f"   {line}" for line in result.lines]
    lines.append("   When the job ends: `llm-localizator validate` and `status`.")
    data["submit"] = result.data
    return OpResult(ok=result.ok, exit_code=result.exit_code, command="localize-project",
                    summary=result.summary, lines=lines, data=data)
