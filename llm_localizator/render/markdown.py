"""Markdown preview. HTML in the source is escaped, never passed through."""

from __future__ import annotations

import html
import re

__all__ = ["preview_markdown"]

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")


def preview_markdown(text: str, locale: str = "") -> str:
    """Return HTML for *text*. *locale* is unused; renderers share one signature."""
    del locale
    lines: list[str] = []
    for raw in text.splitlines():
        line = html.escape(raw)
        if line.startswith("# "):
            lines.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            lines.append(f"<h3>{_inline(line[4:])}</h3>")
        elif not line.strip():
            continue
        else:
            lines.append(f"<p>{_inline(line)}</p>")
    return "\n".join(lines)


def _inline(line: str) -> str:
    # Bold first so ** inside backticks is not bolded after code extraction.
    line = _BOLD.sub(r"<strong>\1</strong>", line)
    return _CODE.sub(r"<code>\1</code>", line)
