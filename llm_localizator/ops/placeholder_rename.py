"""``rename-placeholder``: rename ``{old}`` to ``{new}`` in the source and every locale (C-038).

The rewrite touches the source string and each translation that still carries ``{old}``.
Translation state keeps its provenance (status, model, verification); only the recorded
source fingerprint moves to the new source, so the rename never makes anything stale.
Translations already stale are left stale. Without ``--confirm`` the op lists the diff.
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.history import make_history_event
from ..catalog.mutation_lock import project_mutation_lock
from ..core.hash import src_hash as src_hash_of, structure_signature as structure_signature_of
from ..core.icu import extract_placeholders
from ..core.placeholders import is_placeholder_name, rename_placeholder
from ..pipeline.recording import provenance_stores
from ..projects import ProjectConfig
from .types import OpResult, PlaceholderRenameRequest

__all__ = ["op_rename_placeholder"]

_TRIGGER = "placeholder-rename"


def _fail(summary: str) -> OpResult:
    return OpResult(ok=False, exit_code=1, command="rename-placeholder", summary=summary, lines=[summary])


def _plan(cfg: ProjectConfig, catalog, req: PlaceholderRenameRequest):
    """Return ``(changes, skipped)``; changes are ``(ns, key, locale, before, after)``."""
    wanted = {k.strip() for k in (req.keys or []) if k.strip()}
    changes: list[tuple[str, str, str, str, str]] = []
    skipped: list[str] = []
    for ns in cfg.namespaces_for(catalog):
        if req.namespace and ns != req.namespace:
            continue
        source = catalog.load(cfg.source_locale, ns)
        targets = {loc: catalog.load(loc, ns) for loc in cfg.targets}
        for key, text in source.items():
            full = f"{ns}.{key}" if ns else key
            if wanted and full not in wanted:
                continue
            renamed = rename_placeholder(text, req.old, req.new)
            if renamed == text:
                continue
            if req.new in extract_placeholders(text):
                skipped.append(f"{full}: already has {{{req.new}}}")
                continue
            changes.append((ns, key, cfg.source_locale, text, renamed))
            for loc, msgs in targets.items():
                body = msgs.get(key)
                if not body:
                    continue
                after = rename_placeholder(body, req.old, req.new)
                if after != body:
                    changes.append((ns, key, loc, body, after))
    return changes, skipped


def op_rename_placeholder(cfg: ProjectConfig, req: PlaceholderRenameRequest) -> OpResult:
    if not is_placeholder_name(req.old) or not is_placeholder_name(req.new):
        return _fail("--old and --new must be placeholder names (letters, digits, underscore)")
    if req.old == req.new:
        return _fail("--old and --new are the same")
    catalog = catalog_for(cfg)
    changes, skipped = _plan(cfg, catalog, req)
    keys = sorted({(ns, key) for ns, key, _l, _b, _a in changes})
    lines = [f"{ns + '.' if ns else ''}{key} [{loc}]: {before!r} -> {after!r}"
             for ns, key, loc, before, after in changes[:200]]
    lines += [f"skipped {s}" for s in skipped]
    apply = req.confirm and not req.dry_run
    data = {
        "keys": len(keys), "edits": len(changes), "skipped": skipped, "applied": False,
        "changes": [
            {"namespace": ns, "key": key, "locale": loc, "before": b, "after": a}
            for ns, key, loc, b, a in changes[:500]
        ],
    }
    if not apply or not changes:
        return OpResult(
            ok=True, exit_code=0, command="rename-placeholder",
            summary=(f"would rename in {len(keys)} key(s), {len(changes)} edit(s)"
                     if changes else f"no key uses {{{req.old}}}"),
            lines=lines, data=data,
        )

    stores = provenance_stores(cfg)
    by_ns: dict[str, dict[str, dict[str, str]]] = {}
    for ns, key, loc, _before, after in changes:
        by_ns.setdefault(ns, {}).setdefault(loc, {})[key] = after
    touched: set[str] = set()
    pending = []
    with project_mutation_lock(cfg):
        for ns, per_locale in by_ns.items():
            source = catalog.load(cfg.source_locale, ns)
            src_updates = per_locale.get(cfg.source_locale, {})
            catalog.save(cfg.source_locale, ns, {**source, **src_updates})
            new_source = catalog.load(cfg.source_locale, ns)
            for loc, updates in per_locale.items():
                if loc == cfg.source_locale:
                    continue
                catalog.write(loc, ns, updates, source=new_source)
        for ns, key, loc, before, after in changes:
            if loc == cfg.source_locale:
                continue
            entry = stores.state.entry(loc, ns, key)
            if not entry:
                continue
            old_src = next(b for n2, k2, l2, b, _a in changes
                           if n2 == ns and k2 == key and l2 == cfg.source_locale)
            new_src = next(a for n2, k2, l2, _b, a in changes
                           if n2 == ns and k2 == key and l2 == cfg.source_locale)
            if entry.get("src_sha") == src_hash_of(old_src):
                entry["src_text"] = new_src
                entry["src_sha"] = src_hash_of(new_src)
                entry["structure_sig"] = structure_signature_of(new_src)
                stores.state.record(loc, ns, key, entry)
            pending.append((loc, make_history_event(
                namespace=ns, key=key, prev=before, next_text=after,
                model=str(entry.get("model") or ""), status=str(entry.get("status") or "machine"),
                src_sha=str(entry.get("src_sha") or ""), trigger=_TRIGGER,
                provider=entry.get("provider"), prev_src=old_src, next_src=new_src,
            )))
            touched.add(loc)
        for loc in sorted(touched):
            stores.state.save(loc)
        for loc, event in pending:
            stores.history.append(loc, event)
    data["applied"] = True
    return OpResult(
        ok=True, exit_code=0, command="rename-placeholder",
        summary=f"renamed {{{req.old}}} to {{{req.new}}} in {len(keys)} key(s), {len(changes)} edit(s)",
        lines=lines, data=data,
    )
