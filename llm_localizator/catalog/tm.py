"""Translation memory: exact reuse + near-match few-shot (R-06 / ADR-22).

Stored under ``[prompt] tm_dir`` (default ``<data_root>/.llm-tm/``, ADR-112). Exact hits
skip the provider; near hits only seed examples. Embeddings postponed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..core.hash import src_hash
from ..core.quality import TOKEN_RE, strip_screaming_snake, token_overlap
from .io import append_text_line, atomic_write_text, rewrite_text_locked
from .provenance import normalize_provider
from .state import now_iso

__all__ = [
    "TMEntry",
    "ConcordanceHit",
    "TranslationMemory",
    "context_hash",
    "edit_similarity",
    "tm_near_sort_key",
    "DEFAULT_NEAR_OVERLAP",
    "DEFAULT_NEAR_LIMIT",
]

DEFAULT_NEAR_OVERLAP = 0.55
DEFAULT_NEAR_LIMIT = 3


def context_hash(context: str) -> str:
    """Fingerprint of translator context for TM exact keys."""
    return src_hash((context or "").strip())


def edit_similarity(a: str, b: str) -> float:
    """Levenshtein-based similarity in [0, 1]: ``1 - distance / max_len``."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / len(a)


@dataclass
class TMEntry:
    src_hash: str
    source: str
    context_hash: str
    locale: str
    text: str
    model: str
    provider: str | None = None
    quality_score: float | None = None
    verified: bool = False
    created_at: str = ""

    def to_json(self) -> str:
        payload = asdict(self)
        if payload.get("provider") is None:
            payload.pop("provider", None)
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_dict(cls, raw: dict) -> TMEntry | None:
        try:
            return cls(
                src_hash=str(raw["src_hash"]),
                source=str(raw["source"]),
                context_hash=str(raw.get("context_hash") or ""),
                locale=str(raw["locale"]),
                text=str(raw["text"]),
                model=str(raw.get("model") or ""),
                provider=raw.get("provider"),
                quality_score=(
                    float(raw["quality_score"])
                    if raw.get("quality_score") is not None
                    else None
                ),
                verified=bool(raw.get("verified", False)),
                created_at=str(raw.get("created_at") or ""),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class ConcordanceHit:
    entry: TMEntry
    score: float
    superseded: bool


def tm_near_sort_key(row: tuple[TMEntry, float]) -> tuple[int, float, float, int, str]:
    """Verified first, then higher overlap, then the better-scored translation."""
    entry, overlap = row
    quality = entry.quality_score if entry.quality_score is not None else 0.0
    # src_hash breaks remaining ties so posting-set iteration order does not matter.
    return (0 if entry.verified else 1, -overlap, -quality, -len(entry.source), entry.src_hash)


class TranslationMemory:
    """Append-only JSONL TM, one file per locale."""

    def __init__(
        self,
        directory: Path,
        *,
        shared: Path | list[Path] | tuple[Path, ...] | None = None,
        write_to: Path | None = None,
    ) -> None:
        self.dir = Path(directory)
        if isinstance(shared, (list, tuple)):
            self.shared_paths = [Path(p) for p in shared if p]
        else:
            self.shared_paths = [Path(shared)] if shared else []
        self.shared = self.shared_paths[0] if self.shared_paths else None
        self.write_to = Path(write_to) if write_to else None
        self._index: dict[str, dict[tuple[str, str], TMEntry]] = {}
        # locale → file mtime when ``_index[locale]`` was last loaded from disk
        self._index_mtime: dict[str, int] = {}
        # locale → (mtime_ns, token sets, postings, empty-token keys)
        self._near_cache: dict[str, tuple] = {}
        self._shared_tms: list[TranslationMemory] | None = None
        self._record_mtime: dict[str, int] = {}
        # Appends since last compact; rewrite when superseded rows pile up.
        self._append_counts: dict[str, int] = {}
        self._compact_every = 250

    def _shared_memories(self) -> list[TranslationMemory]:
        """Read-only memories in the configured order; earlier ones win (ADR-95)."""
        if self._shared_tms is None:
            self._shared_tms = [TranslationMemory(p) for p in self.shared_paths]
        return self._shared_tms

    def path_for(self, locale: str) -> Path:
        return self.dir / f"{locale}.jsonl"

    def _ensure_index(self, locale: str) -> dict[tuple[str, str], TMEntry]:
        path = self.path_for(locale)
        try:
            mtime = path.stat().st_mtime_ns if path.exists() else 0
        except OSError:
            mtime = 0
        if locale in self._index and self._index_mtime.get(locale) == mtime:
            return self._index[locale]
        by_key: dict[tuple[str, str], TMEntry] = {}
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        entry = TMEntry.from_dict(raw)
                        if entry is None:
                            continue
                        by_key[(entry.src_hash, entry.context_hash)] = entry
            except OSError:
                pass
        self._index[locale] = by_key
        self._index_mtime[locale] = mtime
        # External (or cold) reload — near postings must rebuild from the index.
        self._near_cache.pop(locale, None)
        return by_key

    def record(
        self,
        *,
        locale: str,
        source: str,
        text: str,
        model: str,
        context: str = "",
        provider: str | None = None,
        quality_score: float | None = None,
        verified: bool = False,
    ) -> TMEntry:
        entry = TMEntry(
            src_hash=src_hash(source),
            source=source,
            context_hash=context_hash(context),
            locale=locale,
            text=text,
            model=model,
            provider=normalize_provider(provider) if provider is not None else None,
            quality_score=quality_score,
            verified=verified,
            created_at=now_iso(),
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(locale)
        append_text_line(path, entry.to_json())
        # Prefer a single mtime per bulk-record burst (translate flush).
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        else:
            self._record_mtime[locale] = mtime
        # In-place update so a warm near-cache is not discarded (Wave C).
        if locale in self._index:
            self._index[locale][(entry.src_hash, entry.context_hash)] = entry
            if mtime is not None:
                self._index_mtime[locale] = mtime
        else:
            self._ensure_index(locale)
        self._note_recorded(locale, entry, path, mtime=mtime)
        count = self._append_counts.get(locale, 0) + 1
        self._append_counts[locale] = count
        if count >= self._compact_every:
            self._append_counts[locale] = 0
            try:
                self.compact(locale)
            except OSError:
                pass
        return entry

    def _note_recorded(
        self,
        locale: str,
        entry: TMEntry,
        path: Path,
        *,
        mtime: int | None = None,
    ) -> None:
        """Keep the near-match postings warm so the next ``near`` does not rebuild."""
        cached = self._near_cache.get(locale)
        if cached is None:
            return
        if mtime is None:
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                self._near_cache.pop(locale, None)
                return
        _mtime, token_sets, postings, empty = cached
        key = (entry.src_hash, entry.context_hash)
        old = token_sets.pop(key, None)
        if old is not None:
            if not old:
                try:
                    empty.remove(key)
                except ValueError:
                    pass
            else:
                for token in old:
                    bucket = postings.get(token)
                    if not bucket:
                        continue
                    try:
                        bucket.remove(key)
                    except ValueError:
                        pass
                    if not bucket:
                        postings.pop(token, None)
        tokens = self._source_tokens(entry.source)
        token_sets[key] = tokens
        if not tokens:
            empty.append(key)
        else:
            for token in tokens:
                postings.setdefault(token, []).append(key)
        self._near_cache[locale] = (mtime, token_sets, postings, empty)

    def exact(
        self,
        locale: str,
        source: str,
        *,
        context: str = "",
    ) -> TMEntry | None:
        key = (src_hash(source), context_hash(context))
        hit = self._ensure_index(locale).get(key)
        if hit is not None:
            return hit
        for shared in self._shared_memories():
            hit = shared.exact(locale, source, context=context)
            if hit is not None:
                return hit
        return None

    def _source_tokens(self, text: str) -> frozenset[str]:
        return frozenset(
            token.lower() for token in TOKEN_RE.findall(strip_screaming_snake(text or ""))
        )

    def _lexical_index(self, locale: str):
        """Token postings for ``near``, rebuilt when the locale file mtime changes."""
        path = self.path_for(locale)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        cached = self._near_cache.get(locale)
        if cached is not None and cached[0] == mtime:
            return cached[1], cached[2], cached[3]
        entries = self._ensure_index(locale)
        token_sets: dict[tuple[str, str], frozenset[str]] = {}
        postings: dict[str, list[tuple[str, str]]] = {}
        empty: list[tuple[str, str]] = []
        for key, entry in entries.items():
            tokens = self._source_tokens(entry.source)
            token_sets[key] = tokens
            if not tokens:
                empty.append(key)
                continue
            for token in tokens:
                postings.setdefault(token, []).append(key)
        self._near_cache[locale] = (mtime, token_sets, postings, empty)
        return token_sets, postings, empty

    def near(
        self,
        locale: str,
        source: str,
        *,
        context: str = "",
        limit: int = DEFAULT_NEAR_LIMIT,
        min_overlap: float = DEFAULT_NEAR_OVERLAP,
        exclude_exact: bool = True,
        semantic: bool = False,
        metric: str = "tokens",
    ) -> list[tuple[TMEntry, float]]:
        """Near matches. Lexical by default; ``semantic=True`` uses embeddings.

        Verified (human-approved) entries sort ahead of machine hits.
        ``metric="edit"`` scores lexical candidates by character edit similarity
        (the CAT-tool "fuzzy %") instead of token overlap.
        Never auto-accept — callers only use hits as few-shot suggestions.
        """
        exact_key = (src_hash(source), context_hash(context))
        scored: list[tuple[TMEntry, float]] = []
        if semantic:
            from .embeddings import semantic_overlap

            for key, entry in self._ensure_index(locale).items():
                if exclude_exact and key == exact_key:
                    continue
                overlap = semantic_overlap(source, entry.source)
                if overlap >= min_overlap:
                    scored.append((entry, overlap))
        else:
            index = self._ensure_index(locale)
            _token_sets, postings, empty = self._lexical_index(locale)
            src_tokens = self._source_tokens(source)
            if min_overlap <= 0:
                # Full scan only when the caller disables the overlap floor.
                candidate_iter = index.items()
            elif not src_tokens:
                candidate_iter = (
                    (key, index[key]) for key in empty if key in index
                )
            else:
                candidate_keys: set[tuple[str, str]] = set()
                for token in src_tokens:
                    candidate_keys.update(postings.get(token, ()))
                candidate_iter = (
                    (key, index[key]) for key in candidate_keys if key in index
                )
            for key, entry in candidate_iter:
                if exclude_exact and key == exact_key:
                    continue
                overlap = (
                    edit_similarity(source, entry.source) if metric == "edit"
                    else token_overlap(source, entry.source)
                )
                if overlap >= min_overlap:
                    scored.append((entry, overlap))
        scored.sort(key=tm_near_sort_key)
        shared_tms = self._shared_memories()
        if shared_tms:
            seen = {(entry.src_hash, entry.context_hash) for entry, _overlap in scored}
            for shared in shared_tms:
                for entry, overlap in shared.near(
                    locale, source, context=context, limit=limit,
                    min_overlap=min_overlap, exclude_exact=exclude_exact,
                    semantic=semantic, metric=metric,
                ):
                    ident = (entry.src_hash, entry.context_hash)
                    if ident in seen:
                        continue
                    seen.add(ident)
                    scored.append((entry, overlap))
            scored.sort(key=tm_near_sort_key)
        return scored[: max(0, limit)]

    def rows(self, locale: str) -> list[tuple[TMEntry, bool]]:
        """Every JSONL line. The in-memory index keeps only the latest pair.

        A line is superseded when a later line has the same source and context.
        """
        path = self.path_for(locale)
        parsed: list[TMEntry] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entry = TMEntry.from_dict(raw)
                if entry is not None:
                    parsed.append(entry)
        latest: dict[tuple[str, str], int] = {}
        for index, entry in enumerate(parsed):
            latest[(entry.src_hash, entry.context_hash)] = index
        return [
            (entry, index != latest[(entry.src_hash, entry.context_hash)])
            for index, entry in enumerate(parsed)
        ]

    def concordance(
        self,
        locale: str,
        query: str,
        *,
        source: bool = True,
        target: bool = True,
        limit: int = 20,
    ) -> list[ConcordanceHit]:
        """Case-fold substring search. An empty query matches nothing."""
        needle = (query or "").casefold().strip()
        if not needle or limit <= 0 or (not source and not target):
            return []
        scored: list[ConcordanceHit] = []
        for entry, superseded in self.rows(locale):
            src_hit = source and needle in (entry.source or "").casefold()
            tgt_hit = target and needle in (entry.text or "").casefold()
            if not src_hit and not tgt_hit:
                continue
            coverage = len(needle) / max(len(entry.source or ""), 1)
            bonus = 0.2 if entry.verified else 0.0
            scored.append(ConcordanceHit(entry, coverage + bonus, superseded))
        scored.sort(key=lambda hit: (-hit.score, len(hit.entry.source or "")))
        return scored[:limit]

    def browse(
        self,
        locale: str,
        *,
        provider: str = "",
        text: str = "",
        limit: int = 250,
    ) -> list[tuple[TMEntry, bool]]:
        """Locale file, optional provider and text filters. Capped."""
        wanted = (provider or "").strip().lower()
        needle = (text or "").casefold().strip()
        kept: list[tuple[TMEntry, bool]] = []
        for entry, superseded in self.rows(locale):
            if wanted and (entry.provider or "").lower() != wanted:
                continue
            if needle:
                hay = f"{entry.source or ''} {entry.text or ''}".casefold()
                if needle not in hay:
                    continue
            kept.append((entry, superseded))
            if len(kept) >= max(0, limit):
                break
        return kept

    def approve(
        self,
        *,
        locale: str,
        source: str,
        text: str,
        context: str = "",
        model: str = "human",
        provider: str | None = "import",
        quality_score: float | None = 1.0,
    ) -> TMEntry:
        """Record an approved human translation for TM reuse / few-shot (A3).

        With a ``write_to`` memory (C-030) the same approved text is also appended there;
        that is the only way anything is written outside the project store.
        """
        entry = self.record(
            locale=locale,
            source=source,
            text=text,
            model=model,
            context=context,
            provider=provider,
            quality_score=quality_score,
            verified=True,
        )
        if self.write_to is not None:
            TranslationMemory(self.write_to).record(
                locale=locale, source=source, text=text, model=model, context=context,
                provider=provider, quality_score=quality_score, verified=True,
            )
        return entry

    def compact(self, locale: str) -> None:
        """Rewrite locale file keeping the latest entry per exact key."""
        # Re-read from disk: another process may have appended since this index
        # was built, and compacting a stale view would silently drop those.
        self._index.pop(locale, None)
        self._index_mtime.pop(locale, None)
        by_key = self._ensure_index(locale)
        lines = [e.to_json() for e in by_key.values()]
        path = self.path_for(locale)
        if not lines and not path.exists():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        rewrite_text_locked(path, "\n".join(lines) + ("\n" if lines else ""))
        self._near_cache.pop(locale, None)
