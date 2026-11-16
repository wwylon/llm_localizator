"""Plural fields for the editor. The page does not parse message syntax.

A row is plural only when the active standard says so. Sibling-key standards
(i18next) report no in-string categories, so they stay one field. Joining
uses the ICU builder because that is the catalogue value those standards
store after load (ADR-36).
"""

from __future__ import annotations

from ..core.cldr import required_plural_categories
from ..core.plurals import PluralSet, build_icu_plural, parse_icu_plural
from ..core.standards import get_standard

_ORDER = ("zero", "one", "two", "few", "many", "other")


def _categories(locale: str) -> list[str]:
    wanted = required_plural_categories(locale)
    ordered = [name for name in _ORDER if name in wanted]
    ordered.extend(sorted(wanted - set(ordered)))
    return ordered


def plural_view(
    source: str,
    value: str,
    locale: str,
    standard_name: str | None,
) -> dict | None:
    """Fields for one locale, or ``None`` when the source is not an in-string plural."""
    standard = get_standard(standard_name)
    if standard.plural_categories(source) is None:
        return None
    parsed = parse_icu_plural(source)
    if parsed is None:
        return None
    target = parse_icu_plural(value or "")
    branches = {
        name: (target.branches.get(name) if target else "") or ""
        for name in _categories(locale)
    }
    return {
        "variable": parsed.variable,
        "prefix": parsed.prefix,
        "suffix": parsed.suffix,
        "categories": list(branches),
        "branches": branches,
    }


def joined_value(
    source: str,
    branches: dict,
    body: dict,
    standard_name: str | None,
) -> str | None:
    """One catalogue string, or ``None`` when branches must be ignored."""
    if not isinstance(branches, dict) or not branches:
        return None
    standard = get_standard(standard_name)
    if standard.plural_categories(source) is None:
        return None
    parsed = parse_icu_plural(source)
    if parsed is None:
        return None
    variable = str(body.get("pluralVariable") or parsed.variable)
    prefix = body.get("pluralPrefix")
    suffix = body.get("pluralSuffix")
    if prefix is None:
        prefix = parsed.prefix
    if suffix is None:
        suffix = parsed.suffix
    cleaned = {str(key): "" if text is None else str(text) for key, text in branches.items()}
    return build_icu_plural(PluralSet(
        variable, cleaned, prefix=str(prefix), suffix=str(suffix),
        keyword=parsed.keyword,
    ))
