"""Cross-locale quality score aggregation — source-hard vs locale-hard triage."""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..catalog import ScoreStore, build_catalog
from ..catalog.io import atomic_write_json
from ..catalog.state import state_key
from ..core.icu import extract_plural_categories
from ..pipeline.run_manifest import RunManifest, config_fingerprint
from ..projects import ProjectConfig
from ..reporting import progress_line, report_run_summary
from .types import HardKeysRequest, OpResult, resolve_namespaces

Reporter = Callable[[str], None]

__all__ = ["collect_hard_keys", "op_hard_keys"]


def collect_hard_keys(
    cfg: ProjectConfig,
    catalog,
    scores: ScoreStore,
    *,
    locales: list[str],
    namespaces: list[str],
    threshold: float = 0.7,
    min_locales: int = 4,
) -> list[dict[str, Any]]:
    """Return tagged keys with cross-locale score stats."""
    out: list[dict[str, Any]] = []
    min_locales = max(1, min_locales)
    # Load each locale's score map once (not scores.get per key × locale).
    score_maps = {locale: scores.load(locale) for locale in locales}

    for ns in namespaces:
        source = catalog.load(cfg.source_locale, ns)
        for key, en in source.items():
            if cfg.is_skipped(ns, key) or not isinstance(en, str) or not en.strip():
                continue
            sk = state_key(ns, key)
            by_locale: dict[str, float] = {}
            for locale in locales:
                row = score_maps[locale].get(sk)
                if row is None or "quality_score" not in row:
                    continue
                by_locale[locale] = float(row["quality_score"])
            if len(by_locale) < min_locales:
                continue
            vals = list(by_locale.values())
            med = float(statistics.median(vals))
            spread = max(vals) - min(vals)
            below = sum(1 for v in vals if v < threshold)
            tag: str | None = None
            if med < threshold and below >= max(2, min_locales // 2):
                tag = "source_hard"
            elif spread >= 0.25 and med >= threshold:
                tag = "locale_outlier"
            elif extract_plural_categories(en):
                cs_ru_low = [
                    by_locale[loc]
                    for loc in ("cs", "ru")
                    if loc in by_locale and by_locale[loc] < threshold
                ]
                if cs_ru_low and med >= threshold:
                    tag = "icu_class"
            if tag is None:
                continue
            outliers = [
                {"locale": loc, "score": score}
                for loc, score in sorted(by_locale.items(), key=lambda row: row[1])
                if score < threshold
            ]
            out.append({
                "namespace": ns,
                "key": key,
                "tag": tag,
                "median_score": round(med, 4),
                "spread": round(spread, 4),
                "locales_scored": len(by_locale),
                "below_threshold": below,
                "outliers": outliers,
            })

    out.sort(key=lambda row: (row["tag"], row["median_score"], row["namespace"], row["key"]))
    return out


def op_hard_keys(
    cfg: ProjectConfig,
    req: HardKeysRequest,
    *,
    report: Reporter | None = None,
) -> OpResult:
    lines: list[str] = []

    def _report(msg: str) -> None:
        lines.append(msg)
        if report is not None:
            report(msg)

    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    scores = ScoreStore(cfg.scores_root())
    locales = cfg.resolve_locales(req.locales)
    namespaces = resolve_namespaces(req.namespace, req.namespaces) or cfg.namespaces_for(catalog)

    manifest = RunManifest.start(
        command="hard-keys",
        locales=locales,
        model=None,
        config_hash=config_fingerprint({
            "threshold": req.threshold,
            "min_locales": req.min_locales,
        }),
        source_locale=cfg.source_locale,
    )

    keys = collect_hard_keys(
        cfg, catalog, scores,
        locales=locales,
        namespaces=namespaces,
        threshold=req.threshold,
        min_locales=req.min_locales,
    )
    total = len(keys)
    manifest.bump("work", total)
    _report(progress_line(0, max(total, 1), f"Scanning hard keys (threshold={req.threshold})"))

    for idx, row in enumerate(keys, start=1):
        label = (
            f"{row['namespace']}.{row['key']} "
            f"tag={row['tag']} median={row['median_score']:.2f}"
        )
        _report(progress_line(idx, total, label))

    report_path: str | None = None
    if not req.dry_run and keys:
        reports_dir = cfg.state_root() / "_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = reports_dir / f"hard_keys_{ts}.json"
        payload = {
            "project": cfg.name,
            "threshold": req.threshold,
            "min_locales": req.min_locales,
            "locales": locales,
            "keys": keys,
        }
        atomic_write_json(path, payload)
        report_path = str(path)

    by_tag: dict[str, int] = {}
    for row in keys:
        by_tag[row["tag"]] = by_tag.get(row["tag"], 0) + 1
    summary = (
        f"{total} hard key(s): "
        + ", ".join(f"{tag}={n}" for tag, n in sorted(by_tag.items()))
        if by_tag else "no hard keys matched filters"
    )
    if report_path:
        summary += f" → {report_path}"

    try:
        manifest.finish(processed=total, total=total, hard_keys=total)
        manifest.write(cfg.state_root())
        report_run_summary(manifest)
    except OSError:
        pass

    return OpResult(
        ok=True,
        exit_code=0,
        command="hard-keys",
        summary=summary,
        lines=lines[-80:] if len(lines) > 80 else lines,
        data={"keys": keys, "reportPath": report_path, "byTag": by_tag},
    )
