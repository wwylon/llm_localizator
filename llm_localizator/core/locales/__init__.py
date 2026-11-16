"""Language profiles: one module per language holds everything known about it.

To teach the tool about a language, add ``<code>.py`` here exporting ``PROFILE``
(and, for regional variants such as ``fr-CA``, a ``VARIANTS`` map) and list the
module name in ``_MODULE_NAMES``. See ``docs/adding-a-language.md``.

Lookup is exact code, then the code with trailing subtags removed (``pl-PL`` ->
``pl``), then a generic default. It never raises.

Modules load lazily on first ``profile()`` / ``all_profiles()`` so importing
``llm_localizator.core`` does not pay for every language file up front.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from .base import (
    CLDR_CATEGORIES,
    KNOWN_SCRIPTS,
    LocaleProfile,
    TypographyCheck,
)

__all__ = [
    "LocaleProfile",
    "TypographyCheck",
    "all_profiles",
    "known_locales",
    "locale_name",
    "profile",
]

# Display order for language pickers: the languages the tool has always offered
# first, then everything else it knows something about.
_MODULE_NAMES: tuple[str, ...] = (
    "pl", "ar", "de", "fr", "es", "it", "ru", "nl", "sv", "pt", "zh", "ja", "he",
    "tr", "da", "nb", "fi", "is_", "id_", "bg", "hu", "cs", "el", "th", "vi", "ko",
    "en", "km", "lo", "my", "fa", "ur", "uk", "hi", "mr", "ne", "yi", "ps", "sd",
    "ug", "ku", "ckb", "dv", "sk", "ro", "hr", "sl", "no", "nn",
)

_DEFAULT = LocaleProfile(code="", name="", selectable=False)

_ALL: list[LocaleProfile] | None = None
_INDEX: dict[str, LocaleProfile] | None = None


def _module_code(module: ModuleType) -> str:
    return module.__name__.rsplit(".", 1)[-1].rstrip("_")


def _validate(item: LocaleProfile, base: str) -> None:
    where = f"locale profile {item.code!r}"
    if item.code.split("-")[0] != base:
        raise ValueError(f"{where}: code does not belong to module {base!r}")
    if not item.name:
        raise ValueError(f"{where}: name is required")
    if item.direction not in ("ltr", "rtl"):
        raise ValueError(f"{where}: direction must be ltr or rtl")
    if item.script not in KNOWN_SCRIPTS:
        raise ValueError(f"{where}: unknown script {item.script!r}")
    if not item.plural_categories or not set(item.plural_categories) <= CLDR_CATEGORIES:
        raise ValueError(f"{where}: bad plural categories {item.plural_categories!r}")
    if "other" not in item.plural_categories:
        raise ValueError(f"{where}: plural categories must include 'other'")
    if item.expansion_band is not None:
        low, high = item.expansion_band
        if not 0 < low < high:
            raise ValueError(f"{where}: expansion band must satisfy 0 < low < high")
    for check in item.typography_checks:
        if not check.fires(check.bad):
            raise ValueError(f"{where}: check {check.id!r} does not fire on its bad example")
        if check.fires(check.good):
            raise ValueError(f"{where}: check {check.id!r} fires on its good example")


def _build() -> tuple[list[LocaleProfile], dict[str, LocaleProfile]]:
    ordered: list[LocaleProfile] = []
    index: dict[str, LocaleProfile] = {}

    def register(item: LocaleProfile, base: str) -> None:
        _validate(item, base)
        ordered.append(item)
        for code in (item.code, *item.aliases):
            key = code.replace("_", "-").lower()
            if key in index:
                raise ValueError(f"locale code {code!r} is defined twice")
            index[key] = item

    pkg = __name__
    for name in _MODULE_NAMES:
        module = importlib.import_module(f".{name}", pkg)
        base = _module_code(module)
        register(module.PROFILE, base)
        for variant in getattr(module, "VARIANTS", {}).values():
            register(variant, base)
    return ordered, index


def _ensure() -> tuple[list[LocaleProfile], dict[str, LocaleProfile]]:
    global _ALL, _INDEX
    if _ALL is None or _INDEX is None:
        _ALL, _INDEX = _build()
    return _ALL, _INDEX


def profile(locale: str | None) -> LocaleProfile:
    """The profile for ``locale``, falling back to its base language, then a default."""
    _all, index = _ensure()
    key = (locale or "").replace("_", "-").lower()
    while key:
        found = index.get(key)
        if found is not None:
            return found
        if "-" not in key:
            break
        key = key.rsplit("-", 1)[0]
    return _DEFAULT


def all_profiles() -> list[LocaleProfile]:
    """Every profile, variants included, in display order."""
    ordered, _index = _ensure()
    return list(ordered)


def known_locales() -> list[str]:
    """Codes a person can pick from, in display order."""
    return [item.code for item in all_profiles() if item.selectable]


def locale_name(locale: str) -> str:
    """Human-readable language name for prompts; the code itself when unknown."""
    return profile(locale).name or locale
