"""Apple ``.stringsdict`` catalog adapter (plural rules).

A ``.stringsdict`` is an XML plist. Each top-level key maps to::

    NSStringLocalizedFormatKey = "%#@items@"
    items = { NSStringFormatSpecTypeKey = NSStringPluralRuleType,
              NSStringFormatValueTypeKey = d, one = "%d item", other = "%d items" }

It is flattened to one ICU plural message per key, with the ``%#@var@`` token
replaced by ``{var, plural, one {...} other {...}}`` so the engine's plural
validation applies. Entries that do not fit that shape (several variables,
non-plural rule types) raise on load: saving would otherwise drop them.

Path template: ``{locale}.lproj/Localizable.stringsdict``.
"""

from __future__ import annotations

import plistlib
import re
from pathlib import Path

from .base import Catalog, FlatMessages
from .io import atomic_write_text

__all__ = ["IosStringsdictCatalog"]

_TOKEN_RE = re.compile(r"%#@([A-Za-z_][A-Za-z0-9_]*)@")
_FMT_KEY = "NSStringLocalizedFormatKey"
_SPEC = "NSStringFormatSpecTypeKey"
_VALUE = "NSStringFormatValueTypeKey"
_PLURAL = "NSStringPluralRuleType"


def _entry_to_icu(path: Path, key: str, entry: dict) -> str:
    fmt = entry.get(_FMT_KEY)
    tokens = _TOKEN_RE.findall(fmt) if isinstance(fmt, str) else []
    if len(tokens) != 1:
        raise ValueError(f"{path}: {key!r} needs exactly one %#@var@ token; refusing to flatten it lossily")
    var = tokens[0]
    rule = entry.get(var)
    if not isinstance(rule, dict) or rule.get(_SPEC) != _PLURAL:
        raise ValueError(f"{path}: {key!r} variable {var!r} is not a plural rule; refusing to flatten it")
    branches = " ".join(
        f"{cat} {{{text}}}" for cat, text in rule.items() if cat not in (_SPEC, _VALUE)
    )
    return _TOKEN_RE.sub(lambda _m: f"{{{var}, plural, {branches}}}", fmt, count=1)


def _find_plural_block(icu: str) -> tuple[int, int, str, str] | None:
    """(start, end, var, body) of the first top-level ``{var, plural, ...}``."""
    depth = 0
    start = -1
    for i, ch in enumerate(icu):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                inner = icu[start + 1 : i]
                m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*plural\s*,(.*)$", inner, re.S)
                if m:
                    return start, i + 1, m.group(1), m.group(2)
                start = -1
    return None


def _split_branches(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    pos = 0
    while True:
        m = re.compile(r"\s*(=\d+|\w+)\s*\{").match(body, pos)
        if not m:
            break
        depth = 1
        j = m.end()
        while j < len(body) and depth:
            depth += {"{": 1, "}": -1}.get(body[j], 0)
            j += 1
        out[m.group(1)] = body[m.end() : j - 1]
        pos = j
    return out


def _icu_to_entry(key: str, icu: str, old: dict | None) -> dict:
    block = _find_plural_block(icu)
    if block is None:
        raise ValueError(f"{key!r}: a stringsdict entry must hold a plural message, got {icu[:40]!r}")
    start, end, var, body = block
    value_type = "d"
    if old and isinstance(old.get(var), dict):
        value_type = old[var].get(_VALUE, "d")
    rule: dict = {_SPEC: _PLURAL, _VALUE: value_type}
    rule.update(_split_branches(body))
    return {_FMT_KEY: icu[:start] + f"%#@{var}@" + icu[end:], var: rule}


class IosStringsdictCatalog(Catalog):
    """Apple .stringsdict plural files."""

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        return self._cached_load(self.path_for(locale, namespace), self._parse_file)

    @staticmethod
    def _read_plist(path: Path) -> dict:
        data = plistlib.loads(path.read_bytes())
        if not isinstance(data, dict):
            raise ValueError(f"{path}: stringsdict root is not a dictionary")
        return data

    @staticmethod
    def _parse_file(path: Path) -> FlatMessages:
        if not path.exists():
            return {}
        data = IosStringsdictCatalog._read_plist(path)
        return {
            key: _entry_to_icu(path, key, entry)
            for key, entry in data.items()
            if isinstance(entry, dict)
        }

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        old = self._read_plist(path) if path.is_file() else {}
        if path.is_file():
            self._parse_file(path)  # refuse to rewrite a file we cannot flatten
        out = {k: _icu_to_entry(k, v, old.get(k)) for k, v in sorted(messages.items())}
        atomic_write_text(path, plistlib.dumps(out, sort_keys=False).decode("utf-8"))
        self._bust_cache(path)
