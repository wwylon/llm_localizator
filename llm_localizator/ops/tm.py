"""Translation-memory search, leverage, and TMX handoff."""

from __future__ import annotations

from pathlib import Path

from ..catalog import catalog_for
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.coherence_index import CoherenceIndex
from ..catalog.history import HistoryStore, make_history_event
from ..catalog.tm import ConcordanceHit, TranslationMemory
from ..catalog.tmx import export_tmx, parse_tmx, score_of
from ..core.hash import src_hash
from ..projects import ProjectConfig
from .types import ConcordanceRequest, OpResult, TmExportRequest, TmImportRequest

__all__ = [
    "op_concordance",
    "op_tm_export",
    "op_tm_import",
    "leverage_payload",
    "browse_payload",
]

_CONFLICTS = {"skip", "overwrite-if-higher", "always"}


def _catalog(cfg: ProjectConfig):
    return catalog_for(cfg)


def _provenance_status(*, provider: str | None, superseded: bool) -> str:
    if superseded:
        return "stale"
    kind = (provider or "").strip().lower()
    if kind == "human":
        return "human"
    if kind == "import":
        return "imported"
    if kind == "agent":
        return "agent"
    return "machine"


def _match_pct(query: str, source: str) -> int:
    needle = (query or "").casefold().strip()
    if not needle:
        return 0
    return min(100, round(100 * len(needle) / max(len(source or ""), 1)))


def _keys_by_source(cfg: ProjectConfig) -> dict[str, tuple[str, str]]:
    """Map source text to the first (namespace, key) carrying it."""
    catalog = _catalog(cfg)
    found: dict[str, tuple[str, str]] = {}
    for namespace in cfg.namespaces_for(catalog):
        for key, value in catalog.load(cfg.source_locale, namespace).items():
            found.setdefault(value, (namespace, key))
    return found


def _hit(hit: ConcordanceHit, *, query: str = "",
         keys: dict[str, tuple[str, str]] | None = None, fuzzy: bool = False) -> dict:
    entry = hit.entry
    namespace, key = (keys or {}).get(entry.source, (None, None))
    return {
        "namespace": namespace,
        "key": key,
        "source": entry.source,
        "translation": entry.text,
        "rank": hit.score,
        "matchPct": round(100 * hit.score) if fuzzy else _match_pct(query, entry.source),
        "quality": entry.quality_score,
        "verified": entry.verified,
        "superseded": hit.superseded,
        "status": _provenance_status(provider=entry.provider, superseded=hit.superseded),
        "provider": entry.provider,
        "model": entry.model,
        "createdAt": entry.created_at,
    }


def _siblings(cfg: ProjectConfig, locale: str, namespace: str, key: str) -> list[dict]:
    catalog = _catalog(cfg)
    source_map = catalog.load(cfg.source_locale, namespace)
    source = source_map.get(key) or ""
    if not source:
        return []
    rows: list[tuple[str, str, str, str]] = []
    for ns in cfg.namespaces_for(catalog):
        english = catalog.load(cfg.source_locale, ns)
        target = catalog.load(locale, ns)
        for item_key, text in english.items():
            rows.append((ns, item_key, text, target.get(item_key) or ""))
    index = CoherenceIndex()
    index.build(rows)
    return [
        {
            "namespace": hit.namespace,
            "key": hit.key,
            "source": hit.source,
            "translation": hit.target,
        }
        for hit in index.exact_siblings(namespace, key, source)
    ]


