"""Usage, progress, and analysis for the operator pages.

These read catalogues, run records, and translation memory. They do not
write, and they do not add a cost field to run manifests.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..catalog import catalog_for
from ..catalog.budget import BudgetStore
from ..catalog.provenance import SOURCE_CLASSES
from ..catalog.tm import DEFAULT_NEAR_OVERLAP, TranslationMemory
from ..pipeline.run_manifest import iter_run_records
from ..projects import ProjectConfig
from .status import collect

_LOCAL_KINDS = frozenset({"ollama", "ctranslate2", "null"})
_FUZZY_HIGH = 0.75
_NEAR_LIMIT = 1


def run_cost_label(cfg: ProjectConfig, record: dict[str, Any]) -> str:
    """Zero for a local run, the stored number, or ``not recorded``."""
    locales = [str(item) for item in (record.get("locales") or [])]
    if locales and all(cfg.provider_kind_for(loc) in _LOCAL_KINDS for loc in locales):
        return "0"
    usd = (record.get("metrics") or {}).get("usd")
    if isinstance(usd, bool) or not isinstance(usd, (int, float)):
        return "not recorded"
    return str(int(usd)) if isinstance(usd, int) else f"{usd:g}"


USAGE_PERIODS = ("month", "last_month", "90d", "all")
_CHART_MAX_BARS = 31


def _month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def _shift_month(day: date, delta: int) -> date:
    index = day.year * 12 + (day.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def _period_bounds(period: str, today: date, first_event: date | None) -> tuple[date, date]:
    """Inclusive (start, end) dates for a period key."""
    if period == "last_month":
        start = _shift_month(today.replace(day=1), -1)
        return start, _shift_month(start, 1) - timedelta(days=1)
    if period == "90d":
        return today - timedelta(days=89), today
    if period == "all":
        return (first_event or today.replace(day=1)), today
    return today.replace(day=1), today


def _event_day(event: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(event.get("ts") or "")[:10])
    except ValueError:
        return None


def _event_tokens(event: dict[str, Any]) -> int | None:
    parts = [event.get("input_tokens"), event.get("output_tokens")]
    nums = [int(p) for p in parts if isinstance(p, (int, float)) and not isinstance(p, bool)]
    return sum(nums) if nums else None


def _ledger_events(store: BudgetStore) -> list[dict[str, Any]]:
    """Every ledger event with its parsed day, across months."""
    out: list[dict[str, Any]] = []
    for month in store.months():
        for event in store.events(month):
            day = _event_day(event)
            if day is not None:
                out.append({**event, "_day": day})
    return out


def _sum_usd(events: list[dict[str, Any]]) -> float:
    return round(sum(float(e.get("usd") or 0) for e in events), 6)


def _daily_series(events: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """Per-day spend; periods longer than the chart limit fold into weekly buckets."""
    span = (end - start).days + 1
    step = 1 if span <= _CHART_MAX_BARS else 7
    buckets: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=step - 1), end)
        usd = _sum_usd([e for e in events if cursor <= e["_day"] <= stop])
        buckets.append({"date": cursor.isoformat(), "usd": usd})
        cursor = stop + timedelta(days=1)
    return buckets[-_CHART_MAX_BARS:] if step == 1 else buckets[-_CHART_MAX_BARS:]


def _strings_by_locale(
    records: list[dict[str, Any]], start: date, end: date, locales: list[str],
) -> dict[str, int]:
    """Strings written per locale in the window; a multi-locale run splits evenly."""
    out = {loc: 0.0 for loc in locales}
    for rec in records:
        if rec.get("command") != "translate":
            continue
        try:
            day = date.fromisoformat(str(rec.get("finished_at") or rec.get("started_at") or "")[:10])
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        targets = [str(loc) for loc in (rec.get("locales") or []) if str(loc) in out]
        written = _run_written(rec)
        if targets and written > 0:
            for loc in targets:
                out[loc] += written / len(targets)
    return {loc: round(n) for loc, n in out.items()}


def _usage_estimate(cfg: ProjectConfig, rows: list[Any], cap: float, remaining: float) -> dict[str, Any]:
    """Cost to finish the due strings on each locale's current provider.

    Local locales are $0. A cloud locale is priced with ``quote_locale``; one
    with no published price is left unpriced rather than guessed (ADR-35).
    """
    from ..catalog.cloud_cost import CLOUD_KINDS, quote_locale
    from ..catalog.pricing import PricingError, estimate_tokens
    from .estimate_cost import sources_for_estimate
    from .types import EstimateCostRequest

    try:
        grouped = sources_for_estimate(cfg, EstimateCostRequest())
    except Exception:  # an unreadable catalogue must not blank the whole page
        grouped = {}
    items: list[dict[str, Any]] = []
    total_usd = 0.0
    total_tokens = 0
    total_keys = 0
    for row in rows:
        loc = row.locale
        kind = (cfg.provider_kind_for(loc) or "").strip().lower()
        sources = grouped.get(loc) or []
        remaining_keys = row.missing + row.stale
        item: dict[str, Any] = {
            "locale": loc, "provider": kind, "remaining": remaining_keys,
            "frozen": bool(row.frozen), "tokens": None, "usd": 0.0, "priced": True,
            "note": "",
        }
        tokens = sum(estimate_tokens(len(s), loc) for s in sources)
        item["tokens"] = tokens or None
        if row.frozen:
            item["note"] = "frozen"
        elif kind not in CLOUD_KINDS:
            item["note"] = "own_hardware"
        else:
            try:
                figures, _kind, model = quote_locale(cfg, loc, sources, batch_size=10) if sources else (None, kind, "")
                item["usd"] = round(figures.max_usd, 6) if figures else 0.0
                item["model"] = model
                if figures is not None and cap > 0 and figures.max_usd > remaining:
                    item["note"] = "over_budget"
                elif not getattr(cfg, "allow_cloud", False):
                    item["note"] = "cloud_off"
            except PricingError:
                item["priced"] = False
                item["usd"] = None
                item["note"] = "no_price"
        # If-cloud reference for local locales; never added to the totals.
        if kind not in CLOUD_KINDS and not row.frozen and sources:
            from ..catalog.pricing import CLOUD_DEFAULT_MODEL

            ref_kind = "anthropic"
            try:
                figures, _k, model = quote_locale(cfg, loc, sources, batch_size=10, kind=ref_kind)
                item["ifCloudUsd"] = round(figures.max_usd, 6)
                item["ifCloudModel"] = model or CLOUD_DEFAULT_MODEL.get(ref_kind, "")
            except Exception:
                item["ifCloudUsd"] = None
        if not row.frozen:
            total_keys += remaining_keys
            total_tokens += tokens
            if isinstance(item["usd"], (int, float)):
                total_usd += item["usd"]
        items.append(item)
    return {
        "rows": items,
        "totalUsd": round(total_usd, 6),
        "totalTokens": total_tokens,
        "totalRemaining": total_keys,
        "unpriced": any(not i["priced"] for i in items),
    }


def usage_runs_payload(cfg: ProjectConfig) -> dict[str, Any]:
    """Lightweight run list for Operations sort keys — no collect()/ledger."""
    runs = []
    for record in iter_run_records(cfg.state_root()):
        runs.append({
            "runId": record.get("run_id"),
            "command": record.get("command"),
            "locales": list(record.get("locales") or []),
            "startedAt": record.get("started_at"),
            "cost": run_cost_label(cfg, record),
        })
    return {"ok": True, "runsOnly": True, "runs": runs}


def usage_payload(
    cfg: ProjectConfig,
    period: str = "month",
    *,
    today: date | None = None,
    catalog=None,
    status_rows=None,
    runs_only: bool = False,
) -> dict[str, Any]:
    if runs_only:
        return usage_runs_payload(cfg)
    if period not in USAGE_PERIODS:
        period = "month"
    today = today or datetime.now(timezone.utc).date()
    records = iter_run_records(cfg.state_root())
    runs = []
    for record in records:
        runs.append({
            "runId": record.get("run_id"),
            "command": record.get("command"),
            "locales": list(record.get("locales") or []),
            "startedAt": record.get("started_at"),
            "cost": run_cost_label(cfg, record),
        })

    store = BudgetStore(cfg.budget_root())
    ledger = _ledger_events(store)
    first = min((e["_day"] for e in ledger), default=None)
    start, end = _period_bounds(period, today, first)
    inside = [e for e in ledger if start <= e["_day"] <= end]
    span = (end - start).days + 1
    prev_start = start - timedelta(days=span)
    prev_end = start - timedelta(days=1)
    previous = [e for e in ledger if prev_start <= e["_day"] <= prev_end]
    spent = _sum_usd(inside)
    prev_spent = _sum_usd(previous)

    projected = None
    if period == "month" and today.day >= 3 and spent > 0:
        days_in_month = (_shift_month(today.replace(day=1), 1) - timedelta(days=1)).day
        projected = round(spent / today.day * days_in_month, 6)

    token_values = [_event_tokens(e) for e in inside]
    tokens = sum(t for t in token_values if t is not None) if any(t is not None for t in token_values) else None

    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    month_spent = store.month_total()
    remaining = max(0.0, cap - month_spent) if cap > 0 else 0.0

    targets = list(cfg.active_targets())
    if catalog is None:
        catalog = catalog_for(cfg)
    if status_rows is None:
        status_rows = collect(cfg, catalog)
    written = _strings_by_locale(records, start, end, targets)

    # Strings written by locales that were billed in this window -> cost per 1k.
    cloud_locales = {str(e.get("locale")) for e in inside}
    cloud_strings = sum(n for loc, n in written.items() if loc in cloud_locales)
    per_1k = round(spent / cloud_strings * 1000, 6) if cloud_strings and spent > 0 else None

    # Provider/model groups. Old events without ``kind`` group under their model.
    groups: dict[str, dict[str, Any]] = {}
    for e in inside:
        label = str(e.get("kind") or "") or "cloud"
        key = f"{label}/{e.get('model') or '?'}"
        g = groups.setdefault(key, {
            "kind": label, "model": str(e.get("model") or ""), "calls": 0,
            "usd": 0.0, "tokens": None, "characters": None,
        })
        g["calls"] += 1
        g["usd"] = round(g["usd"] + float(e.get("usd") or 0), 6)
        t = _event_tokens(e)
        if t is not None:
            g["tokens"] = (g["tokens"] or 0) + t
        c = e.get("characters")
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            g["characters"] = (g["characters"] or 0) + int(c)
    provider_rows = sorted(groups.values(), key=lambda g: g["usd"], reverse=True)
    for g in provider_rows:
        g["share"] = round(g["usd"] / spent, 4) if spent > 0 else 0.0
    local_locales = [loc for loc in targets if cfg.provider_kind_for(loc) in _LOCAL_KINDS]
    local_row = {
        "kind": "local",
        "locales": local_locales,
        "strings": sum(written.get(loc, 0) for loc in local_locales),
        "usd": 0.0,
    }

    locale_rows = []
    for row in status_rows:
        loc = row.locale
        mine = [e for e in inside if str(e.get("locale")) == loc]
        usd = _sum_usd(mine)
        in_tok = [e.get("input_tokens") for e in mine if isinstance(e.get("input_tokens"), (int, float))]
        out_tok = [e.get("output_tokens") for e in mine if isinstance(e.get("output_tokens"), (int, float))]
        strings = written.get(loc, 0)
        locale_rows.append({
            "locale": loc,
            "provider": cfg.provider_kind_for(loc),
            "local": cfg.provider_kind_for(loc) in _LOCAL_KINDS,
            "strings": strings,
            "inputTokens": int(sum(in_tok)) if in_tok else None,
            "outputTokens": int(sum(out_tok)) if out_tok else None,
            "usd": usd,
            "usdPerString": round(usd / strings, 6) if strings and usd > 0 else None,
        })

    return {
        "ok": True,
        "monthUsd": month_spent,
        "runs": runs,
        "period": {"key": period, "from": start.isoformat(), "to": end.isoformat()},
        "cards": {
            "cloudUsd": spent,
            "previousUsd": prev_spent,
            "deltaUsd": round(spent - prev_spent, 6),
            "projectedUsd": projected,
            "tokens": tokens,
            "usdPer1kStrings": per_1k,
        },
        "budget": {
            "capUsd": cap,
            "spentUsd": month_spent,
            "remainingUsd": round(remaining, 6),
            "mode": getattr(cfg, "budget_mode", "on_request") or "on_request",
            "allowCloud": bool(getattr(cfg, "allow_cloud", False)),
            "localOnly": bool(getattr(cfg, "local_only", False)),
            "projectedOverCap": bool(projected is not None and cap > 0 and projected > cap),
        },
        "daily": _daily_series(inside, start, end),
        "providers": {"cloud": provider_rows, "local": local_row},
        "locales": locale_rows,
        "estimate": _usage_estimate(cfg, status_rows, cap, remaining),
    }


def usage_export_csv(cfg: ProjectConfig, period: str = "month", *, today: date | None = None) -> str:
    """Ledger events in the period as CSV (ts, locale, provider, model, tokens, usd)."""
    import csv
    import io

    if period not in USAGE_PERIODS:
        period = "month"
    today = today or datetime.now(timezone.utc).date()
    ledger = _ledger_events(BudgetStore(cfg.budget_root()))
    first = min((e["_day"] for e in ledger), default=None)
    start, end = _period_bounds(period, today, first)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["ts", "locale", "provider", "model", "input_tokens", "output_tokens", "characters", "usd"])
    for e in ledger:
        if start <= e["_day"] <= end:
            writer.writerow([
                e.get("ts", ""), e.get("locale", ""), e.get("kind", ""), e.get("model", ""),
                e.get("input_tokens", ""), e.get("output_tokens", ""), e.get("characters", ""),
                e.get("usd", ""),
            ])
    return buf.getvalue()


def _strings_per_day(records: list[dict[str, Any]]) -> float | None:
    rates: list[float] = []
    for record in records:
        if record.get("command") not in {"translate", "improve"}:
            continue
        wall = record.get("wall_s") or 0
        try:
            wall_s = float(wall)
        except (TypeError, ValueError):
            continue
        if wall_s <= 0:
            continue
        metrics = record.get("metrics") or {}
        counts = record.get("counts") or {}
        written = metrics.get("written", counts.get("written", 0)) or 0
        try:
            n = float(written)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        rates.append(n / wall_s * 86400)
    if not rates:
        return None
    return sum(rates) / len(rates)


_SERIES_DAYS = 30
_ROLLING_DAYS = 7
_VELOCITY_COMMAND = "translate"


def _series_days(today: date) -> list[str]:
    """ISO dates for the trailing window, oldest first, ending today (UTC)."""
    return [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(_SERIES_DAYS - 1, -1, -1)
    ]


def _run_written(rec: dict[str, Any]) -> int:
    metrics = rec.get("metrics") if isinstance(rec.get("metrics"), dict) else {}
    counts = rec.get("counts") if isinstance(rec.get("counts"), dict) else {}
    value = metrics.get("written", counts.get("written", 0)) or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _velocity_by_day(
    records: list[dict[str, Any]], days: list[str], locales: list[str],
) -> dict[str, list[int]]:
    """Strings written per day per locale. A multi-locale run's count is split evenly."""
    index = {day: i for i, day in enumerate(days)}
    out: dict[str, list[int]] = {loc: [0] * len(days) for loc in locales}
    for rec in records:
        # Improve and review rewrite existing strings; only translate adds new ones.
        if rec.get("command") != _VELOCITY_COMMAND:
            continue
        day = str(rec.get("finished_at") or rec.get("started_at") or "")[:10]
        if day not in index:
            continue
        targets = [str(loc) for loc in (rec.get("locales") or []) if str(loc) in out]
        written = _run_written(rec)
        if not targets or written <= 0:
            continue
        share = written / len(targets)
        for loc in targets:
            out[loc][index[day]] += share
    return {loc: [round(n) for n in row] for loc, row in out.items()}


