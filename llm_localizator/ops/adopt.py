"""Adopt catalogue values into state when provenance is missing (no LLM)."""

from __future__ import annotations

from collections import Counter

from ..catalog import StateStore, build_catalog
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import now_iso
from ..core.hash import src_hash
from ..core.quality import score_translation
from ..pipeline.recording import provenance_stores, record_candidate
from ..projects import ProjectConfig, load_glossary
from .catalogue_gaps import iter_catalogue_gaps
from .types import AdoptRequest, OpResult, resolve_namespaces

__all__ = ["op_adopt"]


def _rename_source(state, gap, source_keys: set) -> tuple[str, dict] | None:
    """A single orphan state entry with this key's source hash means the key was renamed.

    Returns (old key, carried entry) so provenance survives; None when ambiguous.
    """
    want = src_hash(gap.source)
    prefix = f"{gap.namespace}." if gap.namespace else ""
    hits = []
    for raw, entry in state.load(gap.locale).items():
        if not raw.startswith(prefix) or entry.get("src_sha") != want:
            continue
        old_key = raw[len(prefix):]
        if old_key != gap.key and old_key not in source_keys:
            hits.append((old_key, entry))
    if len(hits) != 1:
        return None
    entry = dict(hits[0][1])
    entry["tgt_sha"] = src_hash(gap.target.strip())
    return hits[0][0], entry


def op_adopt(cfg: ProjectConfig, req: AdoptRequest) -> OpResult:
    """Stamp non-empty catalogue keys that have no state entry.

    Does not rewrite catalogue files. Does not refresh stale keys (those stay
    in the agent backlog for retranslation).
    """
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    namespaces = resolve_namespaces(req.namespace, req.namespaces)
    gaps = list(
        iter_catalogue_gaps(
            cfg,
            locales=req.locales,
            namespaces=namespaces,
            reasons=("no_state", "external_edit"),
            limit=req.limit,
            catalog=catalog,
        )
    )

    # A changed value under a human-verified entry is a conflict, not an adoption (ADR-48).
    store = StateStore(cfg.state_dir) if cfg.state_dir else None
    held = [g for g in gaps if g.reason == "external_edit" and store
            and (store.entry(g.locale, g.namespace, g.key) or {}).get("status") == "human"]
    gaps = [g for g in gaps if g not in held]
    held_rows = [{"locale": g.locale, "namespace": g.namespace, "key": g.key} for g in held]

    by_locale: Counter[str] = Counter(g.locale for g in gaps)
    lines = [
        f"{loc}: {n} key(s) to adopt"
        for loc, n in sorted(by_locale.items())
    ]
    if req.dry_run:
        return OpResult(
            ok=True,
            exit_code=0,
            command="adopt",
            summary=f"would adopt {len(gaps)} key(s) (dry-run)",
            lines=lines,
            data={
                "adopted": 0,
                "wouldAdopt": len(gaps),
                "dryRun": True,
                "byLocale": dict(by_locale),
                "keys": [
                    {
                        "locale": g.locale,
                        "namespace": g.namespace,
                        "key": g.key,
                    }
                    for g in gaps
                ],
            },
        )

    if not gaps:
        return OpResult(
            ok=True,
            exit_code=0,
            command="adopt",
            summary="nothing to adopt",
            lines=lines,
            data={"adopted": 0, "byLocale": {}, "dryRun": False, "heldHumanConflicts": held_rows},
        )

    stores = provenance_stores(cfg)
    glossary = load_glossary(cfg.glossary_path)
    touched: set[str] = set()

    renamed = 0
    source_keys: dict[str, set] = {}
    with project_mutation_lock(cfg):
        for g in gaps:
            assert g.target is not None
            if g.reason == "no_state":
                if g.namespace not in source_keys:
                    source_keys[g.namespace] = set(catalog.load(cfg.source_locale, g.namespace))
                old = _rename_source(stores.state, g, source_keys[g.namespace])
                if old:
                    stores.state.record(g.locale, g.namespace, g.key, old[1])
                    stores.state.drop(g.locale, g.namespace, old[0])
                    touched.add(g.locale)
                    renamed += 1
                    continue
            quality = score_translation(g.source, g.target, g.locale, glossary)
            entry = record_candidate(
                state=stores.state,
                scores=stores.scores,
                history=stores.history,
                locale=g.locale,
                namespace=g.namespace,
                key=g.key,
                source=g.source,
                previous=g.target,
                text=g.target,
                model=req.model,
                quality_score=quality.score,
                quality_signals=quality.signals,
                trigger="adopt-catalogue",
                status="agent",
                provider=req.provider,
                dimensions=quality.dimensions,
                scorer=quality.scorer,
            )
            who = (req.verified_by or "").strip()
            if who:
                entry["verified_at"] = now_iso()
                entry["verified_by"] = who
                stores.state.record(g.locale, g.namespace, g.key, entry)
            touched.add(g.locale)

        for locale in sorted(touched):
            stores.state.save(locale)
            stores.scores.save(locale)

    return OpResult(
        ok=True,
        exit_code=0,
        command="adopt",
        summary=f"adopted {len(gaps)} key(s)",
        lines=lines,
        data={
            "adopted": len(gaps),
            "renamed": renamed,
            "heldHumanConflicts": held_rows,
            "byLocale": dict(by_locale),
            "dryRun": False,
            "provider": req.provider,
            "model": req.model,
        },
    )
