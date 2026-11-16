"""Project configuration, registry, and the taskqueue bridge."""

from __future__ import annotations

from pathlib import Path

from .config import (
    CONFIG_FILENAME,
    ConfigError,
    LocaleRole,
    ProjectConfig,
    ProviderConfig,
    discover_config,
    load_config,
)
from .context import (
    ContextNotes,
    GlossaryCache,
    append_example,
    effective_glossary_for,
    glossary_prompt_block,
    load_examples,
    load_glossary,
    load_glossary_bundle,
    select_glossary,
)
from .registry import (
    RegistryEntry,
    load_registry,
    register_project,
    registry_home,
    registry_path,
    resolve_project,
)

__all__ = [
    "CONFIG_FILENAME",
    "ConfigError",
    "ContextNotes",
    "GlossaryCache",
    "LocaleRole",
    "ProjectConfig",
    "ProviderConfig",
    "RegistryEntry",
    "append_example",
    "discover_config",
    "effective_glossary_for",
    "glossary_prompt_block",
    "load_config",
    "load_examples",
    "load_glossary",
    "load_glossary_bundle",
    "load_registry",
    "register_project",
    "registry_home",
    "registry_path",
    "resolve_project",
    "resolve",
    "select_glossary",
]


_CLI_BRANCH: str | None = None


def set_cli_branch(name: str | None) -> None:
    """``--branch`` for this process: state/scores come from that branch (ADR-61)."""
    global _CLI_BRANCH
    _CLI_BRANCH = name or None


def _apply_branch(cfg: ProjectConfig) -> ProjectConfig:
    if not _CLI_BRANCH:
        return cfg
    from .branches import branch_config

    overlay = branch_config(cfg, _CLI_BRANCH)
    if overlay is None:
        raise SystemExit(f"branch {_CLI_BRANCH!r} is not tracked (see the Branches page)")
    return overlay


def resolve(project: str | None = None, config: str | Path | None = None) -> ProjectConfig:
    """Resolve a project config by name, explicit path, or upward walk (ADR-3)."""
    if config is not None:
        return _apply_branch(load_config(config))
    if project:
        return _apply_branch(load_config(resolve_project(project)))
    return _apply_branch(load_config(discover_config()))
