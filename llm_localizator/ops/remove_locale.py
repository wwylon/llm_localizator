"""Remove a target locale from the project TOML. Shared by CLI and web (ADR-14)."""

from __future__ import annotations

import tomlkit

from ..catalog.base import Catalog
from ..catalog.io import atomic_write_text
from ..projects.config import ProjectConfig

__all__ = ["remove_locale"]


def remove_locale(cfg: ProjectConfig, locale: str) -> dict:
    """Drop ``locale`` from targets and related maps. Does not delete catalogue files."""
    if locale not in cfg.targets:
        return {"ok": False, "error": f"{locale!r} is not a target locale"}
    try:
        Catalog._validate_component(locale, "locale")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if len(cfg.targets) <= 1:
        return {"ok": False, "error": "cannot remove the last target locale"}

    config_path = cfg.config_path
    if config_path is None:
        return {"ok": False, "error": "no config path"}
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    locales = doc.get("locales")
    if not isinstance(locales, dict):
        return {"ok": False, "error": "[locales] table is missing"}

    targets = locales.get("targets")
    if targets is not None:
        locales["targets"] = tomlkit.array([t for t in list(targets) if t != locale])

    for key in ("frozen", "asap"):
        arr = locales.get(key)
        if arr is not None:
            locales[key] = tomlkit.array([t for t in list(arr) if t != locale])

    for map_key in ("models", "providers", "pivots", "fallbacks", "roles", "prompt_family"):
        table = locales.get(map_key)
        if isinstance(table, dict) and locale in table:
            del table[locale]

    # Drop pivots/fallbacks that pointed at the removed locale.
    for map_key in ("pivots", "fallbacks"):
        table = locales.get(map_key)
        if not isinstance(table, dict):
            continue
        for key in list(table):
            if str(table[key]) == locale:
                del table[key]

    atomic_write_text(config_path, tomlkit.dumps(doc))
    return {"ok": True}
