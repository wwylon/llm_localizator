"""When a scored candidate may replace what the catalogue already has (plan Part C, C2 / E8).

Two rules, applied after scoring and before the write:

* **Write floor.** A candidate scoring below ``[quality] write_floor`` is not written;
  "Wygłodź" (0.53) reached the catalogue as a button label because a low score only
  raised a flag. Default: 0.5 on the judge (LQS) scale, 0.35 on back-translation.
* **Never worse.** A rerun of a key whose source has not changed (``--force``, a plural
  or grammar rerun) keeps the current text unless the new candidate is an improvement
  by :func:`~llm_localizator.core.quality.is_improvement`, the same rule ``improve`` uses.
  Scores are compared only on the same scale and only when the stored score belongs to
  the text that is in the catalogue now.

A held candidate goes to the draft store (ADR-91) so a reviewer can still take it.
"""

from __future__ import annotations

from ..catalog.drafts import DraftStore
from ..catalog.scores import quality_score_of, score_matches_text
from ..catalog.state import is_translated_value
from ..core.hash import src_hash
from ..core.quality import is_improvement

__all__ = ["write_floor", "hold_reason", "hold_as_draft"]

_DEFAULT_FLOOR = {"lqs": 0.5, "bt": 0.35}


def write_floor(cfg, scorer: str | None) -> float:
    explicit = getattr(cfg, "write_floor", None)
    if explicit is not None:
        return float(explicit)
    return _DEFAULT_FLOOR.get(scorer or "bt", 0.0)


def hold_reason(
    cfg, *, source: str, previous: str | None, entry: dict | None,
    old_score: dict | None, text: str, quality,
) -> str | None:
    """Why ``text`` must not replace ``previous``; ``None`` when the write may go ahead."""
    scorer = quality.scorer or "bt"
    if scorer != "heuristic":
        floor = write_floor(cfg, scorer)
        if quality.score < floor:
            return f"score {quality.score:.2f} is below the write floor {floor:.2f}"
    if not is_translated_value(source, previous) or previous == text:
        return None
    if entry is None or entry.get("src_sha") != src_hash(source):
        return None  # the source changed: the current text is stale, not a benchmark
    if not old_score or not score_matches_text(old_score, previous or ""):
        return None
    if (old_score.get("scorer") or "bt") != scorer:
        return None
    old = quality_score_of(old_score)
    if old is None:
        return None
    if is_improvement(quality.score, quality.dimensions, old, old_score.get("dimensions")):
        return None
    return f"not better than the current text ({quality.score:.2f} vs {old:.2f})"


def hold_as_draft(cfg, *, locale: str, namespace: str, key: str, source: str,
                  text: str, score: float, model: str, reason: str) -> None:
    """Keep the held candidate where a reviewer can accept it (ADR-91)."""
    DraftStore.for_project(cfg).put(
        locale, namespace, key, text=text, score=score, model=model or "",
        source=source, by="translate", reason=reason,
    )
