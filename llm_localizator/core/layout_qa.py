"""Deterministic layout / UI-fit checks (audit A3 screenshot layout QA).

No browser automation. Uses max_chars, expansion bands, script/direction,
optional PNG IHDR dimensions, and measured pixel budgets (ADR-159 V29).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .locales import profile
from .locale_policy import LocalePolicy
from .script_checks import check_script_issues
from .validate import check_max_chars

__all__ = [
    "LayoutIssue",
    "check_layout",
    "estimate_text_width_px",
    "locale_width_factor",
    "png_dimensions",
]

#: Soft overshoot before V29 fires (measured boxes are approximate).
_WIDTH_SLACK = 1.05


@dataclass(frozen=True)
class LayoutIssue:
    code: str
    message: str


def png_dimensions(path: Path) -> tuple[int, int] | None:
    """Read width/height from a PNG IHDR without third-party deps."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    # IHDR: length(4) + type(4) + width(4) + height(4)
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        return None
    return width, height


def locale_width_factor(locale: str) -> float:
    """Relative average glyph width vs Latin UI fonts (coarse, hermetic)."""
    policy = LocalePolicy.for_locale(locale)
    base = (locale or "").split("-")[0].lower()
    if policy.direction == "rtl":
        return 1.05
    if base in {"zh", "ja", "ko"}:
        return 1.35
    if base in {"th", "lo", "km", "my"}:
        return 1.15
    return 1.0


def estimate_text_width_px(
    text: str,
    *,
    font_size_px: float = 14.0,
    locale: str = "en",
) -> float:
    """Char-count × font size × locale factor (no shaping library)."""
    n = len(text or "")
    if n <= 0:
        return 0.0
    size = font_size_px if font_size_px and font_size_px > 0 else 14.0
    # ~0.55em average for Latin UI; locale_width_factor scales CJK/RTL.
    return n * size * 0.55 * locale_width_factor(locale)


def check_layout(
    source: str,
    translated: str,
    locale: str,
    *,
    max_chars: int | None = None,
    screenshot: Path | None = None,
    min_screenshot_width: int = 40,
    max_width_px: float | None = None,
    font_size_px: float | None = None,
) -> list[LayoutIssue]:
    """Return layout/UI-fit issues (empty = ok)."""
    issues: list[LayoutIssue] = []
    policy = LocalePolicy.for_locale(locale)

    over = check_max_chars(translated, max_chars)
    if over:
        issues.append(LayoutIssue("max_chars", over))

    band = profile(locale).expansion_band
    if band and source.strip():
        ratio = len(translated) / max(len(source), 1)
        lo, hi = band
        if ratio > hi * 1.15:
            issues.append(LayoutIssue(
                "expansion",
                f"translation {ratio:.2f}× source exceeds locale band {lo:.2f}–{hi:.2f}",
            ))

    for issue in check_script_issues(source, translated, locale):
        code = "script"
        if "latin-only" in issue:
            code = "rtl_latin_only" if policy.direction == "rtl" else "latin_only"
        elif "latin" in issue:
            code = "latin_not_in_source"
        issues.append(LayoutIssue(code, issue))

    if max_width_px is not None:
        try:
            budget = float(max_width_px)
        except (TypeError, ValueError):
            budget = 0.0
        if budget > 0:
            fs = float(font_size_px) if font_size_px else 14.0
            estimated = estimate_text_width_px(
                translated, font_size_px=fs if fs > 0 else 14.0, locale=locale,
            )
            if estimated > budget * _WIDTH_SLACK:
                approx_chars = max(1, int(budget / (0.55 * (fs if fs > 0 else 14.0) * locale_width_factor(locale))))
                issues.append(LayoutIssue(
                    "V29",
                    f"too_wide: ~{estimated:.0f}px estimated > {budget:.0f}px budget "
                    f"(~{approx_chars} chars at {fs:.0f}px)",
                ))

    if screenshot is not None:
        dims = png_dimensions(screenshot)
        if dims is None:
            issues.append(LayoutIssue(
                "screenshot_unreadable",
                f"cannot read PNG dimensions: {screenshot}",
            ))
        else:
            width, height = dims
            if width < min_screenshot_width or height < 8:
                issues.append(LayoutIssue(
                    "screenshot_tiny",
                    f"screenshot {width}×{height} is too small for UI review",
                ))
            # Heuristic: very long text vs narrow screenshot crop.
            if max_chars is None and width > 0 and len(translated) > width // 4:
                issues.append(LayoutIssue(
                    "screenshot_crowding",
                    f"text length {len(translated)} may crowd {width}px-wide crop",
                ))

    return issues
