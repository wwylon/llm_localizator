"""Go ``text/template`` field tokens: ``{{.Name}}`` and ``{{ .Name }}``.

Distinguished from i18next by the leading dot. Control actions such as
``{{if .Ok}}`` are not replacement tokens. No plural syntax.
"""

from __future__ import annotations

import re

__all__ = ["GoTemplateStandard"]

_FIELD = re.compile(r"\.[A-Za-z_][\w.]*")


class GoTemplateStandard:
    id = "go-template"
    has_plurals = False

    def tokens(self, text: str) -> set[str]:
        found, _err = _scan(text)
        return found

    def syntax_error(self, text: str) -> str | None:
        _found, err = _scan(text)
        return err

    def plural_categories(self, text: str) -> set[str] | None:
        return None

    def missing_plural_keys(self, messages: dict[str, str], locale: str) -> list[str]:
        return []


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
        if _FIELD.fullmatch(inner):
            out.add(inner)
        i = end + 2
