"""Work manifest: an inspectable list of what a translate run would do.

``sync --diff`` writes it, ``translate --manifest`` reads it. It is a plain JSON
file, so a CI job can attach it to a pull request. It never touches the catalogue.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..catalog import Catalog, StateStore
from ..catalog.io import atomic_write_text
from ..catalog.state import state_key
from ..projects import ProjectConfig
from .translate import collect_work
from ..catalog.io import read_json

__all__ = ["MANIFEST_NAME", "build_manifest", "manifest_path", "only_keys_from", "write_manifest"]

MANIFEST_NAME = "work_manifest.json"


def manifest_path(cfg: ProjectConfig) -> Path:
    return cfg.state_root() / MANIFEST_NAME


def build_manifest(
    cfg: ProjectConfig,
    catalog: Catalog,
    state: StateStore,
    *,
    locales: list[str],
    namespaces: list[str],
    work: list | None = None,
) -> dict:
    """Added, changed and removed keys, each with the locales that need work.

    ``work`` is the ``collect_work(force=False)`` list for the same scope when the
    caller already has it (sync), so the catalogue is scanned once.
    """
    if work is None:
        work = collect_work(cfg, catalog, state, locales=locales, namespaces=namespaces, force=False)
    added: dict[tuple[str, str], dict] = {}
    changed: dict[tuple[str, str], dict] = {}
    for item in work:
        entry = state.entry(item.locale, item.namespace, item.key) or {}
        ident = (item.namespace, item.key)
        if item.status == "stale":
            row = changed.setdefault(ident, {
                "namespace": item.namespace, "key": item.key,
                "old": entry.get("src_text") or "", "new": item.source, "locales": [],
            })
        else:
            row = added.setdefault(ident, {
                "namespace": item.namespace, "key": item.key,
                "source": item.source, "locales": [],
            })
        row["locales"].append(item.locale)

    removed: dict[tuple[str, str], dict] = {}
    total = 0
    for ns in namespaces:
        source = catalog.load(cfg.source_locale, ns)
        total += len(source)
        for locale in locales:
            for key in catalog.load(locale, ns):
                if key not in source and not cfg.is_skipped(ns, key):
                    removed.setdefault((ns, key), {"namespace": ns, "key": key})
    touched = len({*added, *changed})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "locales": list(locales),
        "added": sorted(added.values(), key=lambda r: (r["namespace"], r["key"])),
        "changed": sorted(changed.values(), key=lambda r: (r["namespace"], r["key"])),
        "removed": sorted(removed.values(), key=lambda r: (r["namespace"], r["key"])),
        "unchanged_count": max(0, total - touched),
    }


def write_manifest(cfg: ProjectConfig, manifest: dict, path: Path | None = None) -> Path:
    target = path or manifest_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return target


def only_keys_from(path: Path) -> dict[str, set[str]]:
    """The ``only_keys`` selector ``collect_work`` understands, from a manifest file."""
    data = read_json(path)
    out: dict[str, set[str]] = {}
    for section in ("added", "changed"):
        for row in data.get(section, []):
            for locale in row.get("locales", []):
                out.setdefault(locale, set()).add(state_key(row["namespace"], row["key"]))
    return out