def _quality_by_day(
    entries: dict[str, Any], days: list[str],
) -> tuple[list[float | None], list[float | None]]:
    """Mean score of entries scored on each day, plus a trailing 7-day mean."""
    per_day: dict[str, list[float]] = {}
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        score = entry.get("quality_score")
        scored_on = str(entry.get("scored_at") or "")[:10]
        if isinstance(score, (int, float)) and scored_on:
            per_day.setdefault(scored_on, []).append(float(score))
    daily: list[float | None] = []
    rolling: list[float | None] = []
    for i, day in enumerate(days):
        nums = per_day.get(day, [])
        daily.append(round(sum(nums) / len(nums), 3) if nums else None)
        window: list[float] = []
        for back in range(_ROLLING_DAYS):
            if i - back < 0:
                break
            window.extend(per_day.get(days[i - back], []))
        rolling.append(round(sum(window) / len(window), 3) if window else None)
    return daily, rolling


def _source_series(
    source_days: list[tuple[str, str]], days: list[str],
) -> dict[str, list[int]]:
    """Keys per day by source class (human, tm, mt, ai, imported); dated keys in the window only."""
    index = {day: i for i, day in enumerate(days)}
    out = {cls: [0] * len(days) for cls in SOURCE_CLASSES}
    for cls, day in source_days:
        if day in index and cls in out:
            out[cls][index[day]] += 1
    return out


