"""Store listing text (fastlane metadata) present in the source locale but missing in others (M6, B22).

App-store text (``fastlane/metadata/android/<locale>/full_description.txt``, ``changelogs/14.txt``,
``fastlane/metadata/<locale>/release_notes.txt`` for iOS) is localized per folder, outside any catalogue. A project
can translate its listing into four languages and still ship every changelog in English only: the scanner never sees
it (store text is not source code), and no catalogue check does either. This reports such gaps; it changes nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["StoreGap", "store_metadata_gaps"]

_SKIP = {".git", "node_modules", ".venv", "build", "dist", "Pods"}
_TEXT_SUFFIXES = {".txt", ".md"}


@dataclass
class StoreGap:
    folder: str                      # the metadata folder holding the locale folders, relative to the root
    source: str                      # the source-locale folder name (en-US, en, …)
    missing: dict[str, list[str]] = field(default_factory=dict)   # relative file -> locales without it
    absent_locales: list[str] = field(default_factory=list)       # expect_locales with no folder at all


def _folder_for_locale(locales: list[Path], want: str) -> Path | None:
    """Match ``pl`` / ``pl-PL`` / ``pl_PL`` against existing store locale folders."""
    norm = want.lower().replace("_", "-")
    primary = norm.split("-")[0]
    exact = [d for d in locales if d.name.lower().replace("_", "-") == norm]
    if exact:
        return exact[0]
    same = [d for d in locales if d.name.lower().replace("_", "-").split("-")[0] == primary]
    return same[0] if same else None


def _metadata_dirs(root: Path, max_depth: int = 4) -> list[Path]:
    out = []
    base_depth = len(root.parts)
    for dirpath, dirnames, _files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP]
        here = Path(dirpath)
        if len(here.parts) - base_depth > max_depth:
            dirnames[:] = []
            continue
        if here.name == "metadata" and here.parent.name == "fastlane":
            # Android keeps a platform level (metadata/android/<locale>); iOS puts locales directly under metadata.
            out.append(here)
            out.extend(d for d in here.iterdir() if d.is_dir() and d.name in ("android", "ios"))
            dirnames[:] = []
    return out


def store_metadata_gaps(
    root: Path,
    source_locale: str,
    *,
    expect_locales: list[str] | None = None,
) -> list[StoreGap]:
    from ..scan.base import _locale_like

    root = Path(root)
    primary = source_locale.lower().replace("_", "-").split("-")[0]
    gaps: list[StoreGap] = []
    for folder in _metadata_dirs(root):
        locales = [d for d in folder.iterdir() if d.is_dir() and _locale_like(d.name)]
        if len(locales) < 2 and not expect_locales:
            continue
        same = [d for d in locales if d.name.lower().replace("_", "-").split("-")[0] == primary]
        if not same:
            continue
        exact = [d for d in same if d.name.lower().replace("_", "-") == source_locale.lower().replace("_", "-")]
        source = (exact or sorted(same, key=lambda d: (d.name != f"{primary}-US", d.name)))[0]
        files = sorted(
            p.relative_to(source).as_posix() for p in source.rglob("*")
            if p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES
        )
        gap = StoreGap(folder=folder.relative_to(root).as_posix(), source=source.name)
        for rel in files:
            without = sorted(d.name for d in locales if d != source and not (d / rel).is_file())
            if without:
                gap.missing[rel] = without
        if expect_locales:
            absent = [
                loc for loc in expect_locales
                if loc.lower().replace("_", "-").split("-")[0] != primary
                and _folder_for_locale(locales, loc) is None
            ]
            gap.absent_locales = absent
        if gap.missing or gap.absent_locales:
            gaps.append(gap)
    return gaps
