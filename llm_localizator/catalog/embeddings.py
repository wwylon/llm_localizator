"""Optional semantic near-match for TM (ADR-22 follow-on).

Default: character n-gram hashing (no deps). Optional backend via
``pip install 'llm_localizator[embeddings]'`` (sentence-transformers) when
``LLM_LOCALIZE_EMBEDDINGS=1`` or ``use_transformer=True``.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter

__all__ = [
    "embed",
    "cosine",
    "semantic_overlap",
    "embeddings_available",
]

_TOKEN_RE = re.compile(r"\S", re.UNICODE)
_transformer = None
_transformer_failed = False


def embeddings_available() -> bool:
    """True when the optional sentence-transformers backend can load."""
    global _transformer, _transformer_failed
    if _transformer is not None:
        return True
    if _transformer_failed:
        return False
    if os.environ.get("LLM_LOCALIZE_EMBEDDINGS", "").strip() not in {"1", "true", "yes"}:
        return False
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _transformer = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return True
    except Exception:
        _transformer_failed = True
        return False


def _ngram_vector(text: str, n: int = 3) -> dict[str, float]:
    s = f" {(text or '').lower()} "
    counts: Counter[str] = Counter()
    if len(s) < n:
        counts[s] = 1.0
    else:
        for i in range(len(s) - n + 1):
            counts[s[i : i + n]] += 1
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


_EMBED_CACHE: dict[tuple[str, bool], list[float] | dict[str, float]] = {}
_EMBED_CACHE_MAX = 4096


def embed(text: str, *, use_transformer: bool | None = None) -> list[float] | dict[str, float]:
    """Return a vector for *text* (dense list or sparse n-gram dict)."""
    want = use_transformer if use_transformer is not None else embeddings_available()
    key = (text or "", bool(want and embeddings_available()))
    hit = _EMBED_CACHE.get(key)
    if hit is not None:
        return hit
    if want and embeddings_available() and _transformer is not None:
        vec = _transformer.encode([text or ""], normalize_embeddings=True)[0]
        out: list[float] | dict[str, float] = [float(x) for x in vec]
    else:
        out = _ngram_vector(text)
    if len(_EMBED_CACHE) >= _EMBED_CACHE_MAX:
        _EMBED_CACHE.clear()
    _EMBED_CACHE[key] = out
    return out


def cosine(a: list[float] | dict[str, float], b: list[float] | dict[str, float]) -> float:
    if isinstance(a, dict) and isinstance(b, dict):
        if not a or not b:
            return 0.0
        keys = set(a) | set(b)
        return sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    if isinstance(a, list) and isinstance(b, list):
        n = min(len(a), len(b))
        if n == 0:
            return 0.0
        return sum(a[i] * b[i] for i in range(n))
    return 0.0


def semantic_overlap(a: str, b: str, *, use_transformer: bool | None = None) -> float:
    """Cosine similarity in embedding space (n-gram or transformer)."""
    return cosine(embed(a, use_transformer=use_transformer), embed(b, use_transformer=use_transformer))
