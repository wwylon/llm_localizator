"""Java .properties catalog adapter (Spring, Java ResourceBundle).

Reads and writes ISO-8859-1 / UTF-8 .properties files:

    # comment
    ! also a comment
    loginTitle=Sign in
    registerTitle=Create account
    greet=Hello {0}!

Key and value may be separated by ``=``, ``:`` or whitespace.
Trailing whitespace is stripped from values.
Line continuation with a backslash at end of line is supported.
Standard Java escapes (``\\n``, ``\\t``, ``\\\\``, ``\\=``, ``\\uXXXX``) are decoded
on load; on save, backslashes, newlines and non-ASCII characters are re-escaped
so a value round-trips.

Saving rewrites the whole file (sorted by key), so ``#`` / ``!`` comments and
blank lines are not preserved. A one-time warning is emitted the first time a
file that contains comments is saved.

Typical path template (Spring Boot convention):

    path = "src/main/resources/messages_{locale}.properties"

Or with a messages/ directory:

    path = "src/main/resources/messages/{locale}.properties"
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Catalog, FlatMessages, warn_comments_lost
from .io import atomic_write_text

__all__ = ["PropertiesCatalog"]

_COMMENT_RE = re.compile(r"^[#!]")
_ESCAPE_RE = re.compile(r"\\(u[0-9A-Fa-f]{4}|.)", re.DOTALL)
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f"}


def _unescape(s: str) -> str:
    def repl(m: re.Match) -> str:
        tok = m.group(1)
        if len(tok) == 5 and tok[0] == "u":
            return chr(int(tok[1:], 16))
        return _SIMPLE_ESCAPES.get(tok, tok)

    text = _ESCAPE_RE.sub(repl, s)
    if any("\ud800" <= c <= "\udfff" for c in text):  # surrogate pair from 😀
        text = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return text


def _escape(s: str, *, key: bool = False) -> str:
    out = []
    for i, ch in enumerate(s):
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\f":
            out.append("\\f")
        elif ord(ch) > 127:
            cp = ord(ch)
            if cp > 0xFFFF:
                cp -= 0x10000
                out.append(f"\\u{0xD800 + (cp >> 10):04X}\\u{0xDC00 + (cp & 0x3FF):04X}")
            else:
                out.append(f"\\u{cp:04X}")
        elif key and ch in "=: #!":
            out.append("\\" + ch)
        elif ch == " " and i == 0:
            out.append("\\ ")  # a leading space would be eaten as separator padding
        else:
            out.append(ch)
    return "".join(out)


def _continues(line: str) -> bool:
    """True for an odd run of trailing backslashes (an escaped one does not continue)."""
    return (len(line) - len(line.rstrip("\\"))) % 2 == 1


def _logical_lines(text: str) -> list[str]:
    """Join backslash continuations."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        while _continues(line) and i < len(lines):
            line = line[:-1] + lines[i].lstrip()
            i += 1
        out.append(line)
    return out


def _split_pair(line: str) -> tuple[str, str] | None:
    """Split on the first unescaped ``=``, ``:`` or whitespace."""
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch in "=: \t":
            break
        i += 1
    key = line[:i]
    if not key:
        return None
    rest = line[i:].lstrip(" \t")
    if rest[:1] in ("=", ":"):
        rest = rest[1:].lstrip(" \t")
    return key, rest


def _parse_properties(text: str) -> FlatMessages:
    out: FlatMessages = {}
    for line in _logical_lines(text):
        stripped = line.lstrip()
        if not stripped or _COMMENT_RE.match(stripped):
            continue
        pair = _split_pair(stripped)
        if pair is None:
            continue
        key, val = pair
        out[_unescape(key)] = _unescape(val.rstrip())
    return out


def _has_comments(text: str) -> bool:
    return any(_COMMENT_RE.match(ln.lstrip()) for ln in text.splitlines())


def _render_properties(messages: FlatMessages) -> str:
    lines = []
    for key, val in sorted(messages.items()):
        lines.append(f"{_escape(key, key=True)}={_escape(val)}")
    return "\n".join(lines) + "\n"


class PropertiesCatalog(Catalog):
    """Java/Spring .properties message files."""

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return self._cached_load(self.path_for(locale, namespace), self._parse_file)

    @staticmethod
    def _parse_file(path: Path) -> FlatMessages:
        if not path.exists():
            return {}
        for enc in ("utf-8-sig", "utf-8", "iso-8859-1"):
            try:
                return _parse_properties(path.read_text(encoding=enc))
            except UnicodeDecodeError:
                continue
        return {}

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        warn_comments_lost(path, "properties", _has_comments)
        payload = _render_properties(messages)
        atomic_write_text(path, payload)
        self._bust_cache(path)