def op_concordance(cfg: ProjectConfig, req: ConcordanceRequest) -> OpResult:
    if not req.locale:
        return OpResult(ok=False, exit_code=64, command="concordance", summary="locale is required")
    if req.mode not in ("substring", "fuzzy"):
        return OpResult(ok=False, exit_code=64, command="concordance",
                        summary="mode must be substring or fuzzy")
    tm = cfg.open_tm()
    if req.mode == "fuzzy":
        floor = min(1.0, max(0.1, float(req.min_similarity)))
        limit = min(max(int(req.limit), 1), 100)
        hits = [
            ConcordanceHit(entry, score, False)
            for entry, score in tm.near(
                req.locale, req.query, limit=limit, min_overlap=floor, exclude_exact=False,
            )
        ] if (req.query or "").strip() else []
    else:
        hits = tm.concordance(
            req.locale,
            req.query,
            source=req.source,
            target=req.target,
            limit=req.limit,
        )
    lines = []
    for hit in hits:
        mark = " (superseded)" if hit.superseded else ""
        lines.append(f"{hit.entry.source} | {hit.entry.text}{mark}")
    keys = _keys_by_source(cfg)
    data = {"matches": [_hit(hit, query=req.query, keys=keys, fuzzy=req.mode == "fuzzy") for hit in hits]}
    if req.namespace and req.key:
        data["siblings"] = _siblings(cfg, req.locale, req.namespace, req.key)
    return OpResult(
        ok=True,
        exit_code=0,
        command="concordance",
        summary=f"{len(hits)} match(es)",
        lines=lines,
        data=data,
    )


def _tm_line_count(tm: TranslationMemory, locale: str) -> int:
    """Non-empty JSONL lines for a locale (same basis as ``len(tm.rows)``)."""
    path = tm.path_for(locale)
    if not path.is_file():
        return 0
    count = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
    except OSError:
        return 0
    return count


def leverage_payload(cfg: ProjectConfig, *, catalog=None, status_rows=None) -> dict:
    """Coverage + TM provenance buckets. Accepts AppState caches when available."""
    from .status import collect

    if catalog is None:
        catalog = _catalog(cfg)
    rows = status_rows if status_rows is not None else collect(cfg, catalog)
    locales = [
        {
            "locale": row.locale,
            "frozen": row.frozen,
            "total": row.total,
            "translated": row.translated,
            "stale": row.stale,
            "missing": row.missing,
            "coverage": row.coverage,
            "tm_reused": row.tm_reused,
            "llm_generated": row.llm_generated,
            "human_edited": row.human_edited,
            "agent_edited": row.agent_edited,
            "imported": row.imported,
        }
        for row in rows
    ]
    totals = {
        "tm_reused": sum(row["tm_reused"] for row in locales),
        "llm_generated": sum(row["llm_generated"] for row in locales),
        "human_edited": sum(row["human_edited"] for row in locales),
        "agent_edited": sum(row["agent_edited"] for row in locales),
        "imported": sum(row["imported"] for row in locales),
    }
    totals["classified"] = (
        totals["tm_reused"]
        + totals["llm_generated"]
        + totals["human_edited"]
        + totals["agent_edited"]
        + totals["imported"]
    )
    tm = cfg.open_tm()
    tm_entries = 0
    tm_locales = 0
    for row in locales:
        count = _tm_line_count(tm, row["locale"])
        if count:
            tm_locales += 1
            tm_entries += count
    return {
        "locales": locales,
        "totals": totals,
        "tmEntries": tm_entries,
        "tmLocales": tm_locales,
    }


def browse_payload(cfg: ProjectConfig, locale: str, *, provider: str = "", text: str = "",
                   limit: int = 250) -> dict:
    tm = cfg.open_tm()
    rows = tm.browse(locale, provider=provider, text=text, limit=limit)
    keys = _keys_by_source(cfg)
    providers = sorted({
        entry.provider for entry, _ in tm.rows(locale) if entry.provider
    })
    return {
        "locale": locale,
        "providers": providers,
        "rows": [
            {
                "namespace": keys.get(entry.source, (None, None))[0],
                "key": keys.get(entry.source, (None, None))[1],
                "source": entry.source,
                "translation": entry.text,
                "provider": entry.provider,
                "model": entry.model,
                "quality": entry.quality_score,
                "verified": entry.verified,
                "createdAt": entry.created_at,
                "superseded": superseded,
                "status": _provenance_status(
                    provider=entry.provider, superseded=superseded,
                ),
            }
            for entry, superseded in rows
        ],
    }