def _stage_series(
    stage_days: list[tuple[str, str]], days: list[str],
) -> dict[str, list[int]]:
    """Cumulative keys per stage by the day their current state was reached.

    Built from each key's latest history event, so it shows when today's
    state arrived, not every past state. Keys without a dated event or with
    one before the window count from day one.
    """
    size = len(days)
    deltas = {"localized": [0] * size, "llm": [0] * size, "human": [0] * size}
    for bucket, day in stage_days:
        if not day or day < days[0]:
            at = 0
        elif day > days[-1]:
            at = size - 1
        else:
            at = days.index(day)
        deltas["localized"][at] += 1
        if bucket in {"llm_generated", "tm_reused"}:
            deltas["llm"][at] += 1
        elif bucket == "human_edited":
            deltas["human"][at] += 1
    out: dict[str, list[int]] = {}
    for name, row in deltas.items():
        total = 0
        cumulative = []
        for n in row:
            total += n
            cumulative.append(total)
        out[name] = cumulative
    return out


def _eta(remaining: int, per_day: float, today: date) -> dict[str, Any] | None:
    if remaining <= 0:
        return {"days": 0, "date": today.isoformat()}
    if per_day <= 0:
        return None
    wait = math.ceil(remaining / per_day)
    return {"days": wait, "date": (today + timedelta(days=wait)).isoformat()}


