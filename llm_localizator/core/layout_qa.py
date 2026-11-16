"""Deterministic layout / UI-fit checks (audit A3 screenshot layout QA).

No browser automation. Uses max_chars, expansion bands, script/direction, and
optional PNG IHDR dimensions when a screenshot file is present.
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
    "png_dimensions",
]


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


def check_layout(
    source: str,
    translated: str,
    locale: str,
    *,
    max_chars: int | None = None,
    screenshot: Path | None = None,
    min_screenshot_width: int = 40,
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
