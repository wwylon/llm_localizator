"""Preview renderers. A new format is a function plus one registry line.

``preview(text, locale) -> safe HTML``. The stored catalogue text is never
replaced by this output.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..core.icu import extract_placeholders
from .html_preview import preview_html
from .icu import (
    coerce_preview_values,
    has_icu,
    preview_icu,
    preview_icu_filled,
)
from .markdown import preview_markdown

__all__ = [
    "RENDERERS",
    "has_icu",
    "preview",
    "preview_if_icu",
    "preview_payload",
    "register_renderer",
]

Renderer = Callable[[str, str], str]

RENDERERS: dict[str, Renderer] = {
    "icu": preview_icu,
    "markdown": preview_markdown,
    "html": preview_html,
}


def register_renderer(name: str, fn: Renderer) -> None:
    """Register *fn* under *name*. Later formats call this; nothing else changes."""
    RENDERERS[name] = fn


def preview(text: str, locale: str, fmt: str) -> str:
    try:
        fn = RENDERERS[fmt]
    except KeyError:
        known = ", ".join(sorted(RENDERERS))
        raise ValueError(f"unknown preview format {fmt!r} (known: {known})") from None
    return fn(text, locale)


def preview_if_icu(text: str, locale: str) -> str:
    """HTML preview when *text* contains a plural or select; otherwise empty."""
    if not text or not has_icu(text):
        return ""
    return preview_icu(text, locale)


def preview_payload(
    text: str,
    locale: str,
    fmt: str,
    *,
    values: Mapping[str, object] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """HTML preview plus placeholder names for the editor sample fields.

    *mode*:
      - ``filled`` (default when *values* is a non-empty mapping for ICU): one
        rendered sample via ``render_message``.
      - ``samples``: multi-arm plural/select list (``preview_icu``), merging
        *values* into every row so bare placeholders are not left literal.
      - omitted: ``filled`` when values provided for ICU, else registry default.
    """
    placeholders = sorted(extract_placeholders(text)) if fmt == "icu" else []
    coerced = coerce_preview_values(values)
    if fmt == "icu":
        use_filled = (mode == "filled") or (mode is None and bool(coerced))
        if use_filled:
            html = preview_icu_filled(text, locale, coerced)
        elif mode == "samples" or has_icu(text):
            html = preview_icu(text, locale, base_values=coerced)
        else:
            html = preview_icu_filled(text, locale, coerced) if placeholders else ""
    else:
        html = preview(text, locale, fmt)
    return {
        "html": html,
        "placeholders": placeholders,
        "source": text,
        "format": fmt,
    }
