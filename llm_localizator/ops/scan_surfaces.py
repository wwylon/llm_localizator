"""Group hardcoded-string findings by ``[scan.surfaces.<name>]`` (a part of the project).

A surface is a named set of path globs with a mode: ``fix`` (counts, fails ``--strict``),
``report`` (listed, never fails) or ``ignore`` (dropped, only counted). Findings that match no
surface belong to ``other`` and behave as ``fix``, so a project with no surfaces is unchanged.
"""

from __future__ import annotations

from fnmatch import fnmatch

OTHER = "other"


def surface_of(surfaces: dict[str, dict], file: str) -> str:
    """First surface whose glob (or directory prefix) matches ``file``; ``other`` if none."""
    rel = file.replace("\\", "/").lstrip("./")
    for name, row in surfaces.items():
        for pattern in row["paths"]:
            pat = pattern.replace("\\", "/").lstrip("./")
            if fnmatch(rel, pat) or rel.startswith(pat.rstrip("/") + "/") or rel == pat:
                return name
    return OTHER


def mode_of(surfaces: dict[str, dict], name: str) -> str:
    return surfaces[name]["mode"] if name in surfaces else "fix"


def unknown_names(surfaces: dict[str, dict], wanted: set[str]) -> list[str]:
    return sorted(n for n in wanted if n not in surfaces and n != OTHER)
