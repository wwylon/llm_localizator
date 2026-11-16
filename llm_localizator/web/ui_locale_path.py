"""URL-prefix UI locale for the review shell (ADR-108, ADR-110).

Canonical app paths are ``/{lang}/app/...``. Bare ``/app/...`` 302s using the
``llm_ui_locale`` cookie (JS syncs from localStorage). ``/api``, ``/static``,
and ``/locales`` stay unprefixed. When a prefix is present it wins over storage.

QA marker locales (``en-XX``, ``en-XA``) are opt-in via ``[web] qa_locales``
(ADR-110). They are never translate targets.
"""

from __future__ import annotations

import re

__all__ = [
    "BASE_UI_LOCALES",
    "KNOWN_QA_LOCALES",
    "UI_LOCALES",
    "UI_LOCALE_COOKIE",
    "ui_locales",
    "split_ui_locale_path",
    "prefixed_path",
    "needs_locale_redirect",
]

# Production / consumer picker — no marker locales.
BASE_UI_LOCALES = frozenset({"en", "de", "pl", "fr", "ar"})
# Pseudo QA markers (ADR-110). Enable only via ``[web] qa_locales``.
KNOWN_QA_LOCALES = frozenset({"en-XX", "en-XA"})
# Back-compat: union of base + known QA (tests / call sites that do not
# pass a project config still accept the marker in path parsing).
UI_LOCALES = BASE_UI_LOCALES | KNOWN_QA_LOCALES
UI_LOCALE_COOKIE = "llm_ui_locale"

# Longer codes before shorter (en-XX before en).
_PREFIXED = re.compile(
    r"^/(?P<lang>en-XX|en-XA|en|de|pl|fr|ar)"
    r"(?P<rest>/app(?:/.*)?|/login|/register|/pending|/setup)/?$"
)
_BARE_APP = re.compile(r"^/app(?:/.*)?$")
_BARE_AUTH = re.compile(r"^/(?:login|register|pending|setup)/?$")


def ui_locales(qa_locales: list[str] | tuple[str, ...] | None = None) -> frozenset[str]:
    """Locales allowed in the picker and URL prefix for this project."""
    allowed = set(BASE_UI_LOCALES)
    for code in qa_locales or ():
        code = str(code).strip()
        if code in KNOWN_QA_LOCALES:
            allowed.add(code)
    return frozenset(allowed)


def split_ui_locale_path(path: str) -> tuple[str | None, str]:
    """Return ``(locale_or_None, path_without_prefix)``."""
    match = _PREFIXED.match(path or "")
    if not match:
        return None, path
    rest = match.group("rest") or "/"
    if rest != "/" and rest.endswith("/"):
        rest = rest.rstrip("/") or "/"
    return match.group("lang"), rest


def needs_locale_redirect(path: str) -> bool:
    """True when the path is a bare app/auth URL that should gain a locale prefix."""
    if not path:
        return False
    if split_ui_locale_path(path)[0] is not None:
        return False
    return bool(_BARE_APP.match(path) or _BARE_AUTH.match(path))


def prefixed_path(
    locale: str,
    path: str,
    *,
    allowed: frozenset[str] | None = None,
) -> str:
    """Join ``/{locale}`` with an unprefixed app/auth path."""
    ok = allowed if allowed is not None else UI_LOCALES
    loc = locale if locale in ok else "en"
    if not path.startswith("/"):
        path = "/" + path
    return f"/{loc}{path}"
