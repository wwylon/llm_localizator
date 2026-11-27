"""Per-locale quality score sidecar (avoids changing ADR-7 state shape)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from .state import now_iso, split_operator_key, state_key
from ._locale_json_store import LocaleJsonStore

__all__ = ["ScoreStore", "quality_score_of", "score_matches_text", "text_sha"]


def text_sha(text: str) -> str:
    """Short digest stored in place of the scored text (keeps the sidecar small)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def score_matches_text(row: dict, text: str) -> bool:
    """True when ``row`` was scored for ``text``. Legacy rows carry the text itself."""
    sha = row.get("text_sha")
    if sha:
        return sha == text_sha(text)
    return (row.get("text") or "") == text


def quality_score_of(entry: dict | None) -> float | None:
    """Parse ``quality_score`` tolerantly; malformed rows return ``None``."""
    if not isinstance(entry, dict):
        return None
    raw = entry.get("quality_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class ScoreStore(LocaleJsonStore):
    def get(self, locale: str, namespace: str, key: str) -> dict | None:
        return self.load(locale).get(state_key(namespace, key))

    def record(
        self,
        locale: str,
        namespace: str,
        key: str,
        *,
        score: float,
        signals: list[str],
        text: str,
        dimensions: dict[str, float] | None = None,
        scorer: str | None = None,
        issues: list[dict[str, str]] | None = None,
    ) -> None:
        entry: dict = {
            "quality_score": score,
            "signals": signals,
            "scored_at": now_iso(),
            "text_sha": text_sha(text),
        }
        if dimensions:
            entry["dimensions"] = dimensions
        if issues:
            entry["issues"] = issues
        if scorer:
            entry["scorer"] = scorer
            entry["scorer_version"] = (
                "lqs-2" if scorer == "lqs"
                else "heuristic-1" if scorer == "heuristic"
                else "bt-1"
            )
        self.load(locale)[state_key(namespace, key)] = entry

    def forget(self, locale: str, namespace: str, key: str) -> None:
        """Drop a score so the key shows as unscored. No-op when absent."""
        self.load(locale).pop(state_key(namespace, key), None)

    def low_score_keys(
        self,
        locale: str,
        threshold: float,
        namespaces: set[str] | None = None,
    ) -> list[tuple[str, str, float]]:
        """Return ``(namespace, key, score)`` below threshold.

        ``namespaces`` is forwarded to :func:`split_operator_key` so that
        slash-namespaces and keys containing dots are parsed correctly.
        """
        out: list[tuple[str, str, float]] = []
        for sk, entry in self.load(locale).items():
            score = quality_score_of(entry if isinstance(entry, dict) else None)
            if score is None:
                continue
            if score >= threshold:
                continue
            ns, key = split_operator_key(sk, namespaces)
            out.append((ns, key, score))
        out.sort(key=lambda row: row[2])
        return out

    def top_peers(
        self,
        locale: str,
        namespace: str,
        *,
        min_score: float = 0.85,
        limit: int = 5,
        catalog_source: dict[str, str] | None = None,
        catalog_target: dict[str, str] | None = None,
        screen_of: Callable[[str], str | None] | None = None,
        screen: str | None = None,
        exclude_key: str | None = None,
    ) -> list[tuple[str, str]]:
        """High-scoring (source, target) pairs for few-shot injection."""
        if not catalog_source or not catalog_target:
            return []
        scored: list[tuple[int, float, str, str]] = []
        table = self.load(locale)  # once: get() would stat the file per key
        for key, en in catalog_source.items():
            if key == exclude_key or not isinstance(en, str) or not en.strip():
                continue
            if screen_of and screen and screen_of(key) != screen:
                continue
            tgt = catalog_target.get(key)
            if not isinstance(tgt, str) or not tgt.strip():
                continue
            entry = table.get(state_key(namespace, key)) or {}
            score = quality_score_of(entry if isinstance(entry, dict) else None)
            if score is None or score < min_score:
                continue
            scored.append((len(en), score, en, tgt))
        scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
        return [(en, tgt) for _, _, en, tgt in scored[:limit]]
