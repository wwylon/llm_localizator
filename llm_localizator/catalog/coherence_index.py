"""Catalogue coherence: same/similar English sources across keys (V30/V31).

Built once per validate/translate locale pass. Exact groups use ``src_hash``;
fuzzy neighbours use :func:`semantic_overlap` (n-gram by default).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..catalog.embeddings import cosine, embed
from ..core.hash import src_hash
from ..core.icu import extract_placeholders

__all__ = [
    "CoherenceHit",
    "CoherenceIndex",
    "DEFAULT_NEAR_OVERLAP",
    "DEFAULT_FUZZY_VALIDATE",
    "compatible_placeholders",
]

DEFAULT_NEAR_OVERLAP = 0.72
DEFAULT_FUZZY_VALIDATE = 0.85
DEFAULT_QUALITY_FLOOR = 0.80


@dataclass(frozen=True)
class CoherenceHit:
    namespace: str
    key: str
    source: str
    target: str
    score: float
    quality_ok: bool = True


def compatible_placeholders(source: str, example_source: str) -> bool:
    """Drop examples that introduce placeholders absent from *source*."""
    extra = extract_placeholders(example_source) - extract_placeholders(source)
    return not extra


class CoherenceIndex:
    """In-memory index of English sources → locale targets for one locale."""

    def __init__(self) -> None:
        # (ns, key) -> (en, target, quality_ok)
        self._rows: list[tuple[str, str, str, str, bool]] = []
        self._by_hash: dict[str, list[tuple[str, str, str, str, bool]]] = {}
        # One vector per distinct text: pair scans reuse it instead of
        # re-embedding both sides on every comparison.
        self._vecs: dict[str, object] = {}
        #: Exact-source groups skipped as too large, as ``(namespace.key, size)``.
        self.skipped_groups: list[tuple[str, int]] = []
        #: True when :meth:`fuzzy_conflicts` declined to scan an oversized index.
        self.fuzzy_skipped = False

    _VEC_CAP = 4096

    def _vec(self, text: str):
        vec = self._vecs.get(text)
        if vec is None:
            if len(self._vecs) >= self._VEC_CAP:
                # Drop an arbitrary oldest insertion; dict preserves order.
                self._vecs.pop(next(iter(self._vecs)))
            vec = self._vecs[text] = embed(text)
        return vec

    def _overlap(self, a: str, b: str) -> float:
        return cosine(self._vec(a), self._vec(b))

    def build(
        self,
        entries: list[tuple[str, str, str, str]],
        *,
        quality_ok: Callable[[str, str], bool] | None = None,
    ) -> None:
        """Load ``(namespace, key, english, target)`` rows.

        *quality_ok(ns, key)* marks whether a target is safe to use as a
        prompt example (verified / high score / human).
        """
        self._rows = []
        self._by_hash = {}
        self._vecs = {}
        self.skipped_groups = []
        self.fuzzy_skipped = False
        q = quality_ok or (lambda _ns, _key: True)
        for ns, key, en, target in entries:
            if not isinstance(en, str) or not en.strip():
                continue
            if not isinstance(target, str):
                continue
            ok = bool(q(ns, key))
            row = (ns, key, en, target, ok)
            self._rows.append(row)
            h = src_hash(en)
            self._by_hash.setdefault(h, []).append(row)

    def exact_siblings(
        self,
        namespace: str,
        key: str,
        source: str,
        *,
        quality_only: bool = False,
    ) -> list[CoherenceHit]:
        """Other keys with the same English source text."""
        rows = self._by_hash.get(src_hash(source), [])
        hits: list[CoherenceHit] = []
        for ns, k, en, target, ok in rows:
            if ns == namespace and k == key:
                continue
            if quality_only and not ok:
                continue
            hits.append(CoherenceHit(
                namespace=ns, key=k, source=en, target=target,
                score=1.0, quality_ok=ok,
            ))
        return hits

    def similar_sources(
        self,
        source: str,
        *,
        exclude: tuple[str, str] | None = None,
        min_overlap: float = DEFAULT_NEAR_OVERLAP,
        limit: int = 5,
        quality_only: bool = True,
        semantic: bool = True,
    ) -> list[CoherenceHit]:
        """Top-*limit* catalogue neighbours by English similarity."""
        if not semantic or not source.strip():
            return []
        scored: list[CoherenceHit] = []
        for ns, k, en, target, ok in self._rows:
            if exclude and (ns, k) == exclude:
                continue
            if quality_only and not ok:
                continue
            if en.strip() == source.strip():
                continue  # exact handled separately
            if not compatible_placeholders(source, en):
                continue
            overlap = self._overlap(source, en)
            if overlap < min_overlap:
                continue
            scored.append(CoherenceHit(
                namespace=ns, key=k, source=en, target=target,
                score=overlap, quality_ok=ok,
            ))
        scored.sort(key=lambda h: (-h.score, -len(h.source)))
        return scored[: max(0, limit)]

    def exact_conflicts(
        self,
        *,
        skip_keys: set[str] | None = None,
        different_context: Callable[[str, str, str, str], bool] | None = None,
        max_group: int | None = None,
    ) -> list[tuple[CoherenceHit, CoherenceHit]]:
        """Pairs of keys with same English but different targets (V30).

        A group of more than ``max_group`` keys is skipped (pairs grow with its
        square) and listed in :attr:`skipped_groups`; other groups still run.
        """
        self.skipped_groups = []
        skip = skip_keys or set()
        pairs: list[tuple[CoherenceHit, CoherenceHit]] = []
        for rows in self._by_hash.values():
            if len(rows) < 2:
                continue
            if max_group is not None and len(rows) > max_group:
                self.skipped_groups.append((f"{rows[0][0]}.{rows[0][1]}", len(rows)))
                continue
            # Compare each pair once.
            for i in range(len(rows)):
                ns_a, key_a, en_a, tgt_a, ok_a = rows[i]
                if key_a in skip:
                    continue
                for j in range(i + 1, len(rows)):
                    ns_b, key_b, en_b, tgt_b, ok_b = rows[j]
                    if key_b in skip:
                        continue
                    if tgt_a.strip() == tgt_b.strip():
                        continue
                    if different_context and different_context(ns_a, key_a, ns_b, key_b):
                        continue
                    pairs.append((
                        CoherenceHit(ns_a, key_a, en_a, tgt_a, 1.0, ok_a),
                        CoherenceHit(ns_b, key_b, en_b, tgt_b, 1.0, ok_b),
                    ))
        return pairs

    def fuzzy_conflicts(
        self,
        *,
        min_overlap: float = DEFAULT_FUZZY_VALIDATE,
        skip_keys: set[str] | None = None,
        max_rows: int | None = None,
    ) -> list[tuple[CoherenceHit, CoherenceHit, float]]:
        """Pairs with similar English but divergent targets (V31).

        Only reports when neither target is a substring of the other (shared
        phrasing is OK). The scan is quadratic, so an index above ``max_rows``
        is not scanned (:attr:`fuzzy_skipped`); exact V30 is unaffected.
        """
        self.fuzzy_skipped = False
        if max_rows is not None and len(self._rows) > max_rows:
            self.fuzzy_skipped = True
            return []
        skip = skip_keys or set()
        pairs: list[tuple[CoherenceHit, CoherenceHit, float]] = []
        seen: set[frozenset[tuple[str, str]]] = set()
        for i, (ns_a, key_a, en_a, tgt_a, ok_a) in enumerate(self._rows):
            if key_a in skip:
                continue
            for ns_b, key_b, en_b, tgt_b, ok_b in self._rows[i + 1 :]:
                if key_b in skip:
                    continue
                if ns_a != ns_b:
                    continue
                if en_a.strip() == en_b.strip():
                    continue
                if not compatible_placeholders(en_a, en_b):
                    continue
                overlap = self._overlap(en_a, en_b)
                if overlap < min_overlap:
                    continue
                ta, tb = tgt_a.strip(), tgt_b.strip()
                if not ta or not tb or ta == tb:
                    continue
                if ta in tb or tb in ta:
                    continue
                keyset = frozenset({(ns_a, key_a), (ns_b, key_b)})
                if keyset in seen:
                    continue
                seen.add(keyset)
                pairs.append((
                    CoherenceHit(ns_a, key_a, en_a, tgt_a, overlap, ok_a),
                    CoherenceHit(ns_b, key_b, en_b, tgt_b, overlap, ok_b),
                    overlap,
                ))
        return pairs
