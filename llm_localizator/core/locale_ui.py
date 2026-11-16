"""Locale display hints for the web UI (pure, no I/O)."""

from __future__ import annotations

from .locales import profile

__all__ = ["text_direction", "font_family"]

_FONT_STACKS: dict[str, str] = {
    "latin": '"Noto Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
    "arabic": '"Noto Naskh Arabic", "Noto Sans Arabic", serif',
    "hebrew": '"Noto Sans Hebrew", "Arial Hebrew", sans-serif',
    "cyrillic": '"Noto Sans", system-ui, sans-serif',
    "cjk": '"Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans CJK KR", sans-serif',
    "thai": '"Noto Sans Thai", sans-serif',
}

def text_direction(locale: str) -> str:
    return profile(locale).direction


def font_family(locale: str) -> str:
    return _FONT_STACKS.get(profile(locale).script, _FONT_STACKS["latin"])
