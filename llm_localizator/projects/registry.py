"""The optional project registry.

A name-to-location index at ``~/.llm_localize/projects.yaml``, mirroring
taskqueue's ``~/.taskqueue/projects.yaml`` so there is one mental model rather
than two. It holds **no configuration** -- only where each project's own config
lives (ADR-3).

Everything here degrades to "no projects registered" rather than raising, so a
machine with no registry is a fully supported state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..catalog.io import atomic_write_text
from .config import CONFIG_FILENAME, ConfigError

__all__ = ["RegistryEntry", "registry_home", "registry_path", "load_registry",
           "register_project", "resolve_project", "org_paths",
           "list_projects", "unregister_project", "rename_project", "prune_projects"]


@dataclass(frozen=True)
class RegistryEntry:
    name: str
    root: Path
    config: str = CONFIG_FILENAME

    @property
    def config_path(self) -> Path:
        return self.root / self.config


def registry_home() -> Path:
    """Registry directory; overridable with ``LLM_LOCALIZE_HOME`` for tests."""
    env = os.environ.get("LLM_LOCALIZE_HOME")
    return Path(env) if env else (Path.home() / ".llm_localize")


def registry_path() -> Path:
    return registry_home() / "projects.yaml"


def load_registry() -> dict[str, RegistryEntry]:
    path = registry_path()
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    out: dict[str, RegistryEntry] = {}
    for name, data in (raw.get("projects") or {}).items():
        if not isinstance(data, dict) or not data.get("root"):
            continue
        out[name] = RegistryEntry(
            name=name,
            root=Path(data["root"]),
            config=data.get("config", CONFIG_FILENAME),
        )
    return out


def register_project(
    name: str, root: Path, config: str = CONFIG_FILENAME, *, force: bool = False,
) -> Path:
    """Add or update an entry, preserving any others. Returns the registry path."""
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    projects = raw.setdefault("projects", {})
    entry: dict[str, str] = {"root": str(Path(root).resolve())}
    if not force:
        for other, e in projects.items():
            same_root = Path(e.get("root", "")).resolve() == Path(entry["root"]).resolve()
            same_cfg = e.get("config", CONFIG_FILENAME) == config
            if other == name and not (same_root and same_cfg):
                raise ConfigError(
                    f"name {name!r} is already registered for {e.get('root')}; "
                    "remove it first (projects remove) or pick another name"
                )
            if other != name and same_root and same_cfg:
                raise ConfigError(
                    f"{entry['root']} is already registered as {other!r}; "
                    "rename it (projects rename) instead of adding a second name"
                )
    if config != CONFIG_FILENAME:
        entry["config"] = config
    projects[name] = entry
    atomic_write_text(path, yaml.safe_dump(raw, sort_keys=True, allow_unicode=True))
    return path


def resolve_project(name: str) -> Path:
    """Registry name to config path."""
    entries = load_registry()
    if name not in entries:
        known = ", ".join(sorted(entries)) or "none registered"
        raise ConfigError(f"project {name!r} is not registered (known: {known})")
    cfg = entries[name].config_path
    if not cfg.exists():
        raise ConfigError(
            f"project {name!r} is registered at {entries[name].root}, "
            f"but {cfg} does not exist"
        )
    return cfg


def org_paths() -> dict[str, Path]:
    """Organisation-level shared memory and glossary (C-036, ADR-99).

    ``org:`` in the registry file may name ``tm`` and ``glossary``; the defaults sit beside
    the registry. Nothing is created here, and a missing registry is a supported state.
    """
    home = registry_home()
    raw: object = {}
    path = registry_path()
    if path.exists():
        try:
            raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("org") or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    def pick(name: str, default: str) -> Path:
        value = raw.get(name) if isinstance(raw, dict) else None
        p = Path(str(value)) if value else home / default
        return p if p.is_absolute() else home / p

    return {"tm": pick("tm", "org/tm"), "glossary": pick("glossary", "org/glossary.yaml")}


def _read_raw() -> dict:
    path = registry_path()
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def _write_raw(raw: dict) -> None:
    atomic_write_text(registry_path(), yaml.safe_dump(raw, sort_keys=True, allow_unicode=True))


def list_projects() -> list[dict]:
    """Every registered project with whether its config file still exists."""
    return [
        {"name": e.name, "root": str(e.root), "config": e.config, "exists": e.config_path.exists()}
        for _, e in sorted(load_registry().items())
    ]


def unregister_project(name: str) -> None:
    """Drop the registry entry only; the project's config and state are never touched."""
    raw = _read_raw()
    projects = raw.get("projects") or {}
    if name not in projects:
        raise ConfigError(f"project {name!r} is not registered (known: {', '.join(sorted(projects)) or 'none'})")
    del projects[name]
    _write_raw(raw)


def rename_project(old: str, new: str) -> None:
    raw = _read_raw()
    projects = raw.get("projects") or {}
    if old not in projects:
        raise ConfigError(f"project {old!r} is not registered")
    if new in projects:
        raise ConfigError(f"project name {new!r} is already registered at {projects[new].get('root')}")
    projects[new] = projects.pop(old)
    _write_raw(raw)


def prune_projects() -> list[str]:
    """Unregister entries whose config file is gone. Returns the removed names."""
    gone = [p["name"] for p in list_projects() if not p["exists"]]
    if gone:
        raw = _read_raw()
        for name in gone:
            raw["projects"].pop(name, None)
        _write_raw(raw)
    return gone
