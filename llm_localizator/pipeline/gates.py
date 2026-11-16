"""Hard gates vs soft semantic dimensions (audit A2).

Hard gates are deterministic accept/reject. Soft dimensions are advisory scores
(BT or LQS) and must not be treated as interchangeable confidence probabilities.
"""

from __future__ import annotations

from .candidates import accept_candidate

__all__ = [
    "SCORER_VERSION_BT",
    "SCORER_VERSION_LQS",
    "SOFT_DIMENSIONS_LQS",
    "hard_gates_ok",
    "scorer_version",
]

SCORER_VERSION_BT = "bt-1"
SCORER_VERSION_LQS = "lqs-1"

# LQS judge dimensions (see pipeline/judge.py). BT has no dimensional breakdown.
SOFT_DIMENSIONS_LQS: tuple[str, ...] = (
    "semantic",
    "info",
    "fluency",
    "terminology",
    "ui",
    "placeholders",
    "html",
    "length",
)


def hard_gates_ok(
    source: str,
    candidate: str | None,
    locale: str,
    glossary: dict,
    *,
    placeholder_mask: dict[str, str] | None = None,
    check_html: bool | None = None,
    standard=None,
) -> tuple[bool, str | None]:
    """True when structural / glossary / script / HTML gates pass."""
    text, reason = accept_candidate(
        source, candidate, locale, glossary,
        placeholder_mask=placeholder_mask, check_html=check_html,
        standard=standard,
    )
    if text is None:
        return False, reason
    return True, None


def scorer_version(scorer: str) -> str:
    """Version tag stored alongside scores for calibration (A2)."""
    if scorer == "lqs":
        return SCORER_VERSION_LQS
    if scorer == "heuristic":
        return "heuristic-1"
    return SCORER_VERSION_BT
