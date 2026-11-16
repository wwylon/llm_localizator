"""``org``: whether this project uses the organisation-level TM and glossary (C-036, ADR-99)."""

from __future__ import annotations

from pathlib import Path

from ..projects import ProjectConfig
from ..projects.registry import org_paths
from .types import OpResult

__all__ = ["op_org"]


def _count(path: Path) -> int:
    if path.is_dir():
        return sum(1 for p in path.rglob("*") if p.is_file())
    return 1 if path.is_file() else 0


def op_org(cfg: ProjectConfig) -> OpResult:
    """Read-only status: flags from ``[org]``, shared paths from the registry, file counts."""
    paths = org_paths()
    data = {
        "use": cfg.org_use,
        "contribute": cfg.org_contribute,
        "tm": {"path": str(paths["tm"]), "files": _count(paths["tm"])},
        "glossary": {"path": str(paths["glossary"]), "files": _count(paths["glossary"])},
    }
    lines = [
        f"use: {'yes' if cfg.org_use else 'no'}   contribute: {'yes' if cfg.org_contribute else 'no'}",
        f"tm: {data['tm']['path']} ({data['tm']['files']} files)",
        f"glossary: {data['glossary']['path']} ({data['glossary']['files']} files)",
    ]
    if not cfg.org_use:
        lines.append('off: add [org] use = true to read these (contribute = true also writes approved text)')
    return OpResult(
        ok=True, exit_code=0, command="org",
        summary="organisation sharing is on" if cfg.org_use else "organisation sharing is off",
        lines=lines, data=data,
    )
