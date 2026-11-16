"""Scan catalogue vs state for adopt / agent-backlog (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from ..core.hash import src_hash
from ..catalog import StateStore, build_catalog, needs_translation
from ..projects import ProjectConfig

__all__ = [
    "GAP_REASONS",
    "CatalogueGap",
    "iter_catalogue_gaps",
    "resolve_gap_locales",
]

GAP_REASONS = frozenset({"missing", "empty", "no_state", "stale", "external_edit"})


@dataclass(frozen=True)
class CatalogueGap:
    locale: str
    namespace: str
    key: str
    reason: str
    source: str
    target: str | None


def _edited_outside(entry: dict, text: str) -> bool:
    recorded = entry.get("tgt_sha")
    return isinstance(recorded, str) and recorded != src_hash(text.strip())


def resolve_gap_locales(cfg: ProjectConfig, locales: list[str] | None) -> list[str]:
    """All configured targets when unset (includes frozen — status-like)."""
    if locales is not None:
        return list(locales)
    return list(cfg.targets)


def iter_catalogue_gaps(
    cfg: ProjectConfig,
    *,
    locales: list[str] | None = None,
    namespaces: list[str] | None = None,
    reasons: Iterable[str] | None = None,
    limit: int | None = None,
    catalog=None,
    state: StateStore | None = None,
) -> Iterator[CatalogueGap]:
    """Yield gaps in locale → namespace → key order.

    Reasons:
    - ``missing`` — key absent from target catalogue
    - ``empty`` — key present but blank/whitespace
    - ``no_state`` — non-empty target value, no state entry
    - ``stale`` — state present but ``src_sha`` ≠ current English
    - ``external_edit`` — state present and current, but the target text no
      longer matches the hash recorded when the engine wrote it (hand/agent edit)
    """
    wanted = set(reasons) if reasons is not None else set(GAP_REASONS)
    unknown = wanted - GAP_REASONS
    if unknown:
        raise ValueError(f"unknown gap reason(s): {sorted(unknown)}")

    if catalog is None:
        catalog = build_catalog(
            cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
        )
    if state is None and cfg.state_dir:
        state = StateStore(cfg.state_dir)

    ns_list = namespaces if namespaces is not None else cfg.namespaces_for(catalog)
    emitted = 0

    for locale in resolve_gap_locales(cfg, locales):
        for ns in ns_list:
            source = catalog.load(cfg.source_locale, ns)
            if not source:
                continue
            target = catalog.load(locale, ns)
            for key, src in source.items():
                if cfg.is_skipped(ns, key, src):
                    continue
                if not isinstance(src, str):
                    continue

                reason: str | None = None
                tgt_val: str | None = None
                if key not in target:
                    reason = "missing"
                else:
                    raw = target[key]
                    text = raw if isinstance(raw, str) else str(raw)
                    tgt_val = text
                    if not text.strip():
                        reason = "empty"
                    else:
                        entry = state.entry(locale, ns, key) if state else None
                        if entry is None:
                            reason = "no_state"
                        elif needs_translation(src, entry):
                            reason = "stale"
                        elif _edited_outside(entry, text):
                            reason = "external_edit"

                if reason is None or reason not in wanted:
                    continue
                yield CatalogueGap(
                    locale=locale,
                    namespace=ns,
                    key=key,
                    reason=reason,
                    source=src,
                    target=tgt_val,
                )
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
