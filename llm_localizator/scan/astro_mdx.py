"""Astro components (``.astro``) and MDX pages (``.mdx``) (plan B2).

* **Astro**: a TypeScript frontmatter between ``---`` fences and a JSX-like body. The fences, ``<style>`` blocks and
  HTML comments are blanked; the rest goes through the JSX scanner as one view with the same line numbers, so frontmatter
  literals get the TS context rules and body text gets the JSX text rules.
* **MDX**: Markdown with JSX. Following MDX's own rule, a line that opens with a tag starts a JSX block that runs until
  the next blank line; those blocks and the ``import``/``export`` lines go to the JSX scanner, every other line is
  Markdown content (headings, paragraphs, list items, front-matter text keys).
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ScanResult, relative_posix
from .views import blank

__all__ = ["astro_view", "mdx_views", "scan_astro_file", "scan_mdx_file"]

_STYLE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_JSX_START = re.compile(r"^\s*<(?!!--)[A-Za-z/>]")
_ESM = re.compile(r"^\s*(?:import|export)\b")


def astro_view(text: str) -> str:
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        lines[0] = ""
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines[i] = ""
                break
    view = "\n".join(lines)
    view = _STYLE.sub(lambda m: blank(m.group()), view)
    return _COMMENT.sub(lambda m: blank(m.group()), view)


_STRINGS = re.compile(r""""(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\\n]|\\.)*`""")


def _bracket_balance(line: str) -> int:
    code = _STRINGS.sub("", line)
    return sum(code.count(c) for c in "({[") - sum(code.count(c) for c in ")}]")


def mdx_views(text: str) -> tuple[list[str], list[str]]:
    """``(markdown lines, jsx lines)``, both as long as the file; a line is in exactly one of them."""
    lines = text.split("\n")
    md = list(lines)
    jsx = [""] * len(lines)
    in_jsx = in_fence = False
    esm_depth = 0   # open brackets of a multi-line ``export const meta = {`` / ``import {`` (M2)
    in_front = bool(lines) and lines[0].strip() == "---"
    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_front:
            if i > 0 and stripped == "---":
                in_front = False
            continue  # front matter stays in the Markdown view (its text keys are read there)
        if esm_depth > 0:
            jsx[i], md[i] = line, ""
            esm_depth += _bracket_balance(line)
            continue
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if in_jsx and not stripped:
            in_jsx = False
        if not in_jsx and (_JSX_START.match(line) or _ESM.match(line)):
            in_jsx = not _ESM.match(line)
            if _ESM.match(line):
                esm_depth = max(0, _bracket_balance(line))
            jsx[i], md[i] = line, ""
            continue
        if in_jsx:
            jsx[i], md[i] = line, ""
    return md, jsx


def scan_astro_file(scanner, jsx_scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    jsx_scanner.scan_file(path, astro_view("\n".join(lines)).split("\n"), result)


def scan_mdx_file(scanner, jsx_scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    from .content import _scan_markdown

    md, jsx = mdx_views("\n".join(lines))
    _scan_markdown(relative_posix(path, scanner.root), md, result)
    if any(line.strip() for line in jsx):
        jsx_scanner.scan_file(path, jsx, result)
