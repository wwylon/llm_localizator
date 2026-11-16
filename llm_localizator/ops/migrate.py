"""Migrate-state operation."""

from __future__ import annotations

from ..catalog import StateStore, state_key, catalog_for
from ..catalog.provenance import provider_of
from ..core.hash import SIGNATURE_VERSION, structure_signature
from ..projects import ProjectConfig
from .types import MigrateRequest, OpResult


def op_migrate(cfg: ProjectConfig, req: MigrateRequest) -> OpResult:
    if not cfg.state_dir:
        return OpResult(
            ok=False,
            exit_code=64,
            command="migrate-state",
            summary="no [state] dir configured",
            lines=[],
        )

    catalog = catalog_for(cfg)
    store = StateStore(cfg.state_dir)
    namespaces = cfg.namespaces_for(catalog)
    locales = req.locales or cfg.targets

    total_changed = 0
    total_seen = 0
    total_orphan = 0
    total_stamped = 0
    lines: list[str] = []
    per_locale: list[dict] = []

    for locale in locales:
        state = store.load(locale)
        if not state:
            continue

        changed = 0
        stamped = 0
        for ns in namespaces:
            source = catalog.load(cfg.source_locale, ns)
            for key, value in source.items():
                entry = state.get(state_key(ns, key))
                if entry is None:
                    continue
                total_seen += 1
                fresh = structure_signature(value)
                if entry.get("structure_sig") != fresh:
                    if not req.dry_run:
                        entry["structure_sig"] = fresh
                    changed += 1

        if req.stamp_provider:
            for entry in state.values():
                if not isinstance(entry, dict) or "provider" in entry:
                    continue
                if not req.dry_run:
                    entry["provider"] = provider_of(entry)
                stamped += 1

        known = {
            state_key(ns, k)
            for ns in namespaces
            for k in catalog.load(cfg.source_locale, ns)
        }
        orphaned = len(set(state) - known)
        total_changed += changed
        total_stamped += stamped
        total_orphan += orphaned
        note = f", {orphaned} orphaned" if orphaned else ""
        stamp_note = f", {stamped} provider stamps" if req.stamp_provider else ""
        lines.append(f"  {locale:<8} {changed:>6} rewritten{stamp_note}{note}")
        per_locale.append({
            "locale": locale, "rewritten": changed, "orphaned": orphaned,
            "providerStamped": stamped,
        })

        if (changed or stamped) and not req.dry_run:
            store.save(locale)

    verb = "would rewrite" if req.dry_run else "rewrote"
    lines.append(
        f"\nsignature version {SIGNATURE_VERSION}: {verb} {total_changed} of "
        f"{total_seen} entries across {len(locales)} locale(s)."
    )
    if req.stamp_provider:
        stamp_verb = "would stamp" if req.dry_run else "stamped"
        lines.append(
            f"provider: {stamp_verb} {total_stamped} entr"
            f"{'y' if total_stamped == 1 else 'ies'} missing provider."
        )
    if total_orphan:
        lines.append(
            f"{total_orphan} entry(ies) reference keys absent from the source "
            f"locale and were left untouched."
        )
    if req.dry_run:
        lines.append("Dry run — nothing written.")

    return OpResult(
        ok=True,
        exit_code=0,
        command="migrate-state",
        summary=f"{verb} {total_changed} of {total_seen} entries",
        lines=lines,
        data={
            "signatureVersion": SIGNATURE_VERSION,
            "changed": total_changed,
            "seen": total_seen,
            "orphaned": total_orphan,
            "providerStamped": total_stamped,
            "dryRun": req.dry_run,
            "locales": per_locale,
        },
    )
