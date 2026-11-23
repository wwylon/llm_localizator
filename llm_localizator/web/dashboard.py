"""Dashboard overview payloads (split from server_logic)."""

from __future__ import annotations

from ..projects.collections import configured_collections
from . import timing as web_timing
from .server_logic import (
    FULL_FINDINGS_THRESHOLD,
    MAX_PAGE_LIMIT,
    PAGE_SIZE_ALL_THRESHOLD,
    AppState,
    _source_total,
    _tq_on_path,
    cached_status_rows,
    needs_translation,
)


def overview_lite(st: AppState) -> dict:
    """Fast namespace list + config; no per-locale coverage walk.

    Uses configured collections only — never ``discover_collections`` (Wave 1).
    """
    if st._overview_cache is not None:
        return st._overview_cache

    with web_timing.span("overview_lite"):
        with web_timing.span("source_total"):
            source_total, per_ns = _source_total(st)
        namespaces = st.namespaces()
        with web_timing.span("collections"):
            collections = [
                {"name": c.name, "kind": c.kind, "format": c.format}
                for c in configured_collections(st.cfg)
            ]
        payload = {
            "project": st.cfg.name,
            "sourceLocale": st.cfg.source_locale,
            "translateEnabled": getattr(st.cfg, "translate_enabled", True),
            "hasContext": bool(st.cfg.context_dir),
            "taskqueueAvailable": _tq_on_path(),
            "scanAdapter": st.cfg.scan_adapter,
            "collections": collections,
            "activeLocales": st.cfg.active_targets(),
            "frozenLocales": list(st.cfg.frozen),
            "namespaces": [{"name": n, "keys": per_ns[n]} for n in namespaces],
            "sourceTotal": source_total,
            "scaleHints": {
                "pageSizeAllDisabled": source_total > PAGE_SIZE_ALL_THRESHOLD,
                "fullFindingsBackground": source_total > FULL_FINDINGS_THRESHOLD,
                "maxPageLimit": MAX_PAGE_LIMIT,
            },
        }
        st._overview_cache = payload
        return payload


def _overview_from_index(st: AppState, index) -> dict:
    """Coverage counts from a warm full-project message index."""
    counts = {
        loc: {"translated": 0, "stale": 0, "missing": 0}
        for loc in st.cfg.targets
    }
    for row in index.rows:
        for loc in st.cfg.targets:
            status = row.statuses.get(loc, "missing")
            bucket = counts[loc]
            if status == "missing":
                bucket["missing"] += 1
            elif status == "stale":
                bucket["stale"] += 1
            else:
                bucket["translated"] += 1
    source_total = len(index.rows)
    locales_data = []
    for locale in st.cfg.targets:
        row = counts[locale]
        translated = row["translated"]
        locales_data.append({
            "locale": locale,
            "translated": translated,
            "stale": row["stale"],
            "missing": row["missing"],
            "total": source_total,
            "coverage": round(translated / source_total * 100, 1) if source_total else 0.0,
            "frozen": st.cfg.is_frozen(locale),
        })
    return {"locales": locales_data, "sourceTotal": source_total}


def _overview_from_status_rows(st: AppState, rows) -> dict:
    """Coverage counts from ``collect()`` — same numbers, shared with guide/status."""
    by_loc = {r.locale: r for r in rows}
    source_total = 0
    if rows:
        source_total = max(r.total for r in rows)
    else:
        source_total, _ = _source_total(st)
    locales_data = []
    for locale in st.cfg.targets:
        row = by_loc.get(locale)
        if row is None:
            locales_data.append({
                "locale": locale,
                "translated": 0,
                "stale": 0,
                "missing": source_total,
                "total": source_total,
                "coverage": 0.0,
                "frozen": st.cfg.is_frozen(locale),
            })
            continue
        locales_data.append({
            "locale": locale,
            "translated": row.translated,
            "stale": row.stale,
            "missing": row.missing,
            "no_record": row.no_record,
            "total": row.total,
            "coverage": round(row.coverage * 100, 1),
            "frozen": row.frozen,
        })
    return {"locales": locales_data, "sourceTotal": source_total}


def _warm_full_index(st: AppState):
    with st.cache_lock:
        cache = dict(st._message_index_cache or {})
    if not cache:
        return None
    wanted = set(st.cfg.targets)
    for index in cache.values():
        if index.namespace_scope != "__all__":
            continue
        if set(index.locales) != wanted:
            continue
        return index
    return None


