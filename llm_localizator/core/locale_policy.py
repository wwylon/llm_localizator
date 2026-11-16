"""Locale-scoped policy: script, plurals, direction, and formality defaults.

Pure data/functions — no I/O. Folded from quality/CLDR/locale_ui so prompts and
validators share one source of truth (audit A1 / ADR-25).
"""

from __future__ import annotations

from dataclasses import dataclass

from .cldr import language_name, required_plural_categories
from .locale_ui import text_direction
from .quality import expected_script, script_prompt_rule

__all__ = ["LocalePolicy"]


@dataclass(frozen=True)
class LocalePolicy:
    """Canonical locale behaviour for prompting and hard gates."""

    locale: str
    language: str
    script: str
    direction: str
    plural_categories: tuple[str, ...]
    register: str = "informal"

    @classmethod
    def for_locale(cls, locale: str, *, register: str = "informal") -> LocalePolicy:
        loc = locale or ""
        return cls(
            locale=loc,
            language=language_name(loc),
            script=expected_script(loc),
            direction=text_direction(loc),
            plural_categories=tuple(sorted(required_plural_categories(loc))),
            register=register or "informal",
        )

    def script_rule(self) -> str:
        """Prompt fragment; matches ``check_unexpected_script`` policy."""
        return script_prompt_rule(self.locale, self.language)

    def script_check_issues(self, source: str, translated: str) -> list[str]:
        """Advisory script issues for this locale (V21 family)."""
        from .script_checks import check_script_issues

        return check_script_issues(source, translated, self.locale)
