"""``bulk-clear``: send many keys back to the translate backlog (ADR-53).

Only the state entry is dropped, so the key reads as missing and the old text stays in the
catalogue as a fallback. Nothing is stamped human (ADR-48). Human, verified and locked keys
are never touched. Without ``--confirm`` the op only reports what it would clear.

``--invalid`` picks keys whose current text fails a hard check (a stray backslash, a foreign
script, a placeholder, HTML or literal mismatch). ``--latin-leftover`` picks non-Latin
translations that carry Latin words the source does not. For these two, a row written by an
import or an agent is eligible even though it is stamped ``human``: that status came from the
hand-off, not from a person editing in the web UI (ADR-48).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..catalog import catalog_for
from ..catalog.history import HistoryEvent
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.provenance import provider_of
from ..catalog.state import is_locked, is_verified, now_iso, parse_translated_at
from ..core.script_checks import foreign_script_hard_gate, latin_leftover_issues
from ..core.standards import get_standard
from ..core.validate import classify_failure, validate_translation
from ..pipeline.recording import provenance_stores
from ..projects import ProjectConfig
from .status import collect_missing
from .types import BulkClearRequest, OpResult

__all__ = ["op_bulk_clear"]


def _protected(entry: dict | None) -> bool:
    if not entry:
        return True
    return entry.get("status") == "human" or is_verified(entry) or is_locked(entry)


def _repairable(entry: dict | None) -> bool:
    """A row a repair may requeue: not verified or locked, and machine or hand-off made."""
    if not entry or is_verified(entry) or is_locked(entry):
        return False
    return entry.get("status") != "human" or provider_of(entry) in ("import", "agent")


def _broken_keys(cfg: ProjectConfig, catalog, locales: list[str], req: BulkClearRequest, state):
    """Yield ``(locale, ns, key, why)`` for translations that fail a hard or Latin-leftover check."""
    glossary_cache = cfg.glossary_cache()
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    for ns in cfg.namespaces_for(catalog):
        if req.namespace and ns != req.namespace:
            continue
        source = catalog.load(cfg.source_locale, ns)
        glossary = glossary_cache.get(cfg.glossary_domains_for(ns))
        for locale in locales:
            target = catalog.load(locale, ns)
            for key, src in source.items():
                text = target.get(key)
                if not isinstance(src, str) or not isinstance(text, str) or not text.strip():
                    continue
                if cfg.is_skipped(ns, key, src) or not _repairable(state.entry(locale, ns, key)):
                    continue
                if req.invalid:
                    ok, reason = validate_translation(src, text, locale, glossary, standard=standard)
                    if not ok:
                        yield locale, ns, key, classify_failure(reason)
                        continue
                    if foreign_script_hard_gate(text, locale):
                        yield locale, ns, key, "foreign-script"
                        continue
                if req.latin_leftover and latin_leftover_issues(src, text, locale):
                    yield locale, ns, key, "latin-leftover"


def op_bulk_clear(cfg: ProjectConfig, req: BulkClearRequest) -> OpResult:
    days = req.purge_machine_older_than
    if not req.stale_to_source and days is None and not req.invalid and not req.latin_leftover:
        return OpResult(ok=False, exit_code=64, command="bulk-clear",
                        summary="pass --stale-to-source, --purge-machine-older-than DAYS, "
                                "--invalid or --latin-leftover")
    catalog = catalog_for(cfg)
    stores = provenance_stores(cfg)
    locales = list(req.locales or ([req.locale] if req.locale else cfg.active_targets()))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days is not None else None
    picked: list[tuple[str, str, str, str]] = []
    if req.stale_to_source:
        for locale, items in collect_missing(cfg, catalog).items():
            if locale not in locales:
                continue
            for ns, key, reason in items:
                if reason == "stale" and (not req.namespace or ns == req.namespace):
                    picked.append((locale, ns, key, "stale"))
    if cutoff is not None:
        for locale in locales:
            for ns in cfg.namespaces_for(catalog):
                if req.namespace and ns != req.namespace:
                    continue
                for key in catalog.load(cfg.source_locale, ns):
                    entry = stores.state.entry(locale, ns, key)
                    when = parse_translated_at((entry or {}).get("translated_at"))
                    if entry and entry.get("status") == "machine" and when and when < cutoff:
                        picked.append((locale, ns, key, "old-machine"))
    repairs: set[tuple[str, str, str]] = set()
    if req.invalid or req.latin_leftover:
        for locale, ns, key, why in _broken_keys(cfg, catalog, locales, req, stores.state):
            picked.append((locale, ns, key, why))
            repairs.add((locale, ns, key))
    seen: set[tuple[str, str, str]] = set()
    todo = []
    for locale, ns, key, why in picked:
        entry = stores.state.entry(locale, ns, key)
        if (locale, ns, key) in seen:
            continue
        if _protected(entry) and not ((locale, ns, key) in repairs and _repairable(entry)):
            continue
        seen.add((locale, ns, key))
        todo.append((locale, ns, key, why))
    lines = [f"{loc}: {ns}.{key} ({why})" for loc, ns, key, why in todo[:50]]
    apply = req.confirm and not req.dry_run
    if apply and todo:
        with project_mutation_lock(cfg):
            for locale, ns, key, why in todo:
                entry = stores.state.entry(locale, ns, key) or {}
                value = catalog.load(locale, ns).get(key)
                stores.state.drop(locale, ns, key)
                stores.history.append(locale, HistoryEvent(
                    ts=now_iso(), namespace=ns, key=key, prev=value, next=value or "",
                    model=str(entry.get("model") or ""), status="missing",
                    src_sha=str(entry.get("src_sha") or ""), trigger="bulk-clear",
                ))
            stores.state.save_all(sorted({loc for loc, *_ in todo}))
    verb = "cleared" if apply else "would clear"
    tail = "" if apply or not todo else " (add --confirm to apply)"
    return OpResult(
        ok=True, exit_code=0, command="bulk-clear",
        summary=f"{verb} {len(todo)} key(s){tail}", lines=lines,
        data={"count": len(todo), "applied": apply and bool(todo),
              "keys": [{"locale": l, "namespace": n, "key": k, "why": w} for l, n, k, w in todo]},
    )
