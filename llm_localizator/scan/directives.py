"""In-code scan control comments (ADR-106).

Read-only: the engine never writes these. A directive is a token inside any
comment (``//``, ``#``, ``/* */``, ``<!-- -->``, ``{/* */}``):

    l10n-ignore              same line
    l10n-ignore-next-line    the following line
    l10n-ignore-start / -end block
    l10n-ignore-file         whole file (first 10 lines)
    l10n: key=a.b note="Pay button" max-length=20 dnt namespace=checkout
                             hints for the hit on this or the next line;
                             ``namespace=`` on a line of its own covers the file

Aliases (``i18n-ignore``, ``i18next/no-literal-string`` disables, ``noqa: i18n``)
are treated as ``l10n-ignore`` / ``l10n-ignore-next-line`` unless disabled with
``[scan] directive_aliases = false``.
"""

from __future__ import annotations

import dataclasses
import re
import shlex

__all__ = ["filter_hits", "annotate_hits", "apply_directives", "lint_directives"]

_COMMENT = re.compile(r"(//|#|/\*|<!--|\{/\*)")
_NATIVE = re.compile(r"(?:l10n|llm-localizator)[:\- ]?ignore(-next-line|-start|-end|-file)?\b")
_ALIAS = re.compile(
    r"eslint-disable-next-line\s+i18next/no-literal-string"
    r"|eslint-disable-line\s+i18next/no-literal-string"
    r"|\bi18n-ignore\b|noqa:\s*i18n"
)
_ATTR = re.compile(r"(?:l10n|llm-localizator):\s+(?!ignore)(.*?)(?:\*/\}?|-->|\}|$)")
_ATTR_NAMES = {"key", "note", "max-length", "dnt", "namespace", "reason", "user-facing"}
_FILE_HEAD = 10


def _kind(text: str, suffix: str | None) -> str:
    if text.startswith("eslint-disable-next-line"):
        return "next"
    if text.startswith(("eslint-disable-line", "i18n-ignore", "noqa")):
        return "line"
    return {None: "line", "-next-line": "next", "-start": "start", "-end": "end",
            "-file": "file"}[suffix]


def _directives(lines: list[str], aliases: bool = True) -> list[tuple[int, str]]:
    """(1-based line, kind) for every ignore directive found inside a comment."""
    found: list[tuple[int, str]] = []
    for n, line in enumerate(lines, 1):
        if "ignore" not in line and "eslint-disable" not in line and "noqa" not in line:
            continue
        c = _COMMENT.search(line)
        if not c:
            continue
        m = _NATIVE.search(line, c.start())
        if m:
            found.append((n, _kind(m.group(0), m.group(1))))
            continue
        if aliases:
            m = _ALIAS.search(line, c.start())
            if m:
                found.append((n, _kind(m.group(0), None)))
    return found


def filter_hits(lines: list[str], hits: list, aliases: bool = True) -> tuple[list, int]:
    """Drop hits covered by a directive. Returns (kept, suppressed count)."""
    marks = _directives(lines, aliases)
    if not marks:
        return hits, 0
    if any(k == "file" and n <= _FILE_HEAD for n, k in marks):
        return [], len(hits)
    off: set[int] = set()
    start = None
    for n, kind in marks:
        if kind == "line":
            off.add(n)
        elif kind == "next":
            off.add(n + 1)
        elif kind == "start":
            start = n
        elif kind == "end" and start is not None:
            off.update(range(start, n + 1))
            start = None
    if start is not None:
        off.update(range(start, len(lines) + 1))
    kept = [h for h in hits if h.line not in off]
    return kept, len(hits) - len(kept)


def _parse_attrs(body: str) -> dict:
    try:
        parts = shlex.split(body)
    except ValueError:
        parts = body.split()
    out: dict = {}
    for part in parts:
        name, eq, value = part.partition("=")
        if name in _ATTR_NAMES:
            out[name] = value if eq else True
    return out


def _attr_lines(lines: list[str]) -> list[tuple[int, dict, bool]]:
    """(line, attrs, standalone) for each ``l10n:`` attribute comment."""
    found = []
    for n, line in enumerate(lines, 1):
        if "l10n:" not in line and "llm-localizator:" not in line:
            continue
        c = _COMMENT.search(line)
        if not c:
            continue
        m = _ATTR.search(line, c.start())
        if m:
            found.append((n, _parse_attrs(m.group(1)), not line[:c.start()].strip()))
    return found


