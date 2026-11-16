"""Named source snapshots for a release, without a new state status (ADR-41)."""

from __future__ import annotations

import json
from pathlib import Path

from ..catalog import build_catalog
from ..catalog.io import atomic_write_text
from ..core.hash import src_hash
from ..projects import ProjectConfig
from .types import OpResult, parse_csv_list
from ..catalog.io import read_json

__all__ = ["op_release_freeze", "op_release_diff"]


def _dir(cfg: ProjectConfig) -> Path:
    return cfg.state_root() / "releases"


def _path(cfg: ProjectConfig, name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip())
    if not safe:
        raise ValueError("release name is required")
    return _dir(cfg) / f"{safe}.json"


def _snapshot(cfg: ProjectConfig, namespaces: list[str] | None, keys: list[str] | None) -> dict:
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    wanted_ns = set(namespaces) if namespaces else None
    wanted_keys = set(keys) if keys else None
    rows: dict[str, str] = {}
    for ns in cfg.namespaces_for(catalog):
        if wanted_ns is not None and ns not in wanted_ns:
            continue
        source = catalog.load(cfg.source_locale, ns)
        for key, value in source.items():
            if not isinstance(value, str):
                continue
            label = f"{ns}.{key}" if ns else key
            if wanted_keys is not None and label not in wanted_keys and key not in wanted_keys:
                continue
            rows[label] = src_hash(value)
    return {"source_locale": cfg.source_locale, "keys": rows}


def op_release_freeze(
    cfg: ProjectConfig,
    *,
    name: str,
    namespaces: list[str] | None = None,
    keys: list[str] | None = None,
) -> OpResult:
    snap = _snapshot(cfg, namespaces, keys)
    path = _path(cfg, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
    return OpResult(
        ok=True,
        exit_code=0,
        command="release-freeze",
        summary=f"froze {len(snap['keys'])} key(s) as {path.name}",
        data={"path": str(path), "count": len(snap["keys"])},
    )


def op_release_diff(cfg: ProjectConfig, *, name: str) -> OpResult:
    path = _path(cfg, name)
    if not path.exists():
        return OpResult(
            ok=False, exit_code=1, command="release-diff",
            summary=f"no release {name!r}",
        )
    saved = read_json(path)
    frozen = saved.get("keys") or {}
    current = _snapshot(cfg, None, None)["keys"]
    added = sorted(set(current) - set(frozen))
    removed = sorted(set(frozen) - set(current))
    changed = sorted(
        key for key in set(current) & set(frozen) if current[key] != frozen[key]
    )
    lines = (
        [f"added\t{key}" for key in added]
        + [f"removed\t{key}" for key in removed]
        + [f"changed\t{key}" for key in changed]
    )
    summary = (
        f"added {len(added)}, removed {len(removed)}, changed {len(changed)}"
    )
    return OpResult(
        ok=True, exit_code=0, command="release-diff",
        summary=summary, lines=lines,
        data={"added": added, "removed": removed, "changed": changed},
    )


def namespaces_from(value) -> list[str] | None:
    return parse_csv_list(value)
