"""Read-only aggregation over persisted run manifests and timestamp lag."""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..catalog import build_catalog
from ..catalog.scores import ScoreStore
from ..catalog.state import StateStore, parse_translated_at
from ..pipeline.run_manifest import iter_run_records
from ..projects import ProjectConfig
from .types import AnalyticsRequest, OpResult

Reporter = Callable[[str], None]

__all__ = ["collect_run_analytics", "collect_lag_analytics", "op_analytics"]


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return parse_translated_at(value)


def _hours_between(later: object, earlier: object) -> float | None:
    end = _parse_iso(later)
    start = _parse_iso(earlier)
    if end is None or start is None:
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    delta = (end - start).total_seconds() / 3600.0
    return delta if delta >= 0 else None


def _filter_runs(
    records: list[dict[str, Any]],
    *,
    command: str | None,
    locale: str | None,
    model: str | None,
    last: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in records:
        if command and row.get("command") != command:
            continue
        if locale and locale not in (row.get("locales") or []):
            continue
        if model and row.get("model") != model:
            continue
        out.append(row)
    if last is not None and last > 0:
        out = out[:last]
    return out


def _rate_for_run(row: dict[str, Any]) -> float | None:
    metrics = row.get("metrics") or {}
    for key in ("keys_per_s", "items_per_s"):
        val = metrics.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    wall = row.get("wall_s")
    if not isinstance(wall, (int, float)) or wall <= 0:
        return None
    metrics_written = metrics.get("written") or metrics.get("processed") or metrics.get("updated")
    counts = row.get("counts") or {}
    n = metrics_written or counts.get("written") or counts.get("processed") or counts.get("updated")
    if n:
        return round(float(n) / float(wall), 4)
    return None


def collect_run_analytics(
    cfg: ProjectConfig,
    *,
    since: str | None = None,
    command: str | None = None,
    locale: str | None = None,
    model: str | None = None,
    last: int | None = None,
) -> dict[str, Any]:
    """Aggregate ``{state}/_runs/*.json`` records."""
    records = _filter_runs(
        iter_run_records(cfg.state_root(), since=since),
        command=command,
        locale=locale,
        model=model,
        last=last,
    )
    runs: list[dict[str, Any]] = []
    rates: list[float] = []
    walls: list[float] = []
    for row in records:
        rate = _rate_for_run(row)
        wall = row.get("wall_s")
        if isinstance(wall, (int, float)):
            walls.append(float(wall))
        if rate is not None:
            rates.append(rate)
        runs.append({
            "run_id": row.get("run_id"),
            "command": row.get("command"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "locales": row.get("locales"),
            "model": row.get("model"),
            "wall_s": wall,
            "rate": rate,
            "metrics": row.get("metrics"),
            "counts": row.get("counts"),
        })

    summary: dict[str, Any] = {
        "runs": len(runs),
        "with_rate": len(rates),
    }
    if rates:
        summary["keys_per_s_median"] = round(statistics.median(rates), 4)
        summary["keys_per_s_mean"] = round(statistics.mean(rates), 4)
    if walls:
        summary["wall_s_median"] = round(statistics.median(walls), 1)
        summary["wall_s_mean"] = round(statistics.mean(walls), 1)

    by_group: dict[tuple[str, str, str], list[float]] = {}
    for row in runs:
        rate = row.get("rate")
        if rate is None:
            continue
        loc = (row.get("locales") or ["*"])[0]
        key = (row.get("command") or "?", loc, row.get("model") or "?")
        by_group.setdefault(key, []).append(float(rate))

    groups = [
        {
            "command": cmd,
            "locale": loc,
            "model": mdl,
            "runs": len(vals),
            "keys_per_s_median": round(statistics.median(vals), 4),
            "keys_per_s_mean": round(statistics.mean(vals), 4),
        }
        for (cmd, loc, mdl), vals in sorted(by_group.items())
    ]

    return {"summary": summary, "groups": groups, "runs": runs}


def collect_lag_analytics(
    cfg: ProjectConfig,
    *,
    locales: list[str] | None = None,
    sample_limit: int = 500,
) -> dict[str, Any]:
    """Derive verify/score lag from existing state + score timestamps."""
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    state = StateStore(cfg.state_root())
    scores = ScoreStore(cfg.scores_root())
    target_locales = locales or list(cfg.active_targets())
    ns_list = cfg.namespaces_for(catalog)

    score_lags_h: list[float] = []
    verify_lags_h: list[float] = []
    heuristic_pending = 0

    for locale in target_locales:
        for ns in ns_list:
            source = catalog.load(cfg.source_locale, ns)
            for key, src in source.items():
                if cfg.is_skipped(ns, key, src):
                    continue
                entry = state.entry(locale, ns, key)
                if not entry:
                    continue
                translated_at = entry.get("translated_at")
                score_row = scores.get(locale, ns, key)
                if score_row:
                    if score_row.get("scorer") == "heuristic":
                        heuristic_pending += 1
                    lag = _hours_between(score_row.get("scored_at"), translated_at)
                    if lag is not None and len(score_lags_h) < sample_limit:
                        score_lags_h.append(lag)
                verified_at = entry.get("verified_at")
                if verified_at:
                    lag = _hours_between(verified_at, translated_at)
                    if lag is not None and len(verify_lags_h) < sample_limit:
                        verify_lags_h.append(lag)

    def _lag_summary(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"samples": 0}
        return {
            "samples": len(values),
            "median_h": round(statistics.median(values), 2),
            "mean_h": round(statistics.mean(values), 2),
            "p90_h": round(sorted(values)[int(len(values) * 0.9) - 1], 2) if len(values) >= 10 else None,
        }

    return {
        "score_lag": _lag_summary(score_lags_h),
        "verify_lag": _lag_summary(verify_lags_h),
        "heuristic_pending": heuristic_pending,
    }


def op_analytics(
    cfg: ProjectConfig,
    req: AnalyticsRequest,
    *,
    report: Reporter | None = None,
) -> OpResult:
    lines: list[str] = []

    def _report(msg: str) -> None:
        lines.append(msg)
        if report is not None:
            report(msg)

    runs = collect_run_analytics(
        cfg,
        since=req.since,
        command=req.run_command,
        locale=req.locale,
        model=req.model,
        last=req.last,
    )
    lag = collect_lag_analytics(cfg, locales=req.locales)

    if req.fmt == "json":
        return OpResult(
            ok=True,
            exit_code=0,
            command="analytics",
            summary=f"{runs['summary'].get('runs', 0)} run(s)",
            lines=lines,
            data={"runs": runs, "lag": lag},
        )

    summary = runs["summary"]
    _report(f"{cfg.name}: {summary.get('runs', 0)} run record(s) in {cfg.state_root() / '_runs'}")
    if summary.get("keys_per_s_median") is not None:
        _report(
            f"  throughput: median {summary['keys_per_s_median']:.4f} keys/s "
            f"(mean {summary['keys_per_s_mean']:.4f})"
        )
    if summary.get("wall_s_median") is not None:
        _report(
            f"  wall time: median {summary['wall_s_median']:.1f}s "
            f"(mean {summary['wall_s_mean']:.1f}s)"
        )
    for group in runs["groups"]:
        _report(
            f"  {group['command']}/{group['locale']}/{group['model']}: "
            f"{group['runs']} run(s), median {group['keys_per_s_median']:.4f} keys/s"
        )
    for row in runs["runs"][:20]:
        rate = row.get("rate")
        rate_s = f"{rate:.4f} keys/s" if rate is not None else "—"
        wall = row.get("wall_s")
        wall_s = f"{wall:.1f}s" if isinstance(wall, (int, float)) else "—"
        locs = ",".join(row.get("locales") or [])
        _report(
            f"  {row.get('started_at', '?')[:19]}Z {row.get('command')} "
            f"[{locs}] {rate_s} wall={wall_s} id={row.get('run_id')}"
        )
    if len(runs["runs"]) > 20:
        _report(f"  … and {len(runs['runs']) - 20} more")

    _report("Lag (hours from translated_at):")
    score_lag = lag["score_lag"]
    if score_lag.get("samples"):
        _report(
            f"  score: median {score_lag['median_h']}h "
            f"(n={score_lag['samples']}, heuristic pending={lag['heuristic_pending']})"
        )
    else:
        _report("  score: no paired timestamps")
    verify_lag = lag["verify_lag"]
    if verify_lag.get("samples"):
        _report(f"  verify: median {verify_lag['median_h']}h (n={verify_lag['samples']})")
    else:
        _report("  verify: no paired timestamps")

    return OpResult(
        ok=True,
        exit_code=0,
        command="analytics",
        summary=f"{summary.get('runs', 0)} run(s) analyzed",
        lines=lines,
        data={"runs": runs, "lag": lag},
    )
