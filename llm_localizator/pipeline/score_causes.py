"""Why a score is low: weakest dimension and signal per scored key (C-005).

Reads only what the score sidecar stores (dimensions, signals). The model and
prompt rule that produced a text are not recorded, so no attribution to them is
made; keys scored without dimensions are reported as such, not guessed at.
"""

from __future__ import annotations

from collections import Counter

__all__ = ["DIMENSION_OK", "explain_score", "top_causes"]

DIMENSION_OK = 0.9


def explain_score(entry: dict) -> dict:
    """``{"cause", "weak", "signal"}`` for one score-sidecar row.

    ``weak`` lists ``(dimension, value)`` below :data:`DIMENSION_OK`, worst
    first; ``cause`` is the worst one, or ``"no-dimensions"`` when the row has
    none (heuristic scores from older runs).
    """
    raw = entry.get("dimensions")
    dims = {
        str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float))
    } if isinstance(raw, dict) else {}
    weak = sorted(((k, v) for k, v in dims.items() if v < DIMENSION_OK), key=lambda kv: (kv[1], kv[0]))
    signals = entry.get("signals") or []
    signal = str(signals[0]) if isinstance(signals, list) and signals else ""
    cause = weak[0][0] if weak else ("no-dimensions" if not dims else "none-below-threshold")
    return {"cause": cause, "weak": weak, "signal": signal}


def top_causes(rows: list[dict]) -> list[tuple[str, int]]:
    """Count ``cause`` over :func:`explain_score` results, most common first."""
    counts = Counter(r["cause"] for r in rows)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
