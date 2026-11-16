"""Path containment helpers for project-scoped filesystem access."""

from __future__ import annotations

from pathlib import Path

__all__ = ["is_under_root", "project_path"]


def project_path(root: Path, raw: str | Path | None) -> Path | None:
    """A path from a request or a CLI flag: absolute as given, relative to the project root otherwise.

    The web server's working directory is not the project, and the dispatcher's containment check
    (``ops.dispatch_util._escaping_path``) judges relative paths against the root, so ops resolve them the same way.
    """
    if raw in (None, ""):
        return None
    path = Path(str(raw)).expanduser()
    return path if path.is_absolute() else Path(root) / path


def is_under_root(path: Path, root: Path) -> bool:
    """Return True when *path* resolves inside *root* (not a sibling prefix)."""
    resolved = Path(path).resolve()
    base = Path(root).resolve()
    return resolved.is_relative_to(base)
