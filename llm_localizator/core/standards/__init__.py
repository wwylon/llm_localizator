"""Registered message standards. One object per id. No I/O."""

from __future__ import annotations

from .base import MessageStandard
from .brace import BraceStandard
from .go_template import GoTemplateStandard
from .i18next import I18nextStandard
from .icu import IcuStandard
from .laravel import LaravelStandard
from .printf import PrintfStandard

__all__ = ["MessageStandard", "get_standard", "uses_icu"]

_ICU = IcuStandard()
_STANDARDS: dict[str, MessageStandard] = {
    "icu": _ICU,
    "printf": PrintfStandard(),
    "brace": BraceStandard(),
    "i18next": I18nextStandard(),
    "go-template": GoTemplateStandard(),
    "laravel": LaravelStandard(),
}


def get_standard(name: str | None = None) -> MessageStandard:
    """Return the standard named by config. Missing or ``icu`` is the ICU wrapper."""
    key = name or "icu"
    if key not in _STANDARDS:
        known = ", ".join(sorted(_STANDARDS))
        raise ValueError(f"unknown message standard {key!r} (known: {known})")
    return _STANDARDS[key]


def uses_icu(name: str | None) -> bool:
    return (name or "icu") == "icu"
