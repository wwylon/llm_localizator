"""``metrics``: edit rate, cycle time and coverage trend from history (read-only)."""

from __future__ import annotations

from datetime import datetime, timezone

from ..catalog import build_catalog
from ..catalog.history import HistoryStore
from ..pipeline.metrics import compute_locale_metrics, parse_since
from ..projects import ProjectConfig
from .types import MetricsRequest, OpResult

__all__ = ["op_metrics", "activity_csv", "csv_safe"]

BY_CHOICES = ("user", "locale", "locale+user")


def csv_safe(value: object) -> str:
    """Neutralise spreadsheet formulas: cells starting ``= + - @`` get a leading quote."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def activity_csv(rows: list[dict], by: str) -> str:
    import csv
    import io

    cols = (["locale"] if "locale" in by else []) + (["user"] if "user" in by else []) + [
        "edits", "translate", "web_edit", "last_at",
    ]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([csv_safe(r.get(c)) for c in cols])
    return buf.getvalue()


def _activity_rows(cfg: ProjectConfig, by: str, locales: list[str], since) -> list[dict]:
    from ..catalog.translator_activity import summarize_activity

    events = summarize_activity(cfg.state_root(), limit=0)["timeline"]
    agg: dict[tuple, dict] = {}
    for ev in events:
        if ev["locale"] and locales and ev["locale"] not in locales:
            continue
        if since is not None:
            try:
                if datetime.fromisoformat(ev["ts"].replace("Z", "+00:00")) < since:
                    continue
            except ValueError:
                continue
        key = (ev["locale"] if "locale" in by else "", ev["username"] if "user" in by else "")
        row = agg.setdefault(key, {
            "locale": key[0], "user": key[1], "edits": 0, "translate": 0, "web_edit": 0, "last_at": "",
        })
        row["edits"] += 1
        if ev["trigger"] in ("translate", "web_edit"):
            row[ev["trigger"]] += 1
        row["last_at"] = max(row["last_at"], ev["ts"])
    return sorted(agg.values(), key=lambda r: (-r["edits"], r["locale"], r["user"]))


def _fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%" if pct else f"{value:.1f}"


def _why_low(cfg: ProjectConfig, req: MetricsRequest, locales: list[str]) -> OpResult:
    from ..catalog import ScoreStore
    from ..core.quality import DEFAULT_SCORE_THRESHOLD
    from ..pipeline.score_causes import explain_score, top_causes

    threshold = DEFAULT_SCORE_THRESHOLD if req.threshold is None else req.threshold
    store = ScoreStore(cfg.scores_root())
    out, lines, total = [], [], 0
    for locale in locales:
        explained = []
        for ns, key, score in store.low_score_keys(locale, threshold):
            entry = store.get(locale, ns, key) or {}
            why = explain_score(entry)
            explained.append({"namespace": ns, "key": key, "score": score, **why})
        total += len(explained)
        causes = top_causes(explained)
        out.append({"locale": locale, "low": len(explained), "causes": causes, "keys": explained[:50]})
        lines.append(f"{locale}: {len(explained)} key(s) below {threshold:g}")
        lines.extend(f"  {name:<22}{n:>5}" for name, n in causes)
    return OpResult(
        ok=True, exit_code=0, command="metrics",
        summary=f"{total} low-scored key(s) below {threshold:g}; unscored keys are not counted",
        lines=lines, data={"threshold": threshold, "locales": out},
    )


def op_metrics(cfg: ProjectConfig, req: MetricsRequest, *, catalog=None) -> OpResult:
    now = datetime.now(timezone.utc)
    try:
        since = parse_since(req.since, now)
    except ValueError as exc:
        return OpResult(ok=False, exit_code=1, command="metrics", summary=str(exc))
    locales = list(req.locales or ([req.locale] if req.locale else cfg.active_targets()))
    if req.why_low:
        return _why_low(cfg, req, locales)
    cat = catalog or build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    total = 0
    for ns in cfg.namespaces_for(cat):
        total += sum(
            1 for key, value in cat.load(cfg.source_locale, ns).items()
            if isinstance(value, str) and value.strip() and not cfg.is_skipped(ns, key)
        )
    if req.by:
        if req.by not in BY_CHOICES:
            return OpResult(ok=False, exit_code=1, command="metrics",
                            summary=f"--by must be one of {', '.join(BY_CHOICES)}")
        act = _activity_rows(cfg, req.by, list(req.locales or ([req.locale] if req.locale else [])), since)
        csv_text = activity_csv(act, req.by)
        return OpResult(
            ok=True, exit_code=0, command="metrics",
            summary=f"{sum(r['edits'] for r in act)} edit(s) in {len(act)} row(s)",
            lines=csv_text.splitlines() if req.fmt == "csv" else [
                f"{r['locale'] or '-':<8}{r['user'] or '-':<20}{r['edits']:>6}" for r in act],
            data={"by": req.by, "since": req.since, "rows": act, "csv": csv_text},
        )
    store = HistoryStore(cfg.history_root())
    rows = []
    for locale in locales:
        events = [event for _sk, event, _raw in store.iter_events(locale)]
        rows.append(compute_locale_metrics(
            locale, events, total_keys=total, now=now, since=since,
        ).to_dict())

    lines = [
        f"{'locale':<8}{'machine':>9}{'edited':>8}{'edit rate':>11}"
        f"{'cycle h (mean)':>16}{'coverage':>10}"
    ]
    for row in rows:
        trend = row["coverageTrend"]
        lines.append(
            f"{row['locale']:<8}{row['machineKeys']:>9}{row['editedKeys']:>8}"
            f"{_fmt(row['editRate'], True):>11}{_fmt(row['cycleHoursMean']):>16}"
            f"{_fmt(trend[-1]['coverage'], True) if trend else '-':>10}"
        )
    machine = sum(r["machineKeys"] for r in rows)
    edited = sum(r["editedKeys"] for r in rows)
    summary = (
        f"{edited}/{machine} machine-translated key(s) were edited by a person"
        if machine else "no machine translations in the history window"
    )
    return OpResult(
        ok=True, exit_code=0, command="metrics", summary=summary, lines=lines,
        data={"since": req.since, "locales": rows},
    )
