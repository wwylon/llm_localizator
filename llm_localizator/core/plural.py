"""Map a number to a CLDR plural category.

``core/cldr.py`` lists category names. This module is the selection rule.
No I/O. Rules cover the locales this package already names; anything else
uses the English one/other split.
"""

from __future__ import annotations

import math
from decimal import Decimal

from .locale_code import base_language

__all__ = ["plural_operands", "plural_category", "sample_numbers"]


def plural_operands(n: int | float) -> tuple[int, int]:
    """Return ``(i, v)``: absolute integer digits, and visible fraction digits."""
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        raise TypeError(f"plural operand must be a number, got {n!r}")
    if isinstance(n, int):
        return abs(n), 0
    if not math.isfinite(n):
        return 0, 0
    # Decimal parses exponent notation (1e-7, 1.5e-07) into visible digits.
    dec = Decimal(repr(float(n))).normalize()
    exp = dec.as_tuple().exponent
    return abs(int(dec)), max(0, -exp) if isinstance(exp, int) else 0


def _lang(locale: str) -> str:
    return base_language((locale or "en").replace("_", "-")).lower() or "en"


def _is_pt_pt(locale: str) -> bool:
    return (locale or "").replace("_", "-").lower() in {"pt-pt", "pt-ao", "pt-mz"}


def plural_category(locale: str, n: int | float) -> str:
    """CLDR plural category for *n* in *locale*."""
    i, v = plural_operands(n)
    lang = _lang(locale)
    if lang == "pl":
        if v == 0 and i == 1:
            return "one"
        if v == 0 and i % 10 in (2, 3, 4) and i % 100 not in (12, 13, 14):
            return "few"
        if v == 0 and (
            (i % 10 in (0, 1) and i != 1)
            or i % 10 in (5, 6, 7, 8, 9)
            or i % 100 in (12, 13, 14)
        ):
            return "many"
        return "other"
    if lang in {"ru", "uk", "be"}:
        if v == 0 and i % 10 == 1 and i % 100 != 11:
            return "one"
        if v == 0 and i % 10 in (2, 3, 4) and i % 100 not in (12, 13, 14):
            return "few"
        if v == 0 and (i % 10 == 0 or i % 10 in (5, 6, 7, 8, 9) or i % 100 in range(11, 15)):
            return "many"
        return "other"
    if lang in {"hr", "sr", "bs"}:
        # CLDR hr/sr/bs: one / few / other (no many).
        if v == 0 and i % 10 == 1 and i % 100 != 11:
            return "one"
        if v == 0 and i % 10 in (2, 3, 4) and i % 100 not in (12, 13, 14):
            return "few"
        return "other"
    if lang in {"cs", "sk"}:
        if v == 0 and i == 1:
            return "one"
        if v == 0 and i in (2, 3, 4):
            return "few"
        if v != 0:
            return "many"
        return "other"
    if lang == "sl":
        rem = i % 100
        if v == 0 and rem == 1:
            return "one"
        if v == 0 and rem == 2:
            return "two"
        if (v == 0 and rem in (3, 4)) or v != 0:
            return "few"
        return "other"
    if lang == "ro":
        if v == 0 and i == 1:
            return "one"
        if v != 0 or n == 0 or (n != 1 and i % 100 in range(1, 20)):
            return "few"
        return "other"
    if lang == "ar":
        if n == 0:
            return "zero"
        if n == 1:
            return "one"
        if n == 2:
            return "two"
        if v == 0 and i % 100 in range(3, 11):
            return "few"
        if v == 0 and i % 100 in range(11, 100):
            return "many"
        return "other"
    if lang == "he":
        if v == 0 and i == 1:
            return "one"
        if v == 0 and i == 2:
            return "two"
        if v == 0 and i > 10 and i % 10 == 0:
            return "many"
        return "other"
    if lang in {"zh", "ja", "ko", "th", "vi", "id", "ms"}:
        return "other"
    if lang in {"fr", "hy", "ff"} or (lang == "pt" and not _is_pt_pt(locale)):
        # CLDR: zero and one are both "one" (0 and 1,x).
        return "one" if i in (0, 1) else "other"
    if lang in {"hi", "bn", "gu", "kn", "zu", "am", "fa"}:
        return "one" if i == 0 or (v == 0 and i == 1) or n == 1 else "other"
    if v == 0 and i == 1:
        return "one"
    return "other"


def sample_numbers(locale: str) -> list[int | float]:
    """Numbers that exercise the categories a reviewer should see."""
    lang = _lang(locale)
    if lang == "pl":
        return [1, 2, 5, 1.5]
    if lang == "ar":
        return [0, 1, 2, 3, 11, 100]
    if lang in {"ru", "uk", "cs", "sk"}:
        return [1, 2, 5, 1.5]
    if lang == "sl":
        return [1, 2, 3, 5]
    if lang in {"hr", "ro"}:
        return [1, 2, 5]
    if lang in {"zh", "ja", "ko", "th", "vi", "id"}:
        return [1, 5]
    return [1, 2]
