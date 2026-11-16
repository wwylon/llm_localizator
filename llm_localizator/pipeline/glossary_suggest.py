"""Suggest glossary terms from translation memory (ADR-52).

A term is suggested when a short target-side phrase and a short source-side phrase keep
turning up in the same TM entries. The pairing is a Dice coefficient over entries, so it is
a suggestion for a person to review, never something written into the glossary.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

__all__ = ["Suggestion", "suggest_terms"]

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOP = frozenset(
    "a an the of to and or in on for with from by at as is are was were be "
    "been being this that these those it its not no you your".split()
)


@dataclass(frozen=True)
class Suggestion:
    term: str
    translation: str
    count: int
    dice: float


def _grams(text: str, max_words: int) -> set[str]:
    words = [word.casefold() for word in _WORD.findall(text)]
    out: set[str] = set()
    for size in range(1, max_words + 1):
        for index in range(len(words) - size + 1):
            out.add(" ".join(words[index:index + size]))
    return out


def _worth_keeping_source(gram: str) -> bool:
    words = gram.split()
    return words[0] not in _STOP and words[-1] not in _STOP and len(gram) > 2


def suggest_terms(
    pairs: list[tuple[str, str]],
    *,
    known: set[str] | None = None,
    min_occurrences: int = 5,
    max_words: int = 3,
    min_dice: float = 0.6,
) -> list[Suggestion]:
    """``pairs`` are ``(source, translation)``; returns the best translation per source term."""
    known = {term.casefold() for term in (known or set())}
    per_entry: list[tuple[set[str], set[str]]] = []
    src_count: dict[str, int] = defaultdict(int)
    tgt_count: dict[str, int] = defaultdict(int)
    for source, target in pairs:
        src, tgt = _grams(source, max_words), _grams(target, max_words)
        per_entry.append((src, tgt))
        for gram in src:
            src_count[gram] += 1
        for gram in tgt:
            tgt_count[gram] += 1

    src_ok = {
        g for g, n in src_count.items() if n >= min_occurrences and _worth_keeping_source(g)
    }
    tgt_ok = {g for g, n in tgt_count.items() if n >= min_occurrences}
    together: dict[tuple[str, str], int] = defaultdict(int)
    for src, tgt in per_entry:
        for s in src & src_ok:
            for t in tgt & tgt_ok:
                together[(s, t)] += 1

    best: dict[str, Suggestion] = {}
    for (s, t), count in together.items():
        if count < min_occurrences or s in known or s == t:
            continue
        dice = 2 * count / (src_count[s] + tgt_count[t])
        if dice < min_dice:
            continue
        current = best.get(s)
        # Prefer the higher Dice; on a tie the shorter phrase, so "zapowiedź" beats "zapowiedź na".
        if current is None or (dice, -len(t)) > (current.dice, -len(current.translation)):
            best[s] = Suggestion(s, t, count, round(dice, 3))
    # A longer source phrase that only repeats a shorter suggested one adds nothing.
    kept = [
        item for item in best.values()
        if not any(
            other is not item and other.term in item.term.split()
            and other.translation == item.translation
            for other in best.values()
        )
    ]
    return sorted(kept, key=lambda item: (-item.count, -item.dice, item.term))