_STRING = re.compile(r"""(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")


def _force_include(lines: list[str], hits: list, marks: list, file: str) -> list:
    """`l10n: user-facing` adds a hit for a string literal the heuristics rejected."""
    if not file:
        return hits
    from .base import HardcodedString

    have = {h.line for h in hits}
    extra = []
    for n, attrs, alone in marks:
        if not attrs.get("user-facing"):
            continue
        target = n + 1 if alone else n
        if target in have or target > len(lines):
            continue
        for m in _STRING.finditer(lines[target - 1]):
            text = m.group(1) if m.group(1) is not None else m.group(2)
            if text and any(c.isalpha() for c in text):
                extra.append(HardcodedString(
                    text=text, file=file, line=target,
                    reason="marked `l10n: user-facing`", confidence="high"))
                break
    return list(hits) + extra if extra else hits


def annotate_hits(lines: list[str], hits: list, file: str = "") -> list:
    """Attach key/note/max-length/dnt/namespace hints to the hits they precede."""
    marks = _attr_lines(lines)
    if not marks:
        return hits
    hits = _force_include(lines, hits, marks, file)
    file_ns = next((a["namespace"] for _, a, alone in marks if alone and "namespace" in a), "")
    by_line: dict[int, dict] = {}
    for n, attrs, alone in marks:
        target = n + 1 if alone else n
        by_line.setdefault(target, {}).update(attrs)
    out = []
    for h in hits:
        a = by_line.get(h.line, {})
        ns = a.get("namespace") or file_ns
        if not a and not ns:
            out.append(h)
            continue
        out.append(dataclasses.replace(
            h,
            key_hint=str(a.get("key", "")),
            note=str(a.get("note", "")),
            max_length=int(a["max-length"]) if str(a.get("max-length", "")).isdigit() else 0,
            dnt=bool(a.get("dnt", False)),
            namespace_hint=str(ns or ""),
        ))
    return out


def apply_directives(
    lines: list[str], hits: list, aliases: bool = True, file: str = "",
) -> tuple[list, int]:
    kept, dropped = filter_hits(lines, hits, aliases)
    return annotate_hits(lines, kept, file), dropped


def lint_directives(lines: list[str], hits: list, aliases: bool = True) -> list[str]:
    """Problems in one file: stale ignores, late ignore-file, unbalanced blocks, typos.

    *hits* must be the unfiltered scan hits, or every working ignore looks stale.
    """
    marks = _directives(lines, aliases)
    hit_lines = {h.line for h in hits}
    problems: list[str] = []
    depth = 0
    for n, kind in marks:
        if kind == "line" and n not in hit_lines:
            problems.append(f"{n}: stale l10n-ignore (no hit on this line)")
        elif kind == "next" and (n + 1) not in hit_lines:
            problems.append(f"{n}: stale l10n-ignore-next-line (no hit below)")
        elif kind == "file" and n > _FILE_HEAD:
            problems.append(f"{n}: l10n-ignore-file must be in the first {_FILE_HEAD} lines")
        elif kind == "start":
            depth += 1
        elif kind == "end":
            depth -= 1
            if depth < 0:
                problems.append(f"{n}: l10n-ignore-end without start")
                depth = 0
    if depth > 0:
        problems.append("l10n-ignore-start without end")
    for n, line in enumerate(lines, 1):
        c = _COMMENT.search(line)
        if not c:
            continue
        tail = line[c.start():]
        for typo in re.findall(r"\bl10n-[a-z-]+", tail):
            if not _NATIVE.fullmatch(typo):
                problems.append(f"{n}: unknown directive {typo!r}")
    for n, line in enumerate(lines, 1):
        c = _COMMENT.search(line)
        m = _ATTR.search(line, c.start()) if c else None
        if not m:
            continue
        try:
            parts = shlex.split(m.group(1))
        except ValueError:
            problems.append(f"{n}: unbalanced quotes in l10n: directive")
            continue
        for part in parts:
            name = part.partition("=")[0]
            if name not in _ATTR_NAMES:
                problems.append(f"{n}: unknown l10n: attribute {name!r}")
    return problems
