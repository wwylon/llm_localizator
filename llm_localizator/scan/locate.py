"""Find the project source files, and the file and line a visible string comes from (ADR-120).

Shared by ``check-keys`` (which files to read), the QA crawl (is a leftover a
literal in the source, or server text?) and the scanner bench (turn a crawl
leftover into a ``{file, line, text}`` label). One walker and one normalisation,
so "literal" means the same thing in all three.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .base import _PRUNE_DIRS, path_is_skipped, split_lines

__all__ = ["SOURCE_SUFFIXES", "source_files", "normalize_text", "LiteralIndex", "Located"]

SOURCE_SUFFIXES = (
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".html", ".htm", ".py", ".jinja", ".jinja2", ".j2", ".hbs", ".ejs",
)


def source_files(cfg, suffixes: tuple[str, ...] = SOURCE_SUFFIXES, *, server: bool = False):
    """Files under ``[scan] src_dirs`` with these suffixes, minus skipped dirs and bundles.

    ``server=True`` adds the ``.py`` files under ``[scan] server_dirs`` (B3, ADR-134).
    """
    root = Path(cfg.root)
    exclude = tuple(getattr(cfg, "scan_exclude", []) or [])
    unskip = tuple(getattr(cfg, "scan_unskip", []) or [])
    dirs = [(rel, suffixes) for rel in getattr(cfg, "scan_src_dirs", []) or []]
    if server:
        dirs += [(rel, (".py",)) for rel in getattr(cfg, "scan_server_dirs", []) or []]
    seen: set[Path] = set()
    for rel, suffixes in dirs:
        base = root / rel
        if base.is_file():
            yield base
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d.lower() not in _PRUNE_DIRS)
            for name in sorted(filenames):
                low = name.lower()
                if not low.endswith(suffixes) or low.endswith(".min.js"):
                    continue
                path = Path(dirpath) / name
                if path in seen or path_is_skipped(path, exclude=exclude, unskip=unskip, root=root):
                    continue
                seen.add(path)
                yield path


def normalize_text(text: str) -> str:
    """Entities decoded, whitespace collapsed, case folded: how a page and a file compare."""
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip().casefold()


@dataclass(frozen=True)
class Located:
    file: str   # posix path relative to the project root
    line: int


class LiteralIndex:
    """Normalised source text of a project, searchable for visible strings."""

    def __init__(self, cfg, *, skip=None) -> None:
        root = Path(cfg.root)
        self._files: list[tuple[str, str, list[int]]] = []
        self._raw: dict[str, list[str]] = {}
        for path in source_files(cfg, server=True):
            if skip is not None and skip(path):
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = path.as_posix()
            # Map each normalised character back to its source line.
            norm_chars: list[str] = []
            lines: list[int] = []
            line = 1
            prev_space = True
            for ch in html.unescape(raw):
                if ch == "\n":
                    line += 1
                if ch.isspace():
                    if prev_space:
                        continue
                    norm_chars.append(" ")
                    lines.append(line)
                    prev_space = True
                    continue
                folded = ch.casefold()
                norm_chars.extend(folded)
                lines.extend([line] * len(folded))
                prev_space = False
            self._files.append((rel, "".join(norm_chars), lines))
            self._raw[rel] = split_lines(raw)

    def __len__(self) -> int:
        return len(self._files)

    def _score(self, rel: str, line: int, text: str) -> float:
        """How likely this occurrence is where the visible string is written."""
        lines = self._raw.get(rel) or []
        raw = lines[line - 1] if 0 < line <= len(lines) else ""
        stripped = raw.lstrip()
        score = 0.0
        t = (text or "").strip()
        if t and any(f"{q}{t}{q}" in raw for q in ("'", '"', "`")) or f">{t}<" in raw:
            score += 3  # the whole string as one literal or one text node
        if rel.endswith((".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte")):
            score += 1
        elif rel.endswith((".js", ".mjs", ".cjs", ".ts")):
            score += 0.5
        if stripped.startswith(("//", "#", "*", "/*", "<!--")):
            score -= 3  # a comment mentions it
        if "config" in rel.rsplit("/", 1)[-1]:
            score -= 1
        return score

    def find(self, text: str) -> Located | None:
        """Where ``text`` (or, when long, its first 40 characters) is most likely written.

        Every file's first occurrence is scored: the whole string as a literal or a text
        node, markup and JS over other files, comments and config files last.
        """
        needle = normalize_text(text)
        if not needle:
            return None
        probes = [needle] + ([needle[:40]] if len(needle) > 40 else [])
        for probe in probes:
            found = []
            for rel, norm, lines in self._files:
                at = norm.find(probe)
                if at >= 0:
                    found.append(Located(rel, lines[at]))
            if found:
                return max(found, key=lambda loc: self._score(loc.file, loc.line, text))
        return None

    def is_literal(self, text: str) -> bool:
        return not normalize_text(text) or self.find(text) is not None
