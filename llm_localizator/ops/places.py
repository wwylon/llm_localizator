"""``places`` — list and set per-place translation policy (ADR-104).

``set`` edits the toml in place with tomlkit, keeping comments.
"""

from __future__ import annotations

import tomlkit

from ..catalog import build_catalog
from ..catalog.io import atomic_write_text
from ..projects import ProjectConfig
from ..projects.config import PLACE_POLICIES
from .types import OpResult

__all__ = ["op_places"]


def _rows(cfg: ProjectConfig, catalog=None) -> list[dict]:
    cat = catalog or build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    rows = []
    for ns in cfg.namespaces_for(cat):
        keys = len(cat.load(cfg.source_locale, ns))
        rows.append({"place": ns, "keys": keys, "policy": cfg.place_policy(ns),
                     "explicit": any(p.partition(":")[0].strip("/") == ns for p in cfg.places)})
    return rows


def op_places(
    cfg: ProjectConfig,
    action: str = "list",
    place: str = "",
    policy: str = "",
    *,
    catalog=None,
) -> OpResult:
    if action == "list":
        rows = _rows(cfg, catalog=catalog)
        return OpResult(ok=True, exit_code=0, command="places", summary=f"{len(rows)} place(s)",
                        lines=[f"{r['place']:<28} {r['policy']:<8} {r['keys']} keys" for r in rows],
                        data={"places": rows, "default": cfg.places_default,
                              "patterns": dict(cfg.places)})
    if action not in ("set", "unset") or not place.strip():
        return OpResult(ok=False, exit_code=64, command="places",
                        summary="usage: places list | set PLACE POLICY | unset PLACE")
    if action == "set" and policy not in PLACE_POLICIES:
        return OpResult(ok=False, exit_code=64, command="places",
                        summary=f"policy must be one of {', '.join(PLACE_POLICIES)}")
    if cfg.config_path is None:
        return OpResult(ok=False, exit_code=1, command="places", summary="no config path")
    doc = tomlkit.parse(cfg.config_path.read_text(encoding="utf-8"))
    table = doc.get("places")
    if action == "set":
        if table is None:
            table = tomlkit.table()
            doc["places"] = table
        sub = tomlkit.table()
        sub["policy"] = policy
        table[place] = sub
        summary = f"{place} -> {policy}"
    else:
        if table is None or place not in table:
            return OpResult(ok=False, exit_code=1, command="places", summary=f"no explicit policy for {place!r}")
        del table[place]
        summary = f"{place} policy removed"
    atomic_write_text(cfg.config_path, tomlkit.dumps(doc))
    return OpResult(ok=True, exit_code=0, command="places", summary=summary)
