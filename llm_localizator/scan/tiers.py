"""How far to trust the scanner for each language: the support tier, with the evidence behind it.

Tiers (see docs/scanners.md):

* ``supported``: measured on at least three held-out third-party projects with recall >= 0.60 and
  precision >= 0.70 at high+medium confidence, outnumbering the held-out projects below that bar. Demoted when the
  projects below the bar outnumber those at it. Evidence per language slice: ``experiments/scanner_bench/TIER_REVIEW.md``
  (``tier_review.py``).
* ``basic``: runs, with an idiom-aware sink table or the shared literal detector, but not (yet) measured to that bar.

Languages with no scanner at all are reported separately as "NOT scanned" (``base.count_unsupported``).
Update this table only from ``experiments/real_world_verify/SCANNER_REPORT.md``; the drift test compares it with the docs.
"""

from __future__ import annotations

from collections import Counter

from ..core.languages import language_for_suffix
from .base import scanner_skips, walk_tree

__all__ = ["TIERS", "tier_for", "coverage_summary"]

#: language id -> tier. Anything registered but absent here is ``basic``.
TIERS: dict[str, str] = {
    "javascript": "supported",
    "tsx": "supported",
    "html": "supported",
    "vue": "supported",
    "svelte": "supported",
    # Tier review 2026-11-12 (plan Part F, TIER_REVIEW.md: five held-out scorings, v37-v43, per language slice):
    # xmlui promoted (8 held-out projects at the bar, 1 below). Python demoted (0 at the bar, 10 below: its earlier
    # promotion rested on whole-project scores carried by Jinja templates, not on .py files). Dart demoted (1 at the bar,
    # 2 below). JavaScript (2/2), Vue (2/0) and Svelte (no held-out slice) keep their tier: nothing outnumbers them.
    "xmlui": "supported",
    # 2026-11-12, after held-out set B (v46): Godot scenes reach the bar in 3 held-out projects, 2 below.
    "godot": "supported",
    # 2026-11-14, tier review over pools A-F (TIER_REVIEW.md): astro promoted (5 held-out projects at the bar, 3 below);
    # typescript demoted (7 at the bar, 8 below; it was supported before, so it is simply absent here and reads basic).
    "astro": "supported",
}


def tier_for(lang_id: str) -> str:
    return TIERS.get(lang_id, "basic")


def coverage_summary(scanner) -> dict[str, dict]:
    """``{language id: {"files": n, "tier": tier}}`` for the files the scanner will read in this tree."""
    counts: Counter[str] = Counter()
    for files in walk_tree(scanner):
        for path in files:
            lang = language_for_suffix(path.suffix)
            # M2: files the scan skips (docs, tests, [scan] exclude) are not part of what it reads.
            if lang is not None and not scanner_skips(scanner, path):
                counts[lang.id] += 1
    return {lang: {"files": n, "tier": tier_for(lang)} for lang, n in counts.most_common()}
