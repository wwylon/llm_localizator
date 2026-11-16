"""Go ``templ`` components (``*.templ``).

A ``.templ`` file is Go code with HTML-like component bodies::

    templ Dashboard(items []Item) {
        <h1>Proxy dashboard</h1>
        if len(items) == 0 { <p>Nothing yet</p> }
        <p>Health: { item.Health }</p>
    }

Only the component bodies are markup. Everything else (package, imports, helper funcs, ``css`` and ``script``
blocks) is blanked, control-flow lines (``if``/``for``/``switch``/``}``), component calls (``@Footer()``) and
Go expressions in braces are neutralised, and what is left goes to the HTML rules (see ``sfc.scan_markup_view``).
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ScanResult, relative_posix
from .sfc import blank_markup_comments
from .views import MarkupView, blank, scan_markup_view

__all__ = ["templ_markup", "scan_templ_file"]

_HEADER = re.compile(r"(?m)^[ \t]*templ[ \t]+\w+[ \t]*\(")
_CONTROL = re.compile(
    # Possessive ``*+``: adjacent whitespace runs must not trade spaces (a blank line was O(n^3), M2).
    r"(?m)^[ \t]*+(?:\}[ \t]*+)?(?:else[ \t]*+(?:if\b[^\n]*)?|if\b[^\n]*|for\b[^\n]*|switch\b[^\n]*|case\b[^\n]*|default\b[^\n]*)?"
    r"[ \t]*+\{?[ \t]*+$"
)
_CALL_LINE = re.compile(r"(?m)^[ \t]*@[^\n]*$")
_EXPR = re.compile(r"\{[^{}\n]*\}")


def _matching_brace(text: str, open_at: int) -> int:
    """Index of the ``}`` closing the ``{`` at *open_at*, skipping quoted strings; len(text) if unbalanced."""
    depth, i, n = 0, open_at, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" and c != "`" else 1
            i = j
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def templ_markup(text: str) -> str:
    """Markup view of a ``.templ`` file: same line numbers, component bodies only, Go neutralised."""
    out = [c if c == "\n" else " " for c in text]
    for header in _HEADER.finditer(text):
        paren = text.find("(", header.start())
        depth, i = 0, paren
        while i < len(text):  # end of the parameter list
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        brace = text.find("{", i)
        if brace < 0:
            continue
        end = _matching_brace(text, brace)
        out[brace + 1:end] = list(text[brace + 1:end])
    markup = blank_markup_comments("".join(out))
    markup = _CALL_LINE.sub(lambda m: blank(m.group()), markup)
    lines = markup.split("\n")
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and "<" not in stripped and _CONTROL.fullmatch(line):
            lines[idx] = blank(line)  # ``if x {``, ``} else {``, ``}``, ``for … {``
    markup = "\n".join(lines)
    return MarkupView.slot_text(_EXPR, markup)


def scan_templ_file(raw_scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    rel = relative_posix(path, raw_scanner.root)
    scan_markup_view(raw_scanner, rel, templ_markup("\n".join(lines)), result)
