"""Feedback loop (ADR-52): a substantial human correction becomes a few-shot example."""

from __future__ import annotations

from difflib import SequenceMatcher

from ..projects import ProjectConfig
from ..projects.context import append_example, load_examples

__all__ = ["MAX_SOURCE_CHARS", "MIN_CHANGE", "MIN_SCORE", "learn_from_edit"]

MAX_SOURCE_CHARS = 60
MIN_CHANGE = 0.20
MIN_SCORE = 0.60


def learn_from_edit(
    cfg: ProjectConfig,
    *,
    locale: str,
    source: str,
    previous: object,
    text: str,
    score: float | None,
) -> bool:
    """Append ``(source, text)`` to ``[prompt] examples_file`` when the edit is a real correction.

    Short sources only, at least 20% of the characters changed, a score of 0.6 or more (the
    edit itself may be wrong), and no example for this source yet. Returns True when written.
    """
    path = getattr(cfg, "examples_file", None)
    if not path or not isinstance(previous, str) or not previous.strip() or previous == text:
        return False
    if len(source) > MAX_SOURCE_CHARS or score is None or score < MIN_SCORE:
        return False
    if 1.0 - SequenceMatcher(None, previous, text).ratio() < MIN_CHANGE:
        return False
    if any(src == source for src, _tgt in load_examples(path).get(locale, [])):
        return False
    return append_example(path, locale, source, text)