def _priority(cfg: ProjectConfig, locale: str) -> str:
    if cfg.is_frozen(locale):
        return "frozen"
    if cfg.is_asap(locale):
        return "asap"
    return "normal"


def progress_payload(
    cfg: ProjectConfig,
    *,
    today: date | None = None,
    catalog=None,
    status_rows=None,
) -> dict[str, Any]:
    if catalog is None:
        catalog = catalog_for(cfg)
    records = iter_run_records(cfg.state_root())
    rate = _strings_per_day(records)
    today = today or datetime.now(timezone.utc).date()
    days = _series_days(today)
    from ..catalog.scores import ScoreStore

    score_store = ScoreStore(cfg.scores_root())
    if status_rows is None:
        status_rows = collect(cfg, catalog)
    velocity = _velocity_by_day(records, days, [row.locale for row in status_rows])
    locales = []
    combined = {name: [0] * len(days) for name in ("localized", "llm", "human")}
    sources = {cls: [0] * len(days) for cls in SOURCE_CLASSES}
    quality: dict[str, dict[str, list[float | None]]] = {}
    for row in status_rows:
        # Stage counts skip stale keys: the status buckets include them, but
        # "localized" does not, so a stale key must not count as verified.
        buckets = [bucket for bucket, _day in row.stage_days]
        human = buckets.count("human_edited")
        llm = buckets.count("llm_generated") + buckets.count("tm_reused")
        item: dict[str, Any] = {
            "locale": row.locale,
            "coverage": row.coverage,
            "translated": row.translated,
            "total": row.total,
            "missing": row.missing,
            "stale": row.stale,
            "frozen": row.frozen,
            "priority": _priority(cfg, row.locale),
            "etaDays": None,
            # Stage counts, as stored in the status buckets. "LLM-verified" is
            # machine output (LLM or TM reuse); "human-verified" is human edits.
            "humanVerified": human,
            "llmVerified": llm,
            "localized": row.translated,
        }
        remaining = row.missing + row.stale
        if not row.frozen and rate is not None and remaining > 0:
            item["etaDays"] = round(remaining / rate, 2)
        series_total = sum(velocity.get(row.locale, []))
        item["velocityPerDay"] = round(series_total / _SERIES_DAYS, 2)
        recent = sum(velocity.get(row.locale, [])[-_ROLLING_DAYS:]) / _ROLLING_DAYS
        item["velocity7PerDay"] = round(recent, 2)
        item["etaDates"] = None
        if not row.frozen:
            verified = human + llm
            item["etaDates"] = {
                "localized": _eta(row.missing + row.stale, recent, today),
                "llm": _eta(row.total - verified, recent, today),
                "human": _eta(row.total - human, recent, today),
            }
        if not row.frozen:
            for name, row_series in _stage_series(row.stage_days, days).items():
                combined[name] = [a + b for a, b in zip(combined[name], row_series)]
            for cls, row_series in _source_series(row.source_days, days).items():
                sources[cls] = [a + b for a, b in zip(sources[cls], row_series)]
        stored = score_store.load(row.locale)
        nums = [
            float(entry["quality_score"])
            for entry in stored.values()
            if isinstance(entry, dict) and isinstance(entry.get("quality_score"), (int, float))
        ]
        item["meanScore"] = round(sum(nums) / len(nums), 3) if nums else None
        daily, rolling = _quality_by_day(stored, days)
        quality[row.locale] = {"meanScore": daily, "rolling7": rolling}
        locales.append(item)

    runs = []
    points: list[dict[str, Any]] = []
    for rec in records[:20]:
        metrics = rec.get("metrics") if isinstance(rec.get("metrics"), dict) else {}
        counts = rec.get("counts") if isinstance(rec.get("counts"), dict) else {}
        keys = metrics.get("written", counts.get("written", counts.get("work", 0)))
        at = rec.get("finished_at") or rec.get("started_at") or ""
        locale_list = [str(loc) for loc in (rec.get("locales") or [])]
        runs.append({
            "command": rec.get("command") or "",
            "locales": locale_list,
            "keys": keys,
            "delta": _run_written(rec),
            "model": rec.get("model") or "",
            "provider": cfg.provider_kind_for(locale_list[0]) if locale_list else "",
            "wallSeconds": rec.get("wall_s"),
            "at": at,
        })
        score = metrics.get("mean_score")
        if isinstance(score, (int, float)):
            for loc in locale_list:
                points.append({
                    "locale": loc,
                    "at": at,
                    "meanScore": round(float(score), 3),
                })
    for item in locales:
        series = [point for point in points if point["locale"] == item["locale"]]
        item["scorePoints"] = list(reversed(series))
    # Prefer the same 30-day velocity window the per-locale cards use so the
    # legacy stringsPerDay figure does not disagree with velocityPerDay.
    active_velocity = [
        float(item.get("velocityPerDay") or 0)
        for item in locales
        if not item.get("frozen")
    ]
    series_rate = (
        sum(active_velocity) / len(active_velocity) if active_velocity else None
    )
    strings_per_day = series_rate if series_rate is not None else rate
    return {
        "ok": True,
        "stringsPerDay": None if strings_per_day is None else round(strings_per_day, 2),
        "locales": locales,
        "runs": runs,
        "series": {
            "days": days,
            "windowDays": _SERIES_DAYS,
            "velocity": velocity,
            "stages": combined,
            "sources": sources,
            "avgPerDay": round(
                sum(sum(velocity.get(i["locale"], [])) for i in locales if not i["frozen"])
                / _SERIES_DAYS, 1),
            "quality": quality,
            "qualityThreshold": 0.55,
        },
    }


