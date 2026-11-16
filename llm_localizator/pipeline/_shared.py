"""Payload-building helpers shared by translate and suggest.

These functions build ``BatchItem`` payloads but make no LLM calls.
They are split out so ``ops.suggest`` can import them without pulling in the
full translation engine.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ..catalog.scores import ScoreStore
from ..catalog.tm import TranslationMemory
from ..core.standards import get_standard, uses_icu
from ..projects import (
    ContextNotes,
    ProjectConfig,
    effective_glossary_for,
)
from ..projects.screenshots import resolve_screenshot_path
from ..scan.usage_hints import load_usage_hints
from .context_assembler import assemble_context, context_completeness
from .ensemble import high_risk_source, risk_level
from .frame_samples import frame_sample_values, is_placeholder_frame
from .placeholder_mask import mask_bare_placeholders
from .prompts import BatchItem


@dataclass(frozen=True)
class WorkItem:
    namespace: str
    locale: str
    key: str
    source: str
    current: str = ""
    status: str = ""


@dataclass
class NamespaceSnapshot:
    """Immutable source/target maps plus prebuilt screen indexes for one ns."""

    source: dict[str, str]
    target: dict[str, str]
    # screen → [(key, source, target), ...] (capped)
    siblings_by_screen: dict[str, list[tuple[str, str, str]]]
    peers_by_screen: dict[str | None, list[tuple[str, str]]]


def build_namespace_snapshot(
    cfg: ProjectConfig,
    catalog,
    notes: ContextNotes,
    locale: str,
    namespace: str,
    *,
    scores: ScoreStore | None = None,
    target_cache: dict | None = None,
) -> NamespaceSnapshot:
    """Load maps once and index siblings/peers by screen (O(n) per namespace)."""
    source = catalog.load(cfg.source_locale, namespace)
    if target_cache is not None and (locale, namespace) in target_cache:
        target = target_cache[(locale, namespace)]
    else:
        target = dict(catalog.load(locale, namespace))
        if target_cache is not None:
            target_cache[(locale, namespace)] = target

    by_screen: dict[str, list[tuple[str, str, str]]] = {}
    for key, en in source.items():
        if key not in target or not isinstance(en, str):
            continue
        screen = notes.screen(namespace, key)
        if not screen:
            continue
        bucket = by_screen.setdefault(screen, [])
        if len(bucket) < 12:
            bucket.append((key, en, target[key]))

    peers_by_screen: dict[str | None, list[tuple[str, str]]] = {}
    if scores is not None:
        screens = {notes.screen(namespace, key) for key in source}
        screens.add(None)
        for screen in screens:
            peers_by_screen[screen] = scores.top_peers(
                locale, namespace,
                catalog_source=source, catalog_target=target,
                screen_of=(lambda k: notes.screen(namespace, k)) if screen else None,
                screen=screen, exclude_key=None, limit=8,
            )
    return NamespaceSnapshot(
        source=source,
        target=target,
        siblings_by_screen=by_screen,
        peers_by_screen=peers_by_screen,
    )


def _item_context(
    notes: ContextNotes,
    native_notes: dict[str, str] | None,
    item: WorkItem,
) -> str:
    parts = [
        (native_notes or {}).get(item.key, ""),
        notes.note(item.namespace, item.key),
    ]
    return "; ".join(dict.fromkeys(p for p in parts if p))


def _item_glossary(cfg: ProjectConfig, notes: ContextNotes, item: WorkItem) -> dict:
    domains = cfg.glossary_domains_for(
        item.namespace,
        key_domain=notes.domain(item.namespace, item.key),
    )
    return effective_glossary_for(
        cfg.glossary_path,
        domains=domains,
        shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )


def _payload(
    cfg, catalog, notes, pivot_cache, pivot_locale, item: WorkItem,
    native_notes: dict[str, str] | None,
    target_cache: dict,
    locale: str,
    examples: list[tuple[str, str]] | None = None,
    scores: ScoreStore | None = None,
    tm: TranslationMemory | None = None,
    *,
    force: bool = False,
    glossary: dict | None = None,
    coherence_index=None,
    ns_snapshots: dict | None = None,
) -> BatchItem:
    context = _item_context(notes, native_notes, item)
    scan_hint = load_usage_hints(
        getattr(cfg, "scan_out_dir", None), item.namespace,
    ).get(item.key, "")
    shown_context = context
    if scan_hint and scan_hint not in context:
        shown_context = f"{context}; {scan_hint}" if context else scan_hint
    llm_note = notes.llm_note(item.namespace, item.key)
    screen = notes.screen(item.namespace, item.key)

    pivot = None
    if pivot_locale:
        cache_key = (pivot_locale, item.namespace)
        if cache_key not in pivot_cache:
            pivot_cache[cache_key] = catalog.load(pivot_locale, item.namespace)
        pivot = pivot_cache[cache_key].get(item.key)

    snap_key = (locale, item.namespace)
    snap: NamespaceSnapshot | None = None
    if ns_snapshots is not None:
        snap = ns_snapshots.get(snap_key)
        if snap is None:
            snap = build_namespace_snapshot(
                cfg, catalog, notes, locale, item.namespace,
                scores=scores, target_cache=target_cache,
            )
            ns_snapshots[snap_key] = snap

    siblings: list[tuple[str, str]] = []
    if screen:
        if snap is not None:
            for key, en, tgt in snap.siblings_by_screen.get(screen, []):
                if key == item.key:
                    continue
                siblings.append((en, tgt))
                if len(siblings) >= 6:
                    break
        else:
            source = catalog.load(cfg.source_locale, item.namespace)
            target = target_cache.get((locale, item.namespace))
            if target is None:
                target = dict(catalog.load(locale, item.namespace))
                target_cache[(locale, item.namespace)] = target
            for key, en in source.items():
                if key == item.key or key not in target:
                    continue
                if notes.screen(item.namespace, key) != screen:
                    continue
                siblings.append((en, target[key]))
                if len(siblings) >= 6:
                    break

    peer_pairs: list[tuple[str, str]] = []
    if scores is not None:
        if snap is not None:
            peers = list(snap.peers_by_screen.get(screen) or snap.peers_by_screen.get(None) or [])
            peer_pairs = [(en, tgt) for en, tgt in peers if en != item.source][:5]
        else:
            source = catalog.load(cfg.source_locale, item.namespace)
            target = target_cache.get((locale, item.namespace))
            if target is None:
                target = catalog.load(locale, item.namespace)
            peer_pairs = scores.top_peers(
                locale, item.namespace,
                catalog_source=source, catalog_target=target,
                screen_of=lambda k: notes.screen(item.namespace, k),
                screen=screen, exclude_key=item.key, limit=5,
            )

    words = len((item.source or "").split())
    incomplete = context_completeness(
        item.source,
        note=context or llm_note,
        screen=screen,
        high_risk=high_risk_source(item.source, cfg),
        ambiguous_short=words <= 2,
    )
    level = risk_level(
        item.source, cfg,
        html=notes.html(item.namespace, item.key),
        context_incomplete=bool(incomplete),
    )
    block = bool(incomplete) and level == "high" and not force

    pkg = assemble_context(
        source=item.source,
        locale=locale,
        namespace=item.namespace,
        key=item.key,
        context=shown_context,
        llm_note=llm_note,
        screen=screen,
        max_chars=notes.max_chars(item.namespace, item.key),
        html=notes.html(item.namespace, item.key),
        pivot=pivot,
        file_examples=list(examples) if examples else None,
        siblings=siblings,
        peer_pairs=peer_pairs,
        tm=None if block else tm,
        coherence_index=coherence_index,
        high_risk=high_risk_source(item.source, cfg),
        scan_hint=scan_hint,
        allow_unverified_tm_examples=True,
        semantic_tm=bool(getattr(cfg, "tm_semantic", False)),
        catalogue_semantic=bool(getattr(cfg, "catalogue_semantic", False)),
    )

    image_b64 = None
    if getattr(cfg, "vision_model", None):
        image_path = resolve_screenshot_path(
            cfg.context_dir,
            screen=screen,
            image=notes.image(item.namespace, item.key),
            locale=locale,
        )
        if image_path is not None:
            try:
                image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
            except OSError:
                image_b64 = None

    icu = uses_icu(getattr(cfg, "catalog_standard", None))
    if icu:
        masked_source, ph_mask = mask_bare_placeholders(item.source)
    else:
        masked_source, ph_mask = item.source, {}
    # Block only high-risk strings with missing context — not every short label.
    # ``force`` retranslate still runs (operator override).
    batch_item = pkg.to_batch_item(
        item.source,
        prompt_source=masked_source if ph_mask else None,
        placeholder_mask=ph_mask or None,
        image_b64=image_b64,
        block_translate=block,
    )
    if icu and is_placeholder_frame(item.source):
        # "{rank} of {suit}": show it filled ("Ace of Spades") so "of" is not a guess (ADR-124).
        batch_item.frame_samples = frame_sample_values(
            item.source, notes.preview_values(item.namespace, item.key),
        )
    if not icu:
        spec = get_standard(cfg.catalog_standard)
        batch_item.native_standard = True
        batch_item.preserve_tokens = tuple(sorted(spec.tokens(item.source)))
    if glossary:
        from ..core.glossary_match import format_glossary_annotation, glossary_hits

        batch_item.glossary_note = format_glossary_annotation(
            glossary_hits(item.source, glossary, locale),
        )
    batch_item.pivot_locale = pivot_locale or ""
    batch_item.file_note = notes.file_note(item.namespace)
    batch_item.register = notes.register(item.namespace, item.key) or ""
    batch_item.gender = notes.gender(item.namespace, item.key) or ""
    group = notes.group(item.namespace, item.key)
    if group:
        source_map = snap.source if snap is not None else catalog.load(
            cfg.source_locale, item.namespace,
        )
        batch_item.group = group
        batch_item.group_parts = [
            (k, source_map[k]) for k in notes.group_keys(item.namespace, group)
            if k != item.key and isinstance(source_map.get(k), str)
        ] or None
    batch_item.risk = level
    label = f"{item.namespace}.{item.key}" if item.namespace else item.key
    batch_item.ui_role = _roles_for(cfg).get(label) or _roles_for(cfg).get(item.key) or ""
    return batch_item


_ROLE_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


def _roles_for(cfg) -> dict[str, str]:
    """Key -> UI role from ``check-keys`` (ADR-129), cached by file mtime."""
    from pathlib import Path

    try:
        path = Path(cfg.data_root()) / "usage" / "roles.json"
        mtime = path.stat().st_mtime
    except (OSError, TypeError, AttributeError):
        return {}
    cached = _ROLE_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    from ..ops.web_runtime import load_roles

    roles = load_roles(cfg)
    _ROLE_CACHE[str(path)] = (mtime, roles)
    return roles
