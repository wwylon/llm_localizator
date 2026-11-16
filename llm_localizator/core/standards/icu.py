"""ICU message syntax. Wraps the existing extractor. V02 and V03 stay as they are."""

from __future__ import annotations

from ..icu import extract_placeholders, extract_plural_categories

__all__ = ["IcuStandard"]


class IcuStandard:
    id = "icu"
    has_plurals = True

    def tokens(self, text: str) -> set[str]:
        return extract_placeholders(text)

    def syntax_error(self, text: str) -> str | None:
        depth = 0
        for ch in text:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    return "unbalanced '}'"
        if depth != 0:
            return "unclosed '{'"
        return None

    def plural_categories(self, text: str) -> set[str] | None:
        return extract_plural_categories(text)

    def missing_plural_keys(self, messages: dict[str, str], locale: str) -> list[str]:
        return []