def length_ratio_by_locale(cfg: ProjectConfig, catalog) -> list[dict[str, Any]]:
    """Median character-length ratio (target / source) per locale, longest first."""
    ratios: dict[str, list[float]] = {loc: [] for loc in cfg.targets}
    for ns in cfg.namespaces_for(catalog):
        source_map = catalog.load(cfg.source_locale, ns)
        for loc in cfg.targets:
            target_map = catalog.load(loc, ns)
            for key, src in source_map.items():
                if not isinstance(src, str) or not src.strip():
                    continue
                val = target_map.get(key)
                if not isinstance(val, str) or not val.strip() or val == src:
                    continue
                ratios[loc].append(len(val) / len(src))
    out: list[dict[str, Any]] = []
    for loc, nums in ratios.items():
        if not nums:
            continue
        nums.sort()
        mid = nums[len(nums) // 2]
        out.append({
            "locale": loc,
            "medianRatio": round(mid, 3),
            "meanRatio": round(sum(nums) / len(nums), 3),
            "n": len(nums),
        })
    out.sort(key=lambda row: (-row["medianRatio"], row["locale"]))
    return out


def _tm_bucket(tm: TranslationMemory, locale: str, source: str) -> str:
    """``exact`` / ``fuzzyHigh`` / ``fuzzyLow`` / ``noMatch`` for one source string."""
    if tm.exact(locale, source, context="") is not None:
        return "exact"
    hits = tm.near(
        locale, source,
        context="",
        limit=_NEAR_LIMIT,
        min_overlap=DEFAULT_NEAR_OVERLAP,
        semantic=False,
    )
    if not hits:
        return "noMatch"
    best = max(score for _entry, score in hits)
    return "fuzzyHigh" if best >= _FUZZY_HIGH else "fuzzyLow"


def analysis_payload(cfg: ProjectConfig, locale: str) -> dict[str, Any]:
    """One bucket per source key. Counts only; no leverage percentage."""
    if locale not in cfg.targets:
        return {"ok": False, "error": f"{locale!r} is not a target locale"}
    catalog = catalog_for(cfg)
    tm = cfg.open_tm()
    counts = {"exact": 0, "fuzzyHigh": 0, "fuzzyLow": 0, "noMatch": 0}
    by_source: dict[str, int] = {}
    for ns in cfg.namespaces_for(catalog):
        for _key, source in catalog.load(cfg.source_locale, ns).items():
            if not isinstance(source, str):
                source = str(source)
            by_source[source] = by_source.get(source, 0) + 1
            counts[_tm_bucket(tm, locale, source)] += 1
    exact, fuzzy_high = counts["exact"], counts["fuzzyHigh"]
    fuzzy_low, no_match = counts["fuzzyLow"], counts["noMatch"]
    source_count = exact + fuzzy_high + fuzzy_low + no_match
    repetitions = sum(n for n in by_source.values() if n > 1)
    return {
        "ok": True,
        "locale": locale,
        "sourceCount": source_count,
        "exact": exact,
        "fuzzyHigh": fuzzy_high,
        "fuzzyLow": fuzzy_low,
        "noMatch": no_match,
        "repetitions": repetitions,
        "lengthByLocale": length_ratio_by_locale(cfg, catalog),
    }


_DUE_REASONS = frozenset({"missing", "empty", "stale"})
_MIN_HISTORY_WRITTEN = 20
_REPETITIONS_TOP = 20


def _sec_per_string(cfg: ProjectConfig) -> dict[str, float]:
    """Measured seconds per written string, from single-locale translate runs."""
    wall: dict[str, float] = {}
    written: dict[str, int] = {}
    for rec in iter_run_records(cfg.state_root()):
        if rec.get("command") != "translate":
            continue
        locales = [str(loc) for loc in (rec.get("locales") or [])]
        if len(locales) != 1:
            continue
        try:
            wall_s = float(rec.get("wall_s") or 0)
        except (TypeError, ValueError):
            continue
        n = _run_written(rec)
        if wall_s <= 0 or n <= 0:
            continue
        wall[locales[0]] = wall.get(locales[0], 0.0) + wall_s
        written[locales[0]] = written.get(locales[0], 0) + n
    return {
        loc: wall[loc] / written[loc]
        for loc in wall
        if written[loc] >= _MIN_HISTORY_WRITTEN
    }


def _assigned_model(cfg: ProjectConfig, locale: str) -> str:
    role = cfg.roles.get(locale)
    if role and role.primary:
        return role.primary
    return cfg.models.get(locale) or cfg.models.get("default") or cfg.model_for(locale)


def analysis_due_sources(
    cfg: ProjectConfig,
    *,
    namespace: str | None = None,
    locales: list[str] | None = None,
    catalog=None,
    state=None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Return ``(scope_namespaces, {locale: [source, ...]})`` for due strings.

    Same missing/empty/stale set as translate / ``estimate-cost``. Shared by
    analysis phase-1 and phase-2 so the catalogue walk runs once.
    """
    from .catalogue_gaps import iter_catalogue_gaps

    if catalog is None:
        catalog = catalog_for(cfg)
    all_namespaces = list(cfg.namespaces_for(catalog))
    if namespace and namespace not in all_namespaces:
        raise ValueError(f"unknown namespace {namespace!r}")
    scope = [namespace] if namespace else all_namespaces
    targets = [loc for loc in cfg.targets if locales is None or loc in locales]
    due: dict[str, list[str]] = {loc: [] for loc in targets}
    for gap in iter_catalogue_gaps(
        cfg,
        locales=targets,
        namespaces=scope,
        reasons=_DUE_REASONS,
        catalog=catalog,
        state=state,
    ):
        due[gap.locale].append(gap.source)
    return scope, due


def _tm_counts_for_sources(
    tm: TranslationMemory,
    locale: str,
    sources: list[str],
    *,
    fuzzy: bool = False,
) -> dict[str, int]:
    """Bucket due sources; identical strings share one TM lookup.

    Default is exact-only: near-match over tens of thousands of due strings
    routinely exceeds 10s on large projects and stalls the Analysis page.
    Pass ``fuzzy=True`` for the full exact/fuzzyHigh/fuzzyLow split (slow).
    """
    from collections import Counter

    counts = {"exact": 0, "fuzzyHigh": 0, "fuzzyLow": 0, "noMatch": 0}
    for src, n in Counter(sources).items():
        if fuzzy:
            counts[_tm_bucket(tm, locale, src)] += n
        elif tm.exact(locale, src, context="") is not None:
            counts["exact"] += n
        else:
            counts["noMatch"] += n
    return counts


def analysis_report(
    cfg: ProjectConfig,
    namespace: str | None = None,
    locales: list[str] | None = None,
    *,
    catalog=None,
    bands: bool = True,
    fuzzy: bool = False,
    due: dict[str, list[str]] | None = None,
    state=None,
) -> dict[str, Any]:
    """Pre-flight view of what a translate run would touch (read-only).

    Buckets cover *due* strings (missing, empty, stale) only, the same set
    that translate and ``estimate-cost`` use. With ``bands=False``, skip TM
    and length ratios (phase-1 gaps/counts/estimates only). With ``bands=True``
    (default), count exact TM hits only unless ``fuzzy=True``. Pass ``due``
    from a prior ``analysis_due_sources`` call to skip the gap walk.
    """
    from ..catalog.cloud_cost import CLOUD_KINDS, paying_cloud_kind, quote_locale
    from ..catalog.pricing import PricingError

    if catalog is None:
        catalog = catalog_for(cfg)
    all_namespaces = list(cfg.namespaces_for(catalog))
    if namespace and namespace not in all_namespaces:
        return {"ok": False, "error": f"unknown namespace {namespace!r}"}
    scope = [namespace] if namespace else all_namespaces
    targets = [loc for loc in cfg.targets if locales is None or loc in locales]

    tm = cfg.open_tm() if bands else None
    sec_per = _sec_per_string(cfg)
    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    remaining = BudgetStore(cfg.budget_root()).remaining(cap) if cap > 0 else 0.0

    source_strings = source_words = 0
    where: dict[str, list[tuple[str, str]]] = {}
    for ns in scope:
        for key, src in catalog.load(cfg.source_locale, ns).items():
            if not isinstance(src, str) or cfg.is_skipped(ns, key):
                continue
            source_strings += 1
            source_words += len(src.split())
            where.setdefault(src, []).append((ns, key))

    if due is None:
        _scope, due = analysis_due_sources(
            cfg, namespace=namespace, locales=locales, catalog=catalog, state=state,
        )
    else:
        due = {loc: list(due.get(loc, [])) for loc in targets}

    frozen = set(cfg.frozen)
    asap = set(getattr(cfg, "asap", []) or [])
    rows: list[dict[str, Any]] = []
    for loc in targets:
        if bands and tm is not None:
            counts = _tm_counts_for_sources(tm, loc, due[loc], fuzzy=fuzzy)
        else:
            counts = {"exact": 0, "fuzzyHigh": 0, "fuzzyLow": 0, "noMatch": len(due[loc])}
        kind = (cfg.provider_kind_for(loc) or "").strip().lower()
        paying = bool(paying_cloud_kind(cfg, loc))
        max_usd: float | None = 0.0 if not paying else None
        price_error = ""
        if paying and due[loc]:
            try:
                figures, _kind, _model = quote_locale(cfg, loc, due[loc], batch_size=10)
                max_usd = round(figures.max_usd, 6)
            except PricingError as exc:
                price_error = str(exc)
        elif paying:
            max_usd = 0.0
        rate = sec_per.get(loc)
        exact = counts["exact"]
        effort_min = (
            round((len(due[loc]) - exact) * rate / 60, 1)
            if rate is not None else None
        )
        rows.append({
            "locale": loc,
            "due": len(due[loc]),
            "words": sum(len(s.split()) for s in due[loc]),
            **counts,
            "bandsReady": bands,
            "frozen": loc in frozen,
            "asap": loc in asap,
            "provider": {
                "id": cfg.provider_entry_for(loc).id,
                "kind": kind,
                "model": _assigned_model(cfg, loc),
            },
            "cloud": paying,
            "cloudBlocked": kind in CLOUD_KINDS and not paying,
            "maxUsd": max_usd,
            "priceError": price_error,
            "effortMin": effort_min,
        })

    active = [r for r in rows if not r["frozen"]]
    usd_known = all(r["maxUsd"] is not None for r in active)
    effort_known = bool(active) and all(
        r["effortMin"] is not None for r in active if r["due"] - r["exact"] > 0
    )
    totals = {
        "locales": [r["locale"] for r in active],
        "due": sum(r["due"] for r in active),
        "words": sum(r["words"] for r in active),
        "exact": sum(r["exact"] for r in active),
        "fuzzyHigh": sum(r["fuzzyHigh"] for r in active),
        "fuzzyLow": sum(r["fuzzyLow"] for r in active),
        "noMatch": sum(r["noMatch"] for r in active),
        "maxUsd": round(sum(r["maxUsd"] or 0.0 for r in active), 6) if usd_known else None,
        "effortMin": (
            round(sum(r["effortMin"] or 0.0 for r in active), 1) if effort_known else None
        ),
        "bandsReady": bands,
    }

    repeated = sorted(
        ((src, pos) for src, pos in where.items() if len(pos) > 1),
        key=lambda item: (-len(item[1]), item[0]),
    )
    repetitions = {
        "total": sum(len(pos) for _src, pos in repeated),
        "top": [
            {
                "source": src,
                "key": f"{pos[0][0]}.{pos[0][1]}" if pos[0][0] else str(pos[0][1]),
                "namespaces": len({ns for ns, _k in pos}),
                "count": len(pos),
            }
            for src, pos in repeated[:_REPETITIONS_TOP]
        ],
    }

    return {
        "ok": True,
        "namespace": namespace or "",
        "namespaces": all_namespaces,
        "sourceStrings": source_strings,
        "sourceWords": source_words,
        "bandsReady": bands,
        # "exact" = hash hits only (fast); "fuzzy" includes near-match (slow).
        "tmBands": ("fuzzy" if fuzzy else "exact") if bands else "none",
        "locales": rows,
        "active": totals,
        "repetitions": repetitions,
        "budget": {
            "remainingUsd": round(remaining, 6),
            "mode": getattr(cfg, "budget_mode", "on_request") or "on_request",
            "allowCloud": bool(getattr(cfg, "allow_cloud", False)),
        },
        # Length ratios walk every locale catalogue — defer to the bands=1 pass.
        "lengthByLocale": length_ratio_by_locale(cfg, catalog) if bands else [],
    }
