"""Push source strings into the consumer catalogue (H.1 / ADR-40)."""

from __future__ import annotations

from ..catalog import build_catalog, needs_translation, state_key
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import StateStore
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["PushStringsRequest", "op_push_strings"]


class PushStringsRequest:
    __slots__ = ("namespace", "strings", "dry_run")

    def __init__(
        self,
        *,
        namespace: str,
        strings: dict[str, str],
        dry_run: bool = False,
    ) -> None:
        self.namespace = namespace
        self.strings = strings
        self.dry_run = dry_run


def op_push_strings(cfg: ProjectConfig, req: PushStringsRequest) -> OpResult:
    """Add or update source keys. Does not call a model (ADR-40)."""
    namespace = (req.namespace or "").strip()
    if not namespace:
        return OpResult(
            ok=False, exit_code=64, command="push-strings",
            summary="namespace is required",
        )
    if not isinstance(req.strings, dict):
        return OpResult(
            ok=False, exit_code=64, command="push-strings",
            summary="strings must be an object",
        )

    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    source = dict(catalog.load(cfg.source_locale, namespace))
    added = 0
    updated = 0
    skipped = 0
    changed_keys: list[str] = []
    source_changes: list[tuple[str, str, str, str]] = []

    for raw_key, raw_value in req.strings.items():
        key = str(raw_key)
        value = "" if raw_value is None else str(raw_value)
        if key not in source:
            source[key] = value
            added += 1
            changed_keys.append(key)
        elif source[key] == value:
            skipped += 1
        else:
            source_changes.append((namespace, key, str(source[key]), value))
            source[key] = value
            updated += 1
            changed_keys.append(key)

    stale_marked = 0
    if changed_keys:
        state = StateStore(cfg.state_root())
        for locale in cfg.targets:
            target = catalog.load(locale, namespace)
            locale_state = state.load(locale)
            for key in changed_keys:
                src = source[key]
                entry = locale_state.get(state_key(namespace, key))
                # Count as stale if a target value exists (or state) and would need work.
                if key in target or entry is not None:
                    if needs_translation(src, entry):
                        stale_marked += 1

    if req.dry_run or not changed_keys:
        return OpResult(
            ok=True,
            exit_code=0,
            command="push-strings",
            summary=(
                f"push-strings: added={added} updated={updated} "
                f"skipped={skipped} stale_marked={stale_marked}"
                + (" (dry-run)" if req.dry_run else "")
            ),
            data={
                "ok": True,
                "added": added,
                "updated": updated,
                "skipped": skipped,
                "stale_marked": stale_marked,
                "dry_run": bool(req.dry_run),
                "written": False,
            },
        )

    with project_mutation_lock(cfg):
        catalog.save(cfg.source_locale, namespace, source)
    if source_changes:
        from ..catalog.source_history import SourceHistory

        with project_mutation_lock(cfg):
            SourceHistory(cfg.state_root()).record_changes(source_changes)

    return OpResult(
        ok=True,
        exit_code=0,
        command="push-strings",
        summary=(
            f"push-strings: added={added} updated={updated} "
            f"skipped={skipped} stale_marked={stale_marked}"
        ),
        data={
            "ok": True,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "stale_marked": stale_marked,
            "dry_run": False,
            "written": True,
        },
    )
