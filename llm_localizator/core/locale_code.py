"""BCP-47 language subtag. No region map.

MADLAD region tags stay in the CTranslate2 provider. This function is only
the part before the first hyphen, matching ``locale.split("-")[0]``.
"""

from __future__ import annotations

__all__ = ["base_language"]


def base_language(locale: str | None) -> str:
    """Language subtag before the first ``-`` or ``_``.

    Does not lower-case. ``en_US`` and ``en-US`` both yield ``en``.
    """
    raw = (locale or "").replace("_", "-", 1)
    return raw.split("-", 1)[0]
