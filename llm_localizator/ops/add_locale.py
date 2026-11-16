"""Add a target locale to the project TOML. Shared by CLI and web (ADR-14)."""

from __future__ import annotations

import tomlkit

from ..catalog.base import Catalog
from ..catalog.io import atomic_write_text
from ..catalog.mutation_lock import project_mutation_lock
from ..projects.config import ProjectConfig

__all__ = ["add_locale"]


def add_locale(cfg: ProjectConfig, locale: str, model: str | None = None) -> dict:
    with project_mutation_lock(cfg):
        return _add_locale(cfg, locale, model)


def _add_locale(cfg: ProjectConfig, locale: str, model: str | None = None) -> dict:
    """Append ``locale`` to ``[locales] targets``. Does not create catalogue files."""
    if locale in cfg.targets:
        return {"ok": False, "error": f"{locale!r} is already a target locale"}
    try:
        Catalog._validate_component(locale, "locale")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if model and any(ch in model for ch in "\n\"'#="):
        return {"ok": False, "error": "model must not contain newline, quotes, #, or ="}

    config_path = cfg.config_path
    if config_path is None:
        return {"ok": False, "error": "no config path"}
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    locales = doc.get("locales")
    if not isinstance(locales, dict):
        return {"ok": False, "error": "[locales] table is missing"}
    targets = locales.get("targets")
    if targets is None:
        targets = tomlkit.array()
        locales["targets"] = targets
    if locale not in list(targets):
        targets.append(locale)
    if model:
        models = locales.get("models")
        if not isinstance(models, dict):
            models = tomlkit.table()
            locales["models"] = models
        models[locale] = model
    atomic_write_text(config_path, tomlkit.dumps(doc))
    return {"ok": True}
