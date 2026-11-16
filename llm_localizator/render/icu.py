"""Render an ICU message for sample parameters. Preview only; stored text stays."""

from __future__ import annotations

import html
from typing import Mapping

from ..core.icu import PLURAL_HEAD_RE, extract_placeholders, split_top_level_segments
from ..core.plural import plural_category, sample_numbers
from ..core.plurals import _arms

__all__ = [
    "render_message",
    "preview_icu",
    "preview_icu_filled",
    "coerce_preview_values",
    "has_icu",
]


def _format_n(n: int | float) -> str:
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)


def coerce_preview_values(raw: Mapping[str, object] | None) -> dict[str, object]:
    """Turn JSON sample fields into values ``render_message`` understands."""
    if not raw:
        return {}
    out: dict[str, object] = {}
    for key, value in raw.items():
        name = str(key)
        if isinstance(value, bool) or value is None:
            out[name] = value
            continue
        if isinstance(value, (int, float)):
            out[name] = value
            continue
        text = str(value).strip()
        if text == "":
            continue
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            out[name] = int(text)
            continue
        try:
            out[name] = float(text) if "." in text else text
        except ValueError:
            out[name] = text
    return out


def render_message(text: str, locale: str, values: dict[str, object]) -> str:
    """Substitute placeholders and pick one plural/select arm."""
    parts: list[str] = []
    for kind, seg in split_top_level_segments(text):
        if kind == "text":
            parts.append(seg)
            continue
        inner = seg[1:-1]
        head = PLURAL_HEAD_RE.match(inner)
        if not head:
            name = inner.strip()
            parts.append(str(values[name]) if name in values else seg)
            continue
        var = head.group(1)
        keyword = head.group(2)
        arms = dict(_arms(inner[head.end() :]))
        if keyword == "select":
            choice = str(values.get(var, "other"))
            chosen = arms.get(choice) or arms.get("other") or ""
            parts.append(render_message(chosen, locale, values))
            continue
        raw = values.get(var, 1)
        number: int | float = raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 1
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
                number = int(stripped)
            else:
                try:
                    number = float(stripped)
                except ValueError:
                    number = 1
        exact = None
        if isinstance(number, int) or (isinstance(number, float) and number.is_integer()):
            exact = f"={int(number)}"
        if exact and exact in arms:
            chosen = arms[exact]
        else:
            category = plural_category(locale, number)
            chosen = arms.get(category) or arms.get("other") or ""
        filled = chosen.replace("#", _format_n(number))
        parts.append(render_message(filled, locale, {**values, var: number}))
    return "".join(parts)


def has_icu(text: str) -> bool:
    return any(kind == "icu" and PLURAL_HEAD_RE.match(seg[1:-1]) for kind, seg in split_top_level_segments(text))


def preview_icu_filled(text: str, locale: str, values: Mapping[str, object] | None = None) -> str:
    """One rendered sample with *values* filled; safe HTML paragraph."""
    if not text:
        return ""
    filled = render_message(text, locale, coerce_preview_values(values))
    return f'<p class="icu-preview-live">{html.escape(filled)}</p>'


def preview_icu(
    text: str,
    locale: str,
    *,
    base_values: Mapping[str, object] | None = None,
) -> str:
    """Safe HTML showing how *text* reads for sample numbers or select options.

    Bare placeholders from *base_values* are substituted into every sample row
    (so ``{mean}`` is not left literal while ``count`` is sampled).
    """
    if not text:
        return ""
    base = coerce_preview_values(base_values)
    if not has_icu(text):
        if extract_placeholders(text) and base:
            return preview_icu_filled(text, locale, base)
        return ""
    rows: list[str] = []
    for kind, seg in split_top_level_segments(text):
        if kind != "icu":
            continue
        inner = seg[1:-1]
        head = PLURAL_HEAD_RE.match(inner)
        if not head:
            continue
        var = head.group(1)
        keyword = head.group(2)
        arms = _arms(inner[head.end() :])
        if keyword == "select":
            for name, _body in arms:
                rendered = render_message(text, locale, {**base, var: name})
                rows.append(
                    f"<li><code>{html.escape(var)}={html.escape(name)}</code> "
                    f"{html.escape(rendered)}</li>"
                )
            continue
        samples: list[int | float] = []
        for selector, _body in arms:
            if selector.startswith("=") and selector[1:].isdigit():
                samples.append(int(selector[1:]))
        for n in sample_numbers(locale):
            if n not in samples:
                samples.append(n)
        for n in samples:
            category = plural_category(locale, n)
            rendered = render_message(text, locale, {**base, var: n})
            rows.append(
                f"<li><code>{html.escape(var)}={html.escape(_format_n(n))}</code> "
                f"{html.escape(category)}: {html.escape(rendered)}</li>"
            )
        break
    if not rows:
        return ""
    return '<ul class="icu-preview">' + "".join(rows) + "</ul>"