def _budget_card(cfg) -> dict:
    """Cloud spend this month against the ceiling, plus the last six months (C-014).

    Local models cost nothing and never appear in the ledger, so a local-only
    project reports ``localOnly`` instead of a zero that looks like a saving.
    """
    from datetime import datetime, timezone

    from ..catalog.budget import BudgetStore

    store = BudgetStore(cfg.budget_root())
    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    spent = store.month_total()
    today = datetime.now(timezone.utc).date()
    projected = None
    if today.day >= 3 and spent > 0:
        import calendar

        projected = round(spent / today.day * calendar.monthrange(today.year, today.month)[1], 6)
    months = store.months()[-6:]
    return {
        "capUsd": cap,
        "spentUsd": spent,
        "remainingUsd": round(max(0.0, cap - spent), 6) if cap > 0 else None,
        "projectedUsd": projected,
        "mode": getattr(cfg, "budget_mode", "on_request") or "on_request",
        "localOnly": bool(getattr(cfg, "local_only", False)),
        "cloudEnabled": bool(getattr(cfg, "allow_cloud", False)),
        "byMonth": [{"month": m, "usd": store.month_total(m)} for m in months],
    }


def _dashboard_extras(st: AppState) -> dict:
    """Pending review, quality summary, and last-run time for the dashboard."""
    pending = 0
    try:
        from ..catalog.review_queue import open_review_queue

        queue = open_review_queue(st.cfg)
        for locale in st.cfg.targets:
            pending += len(queue.open_tickets(locale))
    except OSError:
        pending = 0

    quality_locale = None
    active = st.cfg.active_targets()
    if active:
        quality_locale = active[0]
    elif st.cfg.targets:
        quality_locale = st.cfg.targets[0]

    avg_quality = None
    # bins low→high: <0.5, 0.5–0.6, 0.6–0.7, 0.7–0.8, 0.8–0.9, ≥0.9
    bins = [0, 0, 0, 0, 0, 0]
    if quality_locale:
        stored = st.scores_store().load(quality_locale)
        nums: list[float] = []
        for entry in stored.values():
            if not isinstance(entry, dict):
                continue
            raw = entry.get("quality_score")
            if not isinstance(raw, (int, float)):
                continue
            score = float(raw)
            nums.append(score)
            if score < 0.5:
                bins[0] += 1
            elif score < 0.6:
                bins[1] += 1
            elif score < 0.7:
                bins[2] += 1
            elif score < 0.8:
                bins[3] += 1
            elif score < 0.9:
                bins[4] += 1
            else:
                bins[5] += 1
        if nums:
            avg_quality = round(sum(nums) / len(nums), 2)

    last_run_at = None
    try:
        from ..pipeline.run_manifest import latest_run_record

        with web_timing.span("last_run"):
            rec = latest_run_record(st.cfg.state_root())
        if rec:
            last_run_at = rec.get("finished_at") or rec.get("started_at") or None
    except OSError:
        last_run_at = None

    return {
        "budget": _budget_card(st.cfg),
        "pendingReview": pending,
        "avgQuality": avg_quality,
        "qualityLocale": quality_locale,
        "qualityBins": bins,
        "lastRunAt": last_run_at,
    }


def overview_stats(st: AppState) -> dict:
    """Per-locale coverage; cached separately from overview-lite."""
    if st._overview_stats_cache is not None:
        return st._overview_stats_cache
    with st.stats_lock:
        if st._overview_stats_cache is not None:
            return st._overview_stats_cache
        payload = _compute_overview_stats(st)
        st._overview_stats_cache = payload
        return payload


def _compute_overview_stats(st: AppState) -> dict:
    with web_timing.span("overview_stats"):
        warm = _warm_full_index(st)
        if warm is not None:
            with web_timing.span("index_reuse"):
                payload = _overview_from_index(st, warm)
        else:
            # Prefer collect() (shared with guide/status/progress) over building
            # a full MessageIndex on the dashboard cold path. The editor still
            # primes the index on first /api/messages.
            with web_timing.span("collect_reuse"):
                payload = _overview_from_status_rows(st, cached_status_rows(st))
        # Extras touch the review queue / scores / run manifests — never hold
        # cache_lock across that I/O (Wave C). stats_lock already serialises
        # the cold compute; extras run after the coverage payload is built.
        with web_timing.span("extras"):
            extras = _dashboard_extras(st)
        return {**payload, **extras}


def overview(st: AppState) -> dict:
    """Combined overview (lite + stats) for backwards compatibility."""
    lite = overview_lite(st)
    stats = overview_stats(st)
    out = {**lite, "locales": stats["locales"]}
    for key in (
        "pendingReview", "avgQuality", "qualityLocale",
        "qualityBins", "lastRunAt",
    ):
        if key in stats:
            out[key] = stats[key]
    return out
