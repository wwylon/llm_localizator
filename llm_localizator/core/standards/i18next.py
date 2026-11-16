"""i18next ``{{name}}`` tokens and sibling-key plurals.

``{{name}}`` is one token. It is not an ICU placeholder. Plural forms are
sibling keys (``key_one``, ``key_other``, and the other CLDR suffixes), not
syntax inside the string. v4 nested objects are out of scope.
"""

from __future__ import annotations

import re

from ..cldr import required_plural_categories

__all__ = ["I18nextStandard"]

_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")
_NAME = re.compile(r"[A-Za-z_][\w]*")


class I18nextStandard:
    id = "i18next"
    has_plurals = True

    def tokens(self, text: str) -> set[str]:
        found, _err = _scan(text)
        return found

    def syntax_error(self, text: str) -> str | None:
        _found, err = _scan(text)
        return err

    def plural_categories(self, text: str) -> set[str] | None:
        return None

    def missing_plural_keys(self, messages: dict[str, str], locale: str) -> list[str]:
        keys = set(messages)
        bases: set[str] = set()
        for key in keys:
            for suffix in _SUFFIXES:
                if key.endswith(suffix) and len(key) > len(suffix):
                    bases.add(key[: -len(suffix)])
                    break
        required = required_plural_categories(locale)
        missing: list[str] = []
        for base in sorted(bases):
            for category in sorted(required):
                sibling = f"{base}_{category}"
                if sibling not in keys:
                    missing.append(sibling)
        return missing


def _scan(text: str) -> tuple[set[str], str | None]:
    out: set[str] = set()
    i = 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            return out, None
        end = text.find("}}", start + 2)
        if end < 0:
            return out, "unclosed '{{'"
        inner = text[start + 2:end].strip()
        if inner.startswith("."):
            return out, "go template is not an i18next placeholder"
        if not _NAME.fullmatch(inner):
            return out, "invalid i18next placeholder"
        out.add(inner)
        i = end + 2
