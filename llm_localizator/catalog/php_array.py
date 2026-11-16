"""PHP array catalog adapter (Laravel / Symfony).

Reads and writes PHP files of the form:

    <?php
    return [
        'key' => 'value',
        'nested' => [
            'child' => 'value',
        ],
    ];

Keys are flattened to dotted notation on load (``nested.child``).
Save reconstructs nesting via :func:`unflatten_messages`.

Typical path template (Laravel convention):

    path = "lang/{locale}/{namespace}.php"
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Catalog, FlatMessages, warn_comments_lost
from .io import atomic_write_text

__all__ = ["PhpArrayCatalog"]

_DQ_ESC = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "$": "$"}


def _php_unescape(s: str) -> str:
    """Convert PHP single-quoted string escapes (\\' and \\\\) to Python."""
    return s.replace("\\'", "'").replace("\\\\", "\\")


def _php_dq_unescape(s: str) -> str:
    return re.sub(r"\\(.)",lambda m: _DQ_ESC.get(m.group(1), m.group(0)), s)


def _php_literal(token: str) -> str:
    """Decode a quoted PHP string token (single or double quoted)."""
    body = token[1:-1]
    return _php_dq_unescape(body) if token[0] == '"' else _php_unescape(body)


def _php_escape(s: str) -> str:
    """Escape a value for a PHP single-quoted string."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _php_quote(s: str) -> str:
    """Single-quoted literal; double-quoted when control characters need escapes."""
    if any(c in s for c in "\n\r\t"):
        body = (
            s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        )
        return f'"{body}"'
    return f"'{_php_escape(s)}'"


_TOKEN_RE = re.compile(
    r"(?P<ws>\s+)"
    r"|(?P<comment>//[^\n]*|#[^\n]*|/\*.*?\*/)"
    r"""|(?P<str>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")"""
    r"|(?P<arrow>=>)"
    r"|(?P<open>\[|array\s*\()"
    r"|(?P<close>[\])])"
    r"|(?P<punct>[,.;])"
    r"""|(?P<other>[^\s'",.;\[\]()]+|[()])""",
    re.DOTALL | re.IGNORECASE,
)


class _PhpSyntax(ValueError):
    pass


def _tokens(text: str) -> list[tuple[str, str]]:
    body = text
    start = body.find("return")
    if start < 0:
        raise _PhpSyntax("no `return` statement")
    out: list[tuple[str, str]] = []
    pos = start + len("return")
    while pos < len(body):
        m = _TOKEN_RE.match(body, pos)
        if not m:
            raise _PhpSyntax(f"unexpected character at offset {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            continue
        out.append((kind, m.group(0)))
        if kind == "punct" and m.group(0) == ";":
            break
    return out


def _parse_tokens(tokens: list[tuple[str, str]]) -> FlatMessages:
    pos = 0

    def peek() -> tuple[str, str]:
        return tokens[pos] if pos < len(tokens) else ("eof", "")

    def take(kind: str) -> str:
        nonlocal pos
        k, v = peek()
        if k != kind:
            raise _PhpSyntax(f"expected {kind}, found {v or k!r}")
        pos += 1
        return v

    def string_expr() -> str:
        # One literal, or literals joined with the `.` operator.
        nonlocal pos
        parts = [_php_literal(take("str"))]
        while peek() == ("punct", ".") and pos + 1 < len(tokens) and tokens[pos + 1][0] == "str":
            pos += 1
            parts.append(_php_literal(take("str")))
        return "".join(parts)

    def array(prefix: str, out: FlatMessages) -> None:
        nonlocal pos
        take("open")
        while True:
            kind, _val = peek()
            if kind == "close":
                pos += 1
                return
            key = string_expr()
            take("arrow")
            full = f"{prefix}.{key}" if prefix else key
            if peek()[0] == "open":
                array(full, out)
            else:
                out[full] = string_expr()
            if peek() == ("punct", ","):
                pos += 1
            elif peek()[0] != "close":
                raise _PhpSyntax(f"unsupported value after {full!r}")

    out: FlatMessages = {}
    array("", out)
    return out


def _parse_php(text: str) -> FlatMessages:
    """Parse ``return [...]`` / ``return array(...)`` of string (or nested) values.

    Raises ``ValueError`` on anything else (function calls, constants,
    heredoc), so a save can never silently drop an entry it could not read.
    """
    return _parse_tokens(_tokens(text))


def _unparsed_entries(text: str) -> list[str]:
    """Why the file cannot be round-tripped, as a one-item list; empty when it can."""
    try:
        _parse_php(text)
    except ValueError as exc:
        return [str(exc)]
    return []


def _render_php_value(val, indent: int) -> list[str]:
    pad = "    " * indent
    if isinstance(val, dict):
        lines = [pad + "["]
        for k, v in sorted(val.items()):
            if isinstance(v, dict):
                lines.append(f"{pad}    {_php_quote(str(k))} => [")
                # Drop the opening "[" from nested render and re-indent body.
                nested = _render_php_value(v, indent + 2)
                lines.extend(nested[1:-1])
                lines.append(pad + "    ],")
            else:
                lines.append(f"{pad}    {_php_quote(str(k))} => {_php_quote(str(v))},")
        lines.append(pad + "]")
        return lines
    return [pad + _php_quote(str(val))]


def _render_php(messages: FlatMessages) -> str:
    from .json_nested import unflatten_messages

    tree = unflatten_messages(messages)
    lines = ["<?php", "return ["]
    for key, val in sorted(tree.items()):
        if isinstance(val, dict):
            lines.append(f"    {_php_quote(str(key))} => [")
            body = _render_php_value(val, 2)
            lines.extend(body[1:-1])
            lines.append("    ],")
        else:
            lines.append(f"    {_php_quote(str(key))} => {_php_quote(str(val))},")
    lines.append("];\n")
    return "\n".join(lines)


class PhpArrayCatalog(Catalog):
    """Laravel/Symfony PHP array message files."""

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return self._cached_load(self.path_for(locale, namespace), self._parse_file)

    @staticmethod
    def _parse_file(path: Path) -> FlatMessages:
        if not path.exists():
            return {}
        return _parse_php(path.read_text(encoding="utf-8"))

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        if path.is_file():
            bad = _unparsed_entries(path.read_text(encoding="utf-8"))
            if bad:
                raise ValueError(
                    f"{path}: {len(bad)} entr{'y' if len(bad) == 1 else 'ies'} the PHP "
                    f"adapter cannot read (first: {bad[0][:60]!r}); refusing to rewrite "
                    "the file and drop them"
                )
        warn_comments_lost(
            path, "php-array",
            lambda t: bool(re.search(r"^\s*(//|#|/\*)", t, re.MULTILINE)),
        )
        payload = _render_php(messages)
        atomic_write_text(path, payload)
        self._bust_cache(path)
