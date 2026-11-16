"""Shared verify helper — stamps verified_by without rewriting provider (ADR-19)."""

from __future__ import annotations

from ..catalog import build_catalog
from ..catalog.history import HistoryStore, make_history_event
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import StateStore, now_iso
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["verify_translation", "op_verify"]


def verify_translation(
    cfg: ProjectConfig,
    *,
    locale: str,
    namespace: str,
    key: str,
    verified_by: str = "web",
    verify: bool = True,
    dry_run: bool = False,
    edited_by: str | None = None,
    edited_by_name: str | None = None,
) -> dict:
    """Stamp or clear verification. Leaves ``provider`` on the state entry."""
    if not locale or not key:
        return {"ok": False, "error": "locale and key are required"}
    who = (verified_by or "web").strip() or "web"
    store = StateStore(cfg.state_root())
    entry = dict(store.entry(locale, namespace, key) or {})
    if not entry and verify:
        return {"ok": False, "error": "no state entry to verify"}
    provider_before = entry.get("provider")
    if verify:
        entry["verified_at"] = now_iso()
        entry["verified_by"] = who
        trigger = "workflow-verify" if who == "workflow" else "web-verify"
    else:
        entry.pop("verified_at", None)
        entry.pop("verified_by", None)
        trigger = "web-unverify"
    if dry_run:
        return {
            "ok": True,
            "verified": verify,
            "verified_by": who if verify else None,
            "provider": provider_before,
            "dry_run": True,
        }
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    with project_mutation_lock(cfg):
        store.record(locale, namespace, key, entry)
        store.save(locale)
        current = catalog.load(locale, namespace).get(key)
        HistoryStore(cfg.history_root()).append(
            locale,
            make_history_event(
                namespace=namespace,
                key=key,
                prev=current,
                next_text=current or "",
                model=entry.get("model", "human"),
                status=entry.get("status", "human"),
                src_sha=entry.get("src_sha", ""),
                trigger=trigger,
                quality_score=None,
                provider=entry.get("provider"),
                edited_by=edited_by,
                edited_by_name=edited_by_name,
            ),
        )
    return {
        "ok": True,
        "verified": verify,
        "verified_by": who if verify else None,
        "provider": entry.get("provider"),
        "verifiedAt": entry.get("verified_at"),
    }


def op_verify(
    cfg: ProjectConfig,
    *,
    locale: str,
    namespace: str,
    key: str,
    verified_by: str = "web",
    verify: bool = True,
    dry_run: bool = False,
) -> OpResult:
    result = verify_translation(
        cfg,
        locale=locale,
        namespace=namespace,
        key=key,
        verified_by=verified_by,
        verify=verify,
        dry_run=dry_run,
    )
    return OpResult(
        ok=bool(result.get("ok")),
        exit_code=0 if result.get("ok") else 1,
        command="verify",
        summary=result.get("error") or ("verified" if verify else "unverified"),
        data=result,
    )