def op_tm_export(cfg: ProjectConfig, req: TmExportRequest) -> OpResult:
    if not req.locale:
        return OpResult(ok=False, exit_code=64, command="tm-export", summary="locale is required")
    tm = cfg.open_tm()
    xml = export_tmx(tm, req.locale, cfg.source_locale)
    if req.path:
        path = Path(req.path)
        if not path.is_absolute():
            path = cfg.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding="utf-8")
    return OpResult(
        ok=True,
        exit_code=0,
        command="tm-export",
        summary=f"exported {req.locale}",
        data={"locale": req.locale, "tmx": xml, "path": req.path},
    )


def _decision(existing, incoming_score, conflict: str) -> str:
    if existing is None:
        return "added"
    if conflict == "always":
        return "overwritten"
    if conflict == "overwrite-if-higher":
        incoming = 0.0 if incoming_score is None else float(incoming_score)
        if incoming > score_of(existing):
            return "overwritten"
        return "skipped"
    return "skipped"


def _matching_keys(cfg: ProjectConfig, source: str) -> list[tuple[str, str]]:
    catalog = _catalog(cfg)
    found: list[tuple[str, str]] = []
    for namespace in cfg.namespaces_for(catalog):
        for key, value in catalog.load(cfg.source_locale, namespace).items():
            if value == source:
                found.append((namespace, key))
    return found


def op_tm_import(cfg: ProjectConfig, req: TmImportRequest) -> OpResult:
    if req.dry_run:
        return _op_tm_import(cfg, req)
    with project_mutation_lock(cfg):
        return _op_tm_import(cfg, req)


def _op_tm_import(cfg: ProjectConfig, req: TmImportRequest) -> OpResult:
    if not req.locale:
        return OpResult(ok=False, exit_code=64, command="tm-import", summary="locale is required")
    conflict = req.conflict or "skip"
    if conflict not in _CONFLICTS:
        return OpResult(
            ok=False, exit_code=64, command="tm-import",
            summary=f"unknown conflict mode {conflict!r}",
        )
    if req.tmx:
        xml = req.tmx
    elif req.path:
        try:
            path = Path(req.path)
            if not path.is_absolute():
                path = cfg.root / path
            xml = path.read_text(encoding="utf-8")
        except OSError as exc:
            return OpResult(
                ok=False, exit_code=64, command="tm-import",
                summary=f"cannot read TMX: {exc}",
            )
    else:
        return OpResult(ok=False, exit_code=64, command="tm-import", summary="TMX path or text is required")
    try:
        units = parse_tmx(xml, req.locale)
    except ValueError as exc:
        return OpResult(ok=False, exit_code=64, command="tm-import", summary=str(exc))

    tm = cfg.open_tm()
    history = HistoryStore(cfg.history_root())
    catalog = _catalog(cfg)
    counts = {"added": 0, "overwritten": 0, "skipped": 0, "unkeyed": 0, "history": 0}
    for unit in units:
        current = tm.exact(req.locale, unit["source"])
        decision = _decision(current, unit["quality_score"], conflict)
        if decision == "skipped":
            counts["skipped"] += 1
            continue
        counts[decision] += 1
        keys = _matching_keys(cfg, unit["source"])
        if not keys:
            counts["unkeyed"] += 1
        if req.dry_run:
            continue
        tm.record(
            locale=req.locale,
            source=unit["source"],
            text=unit["text"],
            model=unit["model"],
            provider=unit["provider"],
            quality_score=unit["quality_score"],
            verified=unit["verified"],
        )
        for namespace, key in keys:
            prev = catalog.load(req.locale, namespace).get(key)
            history.append(req.locale, make_history_event(
                namespace=namespace,
                key=key,
                prev=prev,
                next_text=unit["text"],
                model=unit["model"] or "import",
                status="machine",
                src_sha=src_hash(unit["source"]),
                trigger="import",
                provider="import",
                quality_score=unit["quality_score"],
            ))
            counts["history"] += 1
    summary = (
        f"added {counts['added']}, overwritten {counts['overwritten']}, "
        f"skipped {counts['skipped']}"
        + (" (dry-run)" if req.dry_run else "")
    )
    return OpResult(
        ok=True,
        exit_code=0,
        command="tm-import",
        summary=summary,
        lines=[summary],
        data={"locale": req.locale, "dry_run": req.dry_run, "counts": counts},
    )
