"""Shared catalogue/state/scores/history flush (ADR-24 ordering)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..catalog import Catalog, StateStore
from ..catalog.flush_journal import FlushIntent, FlushJournal
from ..catalog.history import HistoryEvent, HistoryStore
from ..catalog.scores import ScoreStore
from ..catalog.state import is_verified, needs_translation, now_iso, state_key

__all__ = ["flush_pending", "accept_allowed", "FlushResult"]

_compact_counters: dict[str, int] = {}


@dataclass
class FlushResult:
    """Keys written and keys skipped because the target changed mid-run."""

    flushed: list[tuple[str, str, str]] = field(default_factory=list)
    skipped_external: list[tuple[str, str, str]] = field(default_factory=list)

    def __iter__(self):
        return iter(self.flushed)

    def __len__(self) -> int:
        return len(self.flushed)

    def __bool__(self) -> bool:
        return bool(self.flushed)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FlushResult):
            return (
                self.flushed == other.flushed
                and self.skipped_external == other.skipped_external
            )
        if isinstance(other, list):
            return self.flushed == other
        return NotImplemented


def accept_allowed(
    source: str,
    entry: dict | None,
    *,
    force: bool = False,
    allow_current: bool = False,
    context: dict | None = None,
) -> bool:
    """Re-check under the mutation lock before writing (TOCTOU guard).

    *allow_current* is True for ``--flagged`` / improve rewrites where the
    source hash already matches but the operator asked to overwrite.
    *context* is ``ContextNotes.stale_args`` so a key selected because its
    translator context changed is still accepted.
    """
    if not force and is_verified(entry):
        return False
    if allow_current or force:
        return True
    return needs_translation(source, entry, force, **(context or {}))


def _norm_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _restore_sidecar_key(
    store, locale: str, namespace: str, key: str, disk: dict | None = None,
) -> None:
    """Put one key back to whatever is on disk, keeping other in-memory edits.

    *disk* memoises the parsed file per ``(id(store), locale)`` so a flush
    with many skipped keys reads each sidecar once. An unreadable file
    leaves the in-memory value alone instead of deleting the key.
    """
    memo_key = (id(store), locale)
    if disk is not None and memo_key in disk:
        raw = disk[memo_key]
    else:
        path = store.path_for(locale)
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError, UnicodeError):
            raw = None
        if raw is not None and not isinstance(raw, dict):
            raw = None
        if disk is not None:
            disk[memo_key] = raw
    if raw is None:
        return
    sk = state_key(namespace, key)
    data = store.load(locale)
    if sk in raw:
        data[sk] = raw[sk]
    else:
        data.pop(sk, None)


def _bust_pending_paths(catalog, pending: dict) -> None:
    bust = getattr(catalog, "_bust_cache", None)
    path_for = getattr(catalog, "path_for", None)
    if bust is None or path_for is None:
        catalog.invalidate()
        return
    try:
        for ns, locale in pending:
            bust(path_for(locale, ns))
    except Exception:  # adapter without per-file paths: fall back
        catalog.invalidate()


def _filter_external_edits(
    catalog: Catalog,
    pending: dict,
    baselines: dict | None,
) -> tuple[dict, list[tuple[str, str, str]]]:
    """Drop pending keys whose on-disk target moved since pick time.

    *baselines* mirrors *pending*: ``{(ns, locale): {key: pick_time_value|None}}``.
    Keys without a baseline entry keep the old always-write behaviour.
    """
    if not baselines:
        return pending, []
    skipped: list[tuple[str, str, str]] = []
    filtered: dict = {}
    # Bust only the files we are about to compare (not the whole cache):
    # a full invalidate forced every later load in the run to re-parse.
    _bust_pending_paths(catalog, pending)
    for (ns, locale), updates in pending.items():
        base_map = baselines.get((ns, locale)) or {}
        if not base_map:
            filtered[(ns, locale)] = dict(updates)
            continue
        existing = catalog.load(locale, ns)
        source: dict | None = None
        kept: dict = {}
        for key, new_val in updates.items():
            if key not in base_map:
                kept[key] = new_val
                continue
            # A missing key and an empty value are the same "nothing there yet".
            baseline = _norm_text(base_map[key]) or None
            on_disk = _norm_text(existing.get(key)) or None
            new_text = _norm_text(new_val)
            if on_disk != baseline and on_disk != new_text:
                if baseline is None:
                    # An earlier flush of this run fills untranslated keys with
                    # the source text (merge_for_write); that is not an edit.
                    if source is None:
                        source = catalog.load(catalog.source_locale, ns)
                    if on_disk == _norm_text(source.get(key)):
                        kept[key] = new_val
                        continue
                skipped.append((locale, ns, key))
                continue
            kept[key] = new_val
        if kept:
            filtered[(ns, locale)] = kept
    return filtered, skipped


def flush_pending(
    cfg,
    catalog: Catalog,
    state: StateStore,
    scores: ScoreStore,
    pending: dict,
    history: HistoryStore | None = None,
    pending_history: list[tuple[str, HistoryEvent]] | None = None,
    *,
    compact_history: bool = True,
    history_compact_every: int = 1,
    use_journal: bool = True,
    baselines: dict | None = None,
    run_id: str | None = None,
) -> FlushResult:
    """Write pending updates in catalogue → state → scores → history order.

    Returns :class:`FlushResult` with flushed ``(locale, namespace, key)`` triples
    and any keys skipped because the target catalogue value changed after pick
    time (*baselines*). When *pending* is empty but *pending_history* is not,
    only history (and optional score saves already done by the caller) is
    appended.

    *baselines* is optional and keyed like *pending*:
    ``{(namespace, locale): {key: value_at_pick_or_None}}``.

    *run_id* stamps the flush journal; prefer this over mutating
    ``cfg._flush_run_id`` (see :mod:`run_context`).
    """
    from .run_context import flush_run_id_of

    result = FlushResult()
    if not pending and not pending_history:
        return result

    safe_pending, skipped = _filter_external_edits(catalog, pending, baselines)
    result.skipped_external = skipped
    if skipped:
        skip_set = set(skipped)
        disk: dict = {}
        for locale, ns, key in skipped:
            _restore_sidecar_key(state, locale, ns, key, disk)
            _restore_sidecar_key(scores, locale, ns, key, disk)
        if pending_history:
            pending_history[:] = [
                (loc, ev) for loc, ev in pending_history
                if (loc, ev.namespace, ev.key) not in skip_set
            ]
        # Drop skipped keys from the caller's pending map so a retry does not
        # re-apply an overwrite the operator already rejected.
        for (ns, locale), updates in list(pending.items()):
            for loc, n, k in skipped:
                if n == ns and loc == locale:
                    updates.pop(k, None)
            if not updates:
                pending.pop((ns, locale), None)

    locales = sorted({locale for (_, locale) in safe_pending} | {
        locale for locale, _ in (pending_history or [])
    } | {loc for loc, _, _ in skipped})
    namespaces = sorted({ns for (ns, _) in safe_pending} | {ns for _, ns, _ in skipped})
    flushed_keys = [
        (locale, ns, key)
        for (ns, locale), updates in safe_pending.items()
        for key in updates
    ]
    result.flushed = flushed_keys

    journal_run = run_id or flush_run_id_of(cfg)
    journal = FlushJournal(cfg.state_root()) if use_journal else None
    if journal is not None:
        intent = FlushIntent(
            run_id=journal_run,
            started_at=now_iso(),
            locales=locales,
            namespaces=namespaces,
            pending_keys=sum(len(u) for u in safe_pending.values()),
            history_events=len(pending_history or []),
            phase="started",
        )
        journal.begin(intent)
    touched: set[str] = set()
    if journal is not None:
        journal.set_phase("catalog")
    for (ns, locale), updates in sorted(safe_pending.items()):
        source = catalog.load(cfg.source_locale, ns)
        existing = catalog.load(locale, ns)
        catalog.save(locale, ns, catalog.merge_for_write(source, existing, updates))
        touched.add(locale)
    # Locales whose only action was a skip still need state/score restore saved.
    for locale, _ns, _key in skipped:
        touched.add(locale)
    if safe_pending or skipped:
        if journal is not None:
            journal.set_phase("state")
        state.save_all(sorted(touched))
        if journal is not None:
            journal.set_phase("scores")
        scores.save_all(sorted(touched))
        pending.clear()
        if baselines is not None:
            baselines.clear()
    if history is not None and pending_history:
        if journal is not None:
            journal.set_phase("history")
        # Drop what was written even on failure, so a mid-list error leaves
        # only unwritten events for retry (no duplicated lines). One slice
        # delete instead of a pop(0) per event.
        written = 0
        try:
            for locale, event in pending_history:
                history.append(locale, event)
                written += 1
        finally:
            del pending_history[:written]
        if compact_history:
            every = max(1, int(history_compact_every or 1))
            root_key = str(cfg.state_root())
            tick = _compact_counters.get(root_key, 0) + 1
            _compact_counters[root_key] = tick
            if tick % every == 0:
                for locale in locales:
                    history.compact(locale)
    if journal is not None:
        journal.set_phase("done")
        if flushed_keys:
            journal.note_progress(
                flushed_keys,
                run_id=journal_run,
            )
        else:
            journal.clear()
    return result
