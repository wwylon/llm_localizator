"""Raw Unicode range table for supported writing systems.

No imports — imported by both ``core.scripts`` and ``core.locales.base``
so neither creates a dependency on the other.
"""

from __future__ import annotations

SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "latin": ((0x0041, 0x024F), (0x1E00, 0x1EFF)),
    "cyrillic": ((0x0400, 0x04FF),),
    "greek": ((0x0370, 0x03FF),),
    "arabic": ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF)),
    "hebrew": ((0x0590, 0x05FF),),
    # Hangul Syllables so Korean is first-class under the cjk profile.
    "cjk": (
        (0x3040, 0x30FF),
        (0x3400, 0x9FFF),
        (0xF900, 0xFAFF),
        (0xAC00, 0xD7AF),
    ),
    "thai": ((0x0E00, 0x0E7F),),
    "devanagari": ((0x0900, 0x097F),),
    "georgian": ((0x10A0, 0x10FF), (0x2D00, 0x2D2F)),
    "armenian": ((0x0530, 0x058F),),
    "bengali": ((0x0980, 0x09FF),),
    "gurmukhi": ((0x0A00, 0x0A7F),),
    "gujarati": ((0x0A80, 0x0AFF),),
    "tamil": ((0x0B80, 0x0BFF),),
    "telugu": ((0x0C00, 0x0C7F),),
    "kannada": ((0x0C80, 0x0CFF),),
    "malayalam": ((0x0D00, 0x0D7F),),
    "sinhala": ((0x0D80, 0x0DFF),),
    "lao": ((0x0E80, 0x0EFF),),
    "tibetan": ((0x0F00, 0x0FFF),),
    "myanmar": ((0x1000, 0x109F),),
    "khmer": ((0x1780, 0x17FF), (0x19E0, 0x19FF)),
    "ethiopic": ((0x1200, 0x137F),),
    "thaana": ((0x0780, 0x07BF),),
}
