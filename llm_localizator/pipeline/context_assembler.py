"""Typed context retrieval with provenance (audit A1 / ADR-25).

Ranks TM / examples / siblings / peers and records why each item was included.
Filesystem and catalogue I/O stay in the caller; this module only ranks and
packages already-loaded assets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..catalog.tm import TMEntry, TranslationMemory, tm_near_sort_key
from ..core.icu import extract_placeholders
from .prompts import BatchItem

__all__ = [
    "ContextItem",
    "ContextPackage",
    "assemble_context",
    "context_completeness",
    "rank_tm_near",
]


@dataclass(frozen=True)
class ContextItem:
    """One retrieval hit injected into (or considered for) the prompt."""

    kind: str  # tm_exact | tm_near | example | sibling | peer | catalogue_exact | catalogue_near
    authority: str  # approved | suggestion | machine
    source: str
    target: str
    score: float | None = None
    reason: str = ""


@dataclass
class ContextPackage:
    """Bounded context for one key, plus a retrieval trace."""

    items: list[ContextItem] = field(default_factory=list)
    context: str = ""
    llm_note: str = ""
    screen: str | None = None
    max_chars: int | None = None
    html: bool = False
    message_key: str = ""
    pivot: str | None = None
    examples: list[tuple[str, str]] = field(default_factory=list)
    siblings: list[tuple[str, str]] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)

    def to_batch_item(
        self,
        source: str,
        *,
        prompt_source: str | None = None,
        placeholder_mask: dict[str, str] | None = None,
        image_b64: str | None = None,
        block_translate: bool = False,
    ) -> BatchItem:
        return BatchItem(
            source=source,
            prompt_source=prompt_source,
            placeholder_mask=placeholder_mask,
            context=self.context,
            llm_note=self.llm_note,
            pivot=self.pivot,
            max_chars=self.max_chars,
            examples=self.examples or None,
            siblings=self.siblings or None,
            image_b64=image_b64,
            message_key=self.message_key,
            html=self.html,
            incomplete=list(self.incomplete) or None,
            block_translate=block_translate,
            trace=list(self.trace),
        )


def context_completeness(
    source: str,
    *,
    note: str = "",
    screen: str | None = None,
    high_risk: bool = False,
    ambiguous_short: bool = False,
) -> list[str]:
    """Return missing-context reasons for high-risk strings.

    Ambiguous short labels are noted only when already high-risk (so everyday
    buttons are not blocked solely for lacking a screen id).
    """
    missing: list[str] = []
    if not high_risk:
        return missing
    if not (note or "").strip():
        missing.append("missing_note")
    if not (screen or "").strip():
        missing.append("missing_screen")
    if ambiguous_short and not (note or "").strip():
        if "missing_note" not in missing:
            missing.append("ambiguous_short_no_note")
    return missing


def rank_tm_near(
    hits: list[tuple[TMEntry, float]],
    *,
    limit: int = 3,
    allow_unverified: bool = True,
) -> list[tuple[TMEntry, float]]:
    """Prefer verified TM, then higher overlap; optionally drop machine hits."""
    filtered: list[tuple[TMEntry, float]] = []
    for entry, overlap in hits:
        if entry.verified:
            filtered.append((entry, overlap))
        elif allow_unverified:
            filtered.append((entry, overlap))
    filtered.sort(key=tm_near_sort_key)
    return filtered[: max(0, limit)]


def _compatible(source: str, example_source: str) -> bool:
    """Drop few-shots that introduce placeholders absent from the target string."""
    extra = extract_placeholders(example_source) - extract_placeholders(source)
    return not extra


def assemble_context(
    *,
    source: str,
    locale: str,
    namespace: str,
    key: str,
    context: str = "",
    llm_note: str = "",
    screen: str | None = None,
    max_chars: int | None = None,
    html: bool = False,
    pivot: str | None = None,
    file_examples: list[tuple[str, str]] | None = None,
    siblings: list[tuple[str, str]] | None = None,
    peer_pairs: list[tuple[str, str]] | None = None,
    tm: TranslationMemory | None = None,
    coherence_index: object | None = None,
    high_risk: bool = False,
    allow_unverified_tm_examples: bool = False,
    example_limit: int = 5,
    sibling_limit: int = 6,
    semantic_tm: bool = False,
    catalogue_semantic: bool = False,
    scan_hint: str = "",
) -> ContextPackage:
    """Rank and bound retrieval assets for one message key."""
    pkg = ContextPackage(
        context=context,
        llm_note=llm_note,
        screen=screen,
        max_chars=max_chars,
        html=html,
        message_key=f"{namespace}.{key}" if namespace else key,
        pivot=pivot,
    )
    words = len((source or "").split())
    pkg.incomplete = context_completeness(
        source,
        note=context or llm_note,
        screen=screen,
        high_risk=high_risk,
        ambiguous_short=words <= 2,
    )
    for reason in pkg.incomplete:
        pkg.trace.append(f"lint:{reason}")
    if scan_hint:
        pkg.trace.append(f"scan:{scan_hint}")

    seen: set[tuple[str, str]] = set()
    examples: list[tuple[str, str]] = []

    def _add_example(
        pair: tuple[str, str],
        *,
        kind: str,
        authority: str,
        score: float | None,
        reason: str,
    ) -> None:
        if pair in seen or not _compatible(source, pair[0]):
            return
        if len(examples) >= example_limit:
            return
        seen.add(pair)
        examples.append(pair)
        pkg.items.append(ContextItem(
            kind=kind, authority=authority, source=pair[0], target=pair[1],
            score=score, reason=reason,
        ))
        pkg.trace.append(f"{kind}:{authority}:{reason}")

    for en, tgt in file_examples or []:
        _add_example(
            (en, tgt), kind="example", authority="approved",
            score=None, reason="examples_file",
        )

    if coherence_index is not None and len(examples) < example_limit:
        exact = coherence_index.exact_siblings(  # type: ignore[attr-defined]
            namespace, key, source, quality_only=True,
        )
        for hit in exact:
            if len(examples) >= example_limit:
                break
            _add_example(
                (hit.source, hit.target),
                kind="catalogue_exact",
                authority="approved" if hit.quality_ok else "suggestion",
                score=hit.score,
                reason=f"{hit.namespace}.{hit.key}",
            )

    if (
        coherence_index is not None
        and catalogue_semantic
        and len(examples) < example_limit
    ):
        near = coherence_index.similar_sources(  # type: ignore[attr-defined]
            source,
            exclude=(namespace, key),
            limit=example_limit - len(examples),
            quality_only=True,
            semantic=True,
        )
        for hit in near:
            _add_example(
                (hit.source, hit.target),
                kind="catalogue_near",
                authority="suggestion",
                score=hit.score,
                reason=f"overlap={hit.score:.2f}:{hit.namespace}.{hit.key}",
            )

    if tm is not None and len(examples) < example_limit:
        raw_near = tm.near(
            locale, source, context=context, limit=10, semantic=semantic_tm,
        )
        for entry, overlap in rank_tm_near(
            raw_near,
            limit=example_limit - len(examples),
            allow_unverified=allow_unverified_tm_examples,
        ):
            auth = "approved" if entry.verified else "suggestion"
            _add_example(
                (entry.source, entry.text),
                kind="tm_near",
                authority=auth,
                score=overlap,
                reason=f"overlap={overlap:.2f}",
            )

    for en, tgt in peer_pairs or []:
        _add_example(
            (en, tgt), kind="peer", authority="machine",
            score=None, reason="high_score_peer",
        )

    sibs: list[tuple[str, str]] = []
    for en, tgt in siblings or []:
        if len(sibs) >= sibling_limit:
            break
        if not _compatible(source, en):
            continue
        sibs.append((en, tgt))
        pkg.items.append(ContextItem(
            kind="sibling", authority="suggestion", source=en, target=tgt,
            reason=f"screen={screen or ''}",
        ))
        pkg.trace.append(f"sibling:suggestion:screen={screen or ''}")

    pkg.examples = examples
    pkg.siblings = sibs
    return pkg
