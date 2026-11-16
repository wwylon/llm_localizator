"""Laravel ``:name`` replacement tokens.

A colon followed by an identifier. Not a token inside a time (``12:30``) or
when the colon continues a word (``mailto:name``). No plural syntax.
"""

from __future__ import annotations

import re

__all__ = ["LaravelStandard"]

# The character before ``:`` must not be a letter or digit, so ``12:30`` and
# ``mailto:user`` are not tokens. ``:name`` at the start of a string is.
_TOKEN = re.compile(r"(?<![A-Za-z0-9]):([A-Za-z_][\w]*)")


class LaravelStandard:
    id = "laravel"
    has_plurals = False

    def tokens(self, text: str) -> set[str]:
        return {match.group(0) for match in _TOKEN.finditer(text)}

    def syntax_error(self, text: str) -> str | None:
        return None

    def plural_categories(self, text: str) -> set[str] | None:
        return None

    def missing_plural_keys(self, messages: dict[str, str], locale: str) -> list[str]:
        return []
