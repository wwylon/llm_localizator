"""Soft-hyphen insertion for compound-heavy locales.

Cosmetic post-process: inserts U+00AD at syllable boundaries so long German or
Dutch compounds can wrap inside narrow UI elements. The translation *content* is
unchanged. Requires the optional ``pyphen`` dependency; without it this is a
no-op, which is the correct degradation -- an un-hyphenated compound still
renders, it just wraps less gracefully.
"""

from __future__ import annotations

import re

from .locales import profile

__all__ = ["apply_soft_hyphens", "pyphen_available"]

SOFT_HYPHEN = "­"
_MIN_TOKEN_LEN = 12  # only hyphenate tokens longer than this

try:  # pragma: no cover - trivial import guard
    import pyphen as _pyphen_mod

    _PYPHEN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _pyphen_mod = None
    _PYPHEN_AVAILABLE = False

_dicts: dict[str, object | None] = {}
_WORD_RE = re.compile(r"(\W*)([\wÀ-ɏ]+)(\W*)")


def pyphen_available() -> bool:
    """Whether the optional hyphenation backend is installed."""
    return _PYPHEN_AVAILABLE


def _dict_for(locale: str):
    if not _PYPHEN_AVAILABLE or _pyphen_mod is None:
        return None
    if locale not in _dicts:
        lang = locale.replace("-", "_").split("_")[0]
        try:
            _dicts[locale] = _pyphen_mod.Pyphen(lang=lang)
        except Exception:
            _dicts[locale] = None
    return _dicts[locale]


def apply_soft_hyphens(text: str, locale: str) -> str:
    """Insert soft hyphens into long tokens for locales whose profile sets ``hyphenate``.

    Returns ``text`` unchanged for every other locale, and whenever pyphen is
    unavailable or has no dictionary for the language.
    """
    if not profile(locale).hyphenate:
        return text
    dic = _dict_for(locale)
    if dic is None:
        return text

    parts: list[str] = []
    for word in re.split(r"(\s+)", text):
        if not word or word.isspace():
            parts.append(word)
            continue
        # Strip surrounding punctuation so hyphens aren't inserted at odd spots.
        m = _WORD_RE.fullmatch(word)
        if m and len(m.group(2)) > _MIN_TOKEN_LEN:
            parts.append(m.group(1) + dic.inserted(m.group(2), hyphen=SOFT_HYPHEN) + m.group(3))
        else:
            parts.append(word)
    return "".join(parts)
