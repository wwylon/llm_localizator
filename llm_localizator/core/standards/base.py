"""Message-standard protocol.

``validate_translation`` and the source check call this. They do not grow a
branch per syntax. New standards do not rewrite stored text into ICU.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["MessageStandard"]


class MessageStandard(Protocol):
    id: str
    has_plurals: bool

    def tokens(self, text: str) -> set[str]:
        """Replacement tokens that must survive translation."""

    def syntax_error(self, text: str) -> str | None:
        """Unclosed or unknown token, or ``None`` when the string is well-formed."""

    def plural_categories(self, text: str) -> set[str] | None:
        """CLDR categories in this string, or ``None`` when it is not a plural."""

    def missing_plural_keys(self, messages: dict[str, str], locale: str) -> list[str]:
        """Sibling keys a plural family still needs. Empty for in-string plurals."""
