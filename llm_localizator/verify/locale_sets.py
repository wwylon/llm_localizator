"""Named locale sets for ``verify --locales`` (plan Part 3).

Each set groups languages that stress one thing (plural rules, bidi, scripts
written without spaces, ...). ``unprofiled`` lists languages with no profile
yet: the engine must fall back gracefully, and the list doubles as a to-do for
``docs/adding-a-language.md``.
"""

from __future__ import annotations

__all__ = ["LOCALE_SETS", "resolve_locales"]

LOCALE_SETS: dict[str, tuple[str, ...]] = {
    "plurals": ("pl", "ru", "uk", "cs", "ar", "lt", "ga", "cy"),
    "rtl": ("ar", "he", "fa", "ur", "ckb", "yi", "dv"),
    "nospace": ("ja", "zh-Hans", "zh-Hant", "th", "lo", "km", "my"),
    "indic": ("hi", "mr", "ne", "bn", "ta", "si"),
    "casing": ("tr", "vi", "el", "de", "fi", "hu"),
    "regional": ("pt-BR", "pt-PT", "es-ES", "es-419", "en-GB", "fr-CA", "sr-Latn", "sr-Cyrl"),
    "unprofiled": ("sw", "am", "ka", "hy", "ga", "cy", "lt", "lv", "sr", "bn", "ta", "si"),
    "pseudo": ("en-XA", "qps-ploc"),
}


def resolve_locales(spec: str | None) -> list[str]:
    """Expand ``"plurals,de"`` into a de-duplicated locale list; unknown names are codes."""
    out: list[str] = []
    for token in (spec or "").replace(" ", "").split(","):
        if not token:
            continue
        for code in LOCALE_SETS.get(token, (token,)):
            if code not in out:
                out.append(code)
    return out
