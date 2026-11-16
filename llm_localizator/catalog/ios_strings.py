"""iOS/macOS .strings catalog adapter.

Reads and writes Apple Localizable.strings files:

    /* comment */
    "KEY" = "value";

    /* optional comment for KEY2 */
    "KEY2" = "Another value with \"quotes\" and \\backslash";

Escape sequences follow Apple's conventions:
    \\   →  backslash
    \"   →  double quote
    \n   →  newline
    \t   →  tab
    \r   →  carriage return

Objective-C / Swift format specifiers (``%@``, ``%d``, ``%1$@``) are preserved
as-is; they are not converted to ICU because that mapping is lossy and tooling
on the Apple side expects the native format.

Typical path template:

    path = "{locale}.lproj/Localizable.strings"

For a multi-namespace project:

    path = "{locale}.lproj/{namespace}.strings"
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Catalog, FlatMessages, warn_comments_lost
from .io import atomic_write_text

__all__ = ["IosStringsCatalog"]

# Match: "KEY" = "VALUE";
_PAIR_RE = re.compile(
    r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;'
)

_ESCAPE_MAP = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\t": "\\t",
    "\r": "\\r",
}

_UNESCAPE_MAP = {v: k for k, v in _ESCAPE_MAP.items()}


def _unescape(s: str) -> str:
    result = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            pair = s[i : i + 2]
            result.append(_UNESCAPE_MAP.get(pair, pair))
            i += 2
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _escape(s: str) -> str:
    out = []
    for ch in s:
        out.append(_ESCAPE_MAP.get(ch, ch))
    return "".join(out)


def _parse_strings(text: str) -> FlatMessages:
    out: FlatMessages = {}
    for m in _PAIR_RE.finditer(text):
        key = _unescape(m.group(1))
        val = _unescape(m.group(2))
        out[key] = val
    return out


def _render_strings(messages: FlatMessages) -> str:
    lines = []
    for key, val in sorted(messages.items()):
        ek = _escape(key)
        ev = _escape(val)
        lines.append(f'"{ek}" = "{ev}";')
    return "\n".join(lines) + "\n"


class IosStringsCatalog(Catalog):
    """Apple .strings message files (Localizable.strings)."""

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return self._cached_load(self.path_for(locale, namespace), self._parse_file)

    @staticmethod
    def _parse_file(path: Path) -> FlatMessages:
        if not path.exists():
            return {}
        # .strings files may be UTF-16 (Xcode default) or UTF-8
        for enc in ("utf-8-sig", "utf-16", "utf-8"):
            try:
                return _parse_strings(path.read_text(encoding=enc))
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"{path}: not decodable as UTF-8 or UTF-16; refusing to treat it as empty")

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        warn_comments_lost(path, "ios-strings", lambda t: "/*" in t or "//" in t)
        payload = _render_strings(messages)
        atomic_write_text(path, payload)
        self._bust_cache(path)
