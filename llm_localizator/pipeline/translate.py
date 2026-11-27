"""The translation engine.

Collects the work up front, groups it by (locale, model) so each batch hits one
model, translates in batches with a per-key fallback, validates every candidate,
scores quality, appends history, and **checkpoints after every batch**.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from ..catalog import Catalog, FlagStore, StateStore, needs_translation
from ..catalog.history import HistoryEvent, HistoryStore
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.scores import ScoreStore
from ..catalog.state import is_locked, state_key, is_verified, translation_status
from .checkpoint import accept_allowed
from ..catalog.tm import TranslationMemory
from ..catalog.review_queue import STATUS_BLOCKED, open_review_queue
from ..catalog.flush_journal import FlushJournal
from ..catalog.pricing import estimate_tokens
from ..core.cldr import language_name
from ..core.hyphens import apply_soft_hyphens
from ..core.icu import is_bare_placeholder_span, needs_icu_decomposition, split_top_level_segments
from ..core.quality import DEFAULT_SCORE_THRESHOLD, sample_consistency, with_consistency
from ..core.standards import get_standard, uses_icu
from ..core.validate import check_translation_length
from ..projects import (
    ContextNotes,
    ProjectConfig,
    effective_glossary_for,
    glossary_prompt_block,
    load_examples,
    load_glossary,
)
from ..providers import CompletionRequest, Provider, ProviderError, provider_for_locale, record_provider_spend
from ..reporting import log_heartbeat, report as queue_report
from ..reporting import report_metric, report_progress, report_run_summary
from .prompts import (
    BATCH_SCHEMA,
    build_batch_prompt,
    build_fragment_prompt,
    build_icu_span_prompt,
    build_refine_prompt,
    build_shorten_prompt,
    build_single_prompt,
)
from .candidates import soft_issues as _soft_issues
from .candidates import validate_candidate as _validate_candidate
from .write_policy import hold_as_draft, hold_reason
from ._shared import WorkItem, _item_context, _item_glossary, _payload
from .ensemble import CandidateRecord, needs_secondary_pass, pick_better
from .translate_icu import _bill_cloud  # noqa: F401 (re-exported for tests)
from .translate_icu import _translate_icu_whole
from .frame_samples import has_icu_choice
from .translate_items import (
    _candidate,
    _flush,
    _resolve_flushed_flags,
    _retry_rejected,
    _shorten,
    _soft_retry,
    _translate_batch,
    _translate_payload,
    _translate_singles,
    cloud_async_batch_enabled,
    reject_duplicate_batch_outputs,
    translate_cloud_async_batches,
)


from .placeholder_mask import mask_bare_placeholders, restore_placeholders
from .recording import provenance_stores, record_candidate
from .planning import dry_run_messages, pin_run_model, plan_batches
from .run_manifest import RunManifest, config_fingerprint
from .scoring import (
    PendingScoreItem,
    collect_pending_llm_scores,
    improve_score_cut,
    run_deferred_scoring_phase,
    score_candidate,
    score_model_for,
    should_defer_scoring_for_translate,
)

__all__ = [
    "TranslationResult",
    "WorkItem",
    "collect_work",
    "run_translation",
    "min_keys_skip_message",
    "reject_duplicate_batch_outputs",
    "word_count",
]

Reporter = Callable[[str], None]

#: Flag reason for a key whose ICU message failed whole, by fragments and on the secondary.


from .translate_process import (  # noqa: F401  (re-exported: tests and ops import them from here)
    ICU_FAILED, _Loc, _append_flag, _dual_candidate, _process_translation, _split_blocked, _try_glossary_answer,
    _try_tm_hit,
)
from .translate_run import (  # noqa: F401
    batch_glossary as _batch_glossary,
    start_manifest as _start_manifest,
    summary_line as _summary_line,
)

@dataclass
class TranslationResult:
    total: int = 0
    written: int = 0
    rejected: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # provider errors / empty answers
    #: ICU message failed whole, fragment by fragment and on the secondary (ADR-124); flagged.
    icu_failed: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    flagged_low_score: list[str] = field(default_factory=list)
    # Candidates kept as drafts: below the write floor or not better than the current text.
    held: list[str] = field(default_factory=list)
    escalated: list[str] = field(default_factory=list)  # rescued by the secondary model
    #: Target edited outside the run between pick and write; run ``adopt``.
    external_edit: list[str] = field(default_factory=list)
    touched: set[tuple[str, str]] = field(default_factory=set)
    dry_run: bool = False
    aborted: bool = False
    #: Resume that only finishes deferred scoring: nothing is written by design.
    score_only: bool = False

    @property
    def exit_code(self) -> int:
        if self.dry_run:
            return 0
        if self.aborted:
            return 1
        # A run that had work but wrote nothing is a failed queue job,
        # regardless of whether outputs were rejected or skipped.
        if self.total and not self.written and not self.score_only:
            return 1
        return 0


def min_keys_skip_message(
    pending: int,
    min_keys: int,
    *,
    force: bool = False,
    flagged: bool = False,
    ignore_min_keys: bool = False,
    locale: str | None = None,
) -> str | None:
    """Return a skip reason when backlog is below ``min_keys``, else None.

    Operator-initiated runs pass ``ignore_min_keys=True`` (or ``--force`` /
    ``--flagged``). The floor only applies to automated sync→translate chains
    so tiny overnight backlogs do not warm the GPU.
    """
    if force or flagged or ignore_min_keys or min_keys <= 0:
        return None
    if pending >= min_keys:
        return None
    where = f"{locale}: " if locale else ""
    return f"skip {where}{pending} pending < min_keys {min_keys}"


def word_count(text: str) -> int:
    return len(text.split())




def collect_work(
    cfg: ProjectConfig,
    catalog: Catalog,
    state: StateStore,
    *,
    locales: list[str],
    namespaces: list[str],
    force: bool = False,
    only_keys: dict[str, set[str]] | None = None,
    held: list[WorkItem] | None = None,
    skip_unrecorded: bool = True,
    unrecorded: list[WorkItem] | None = None,
) -> list[WorkItem]:
    """Everything needing translation, computed up front for honest progress.

    ``human``-tier keys (ADR-52) never enter the list; when ``held`` is given the
    ones that would otherwise have been work are appended to it.

    A target value that differs from the source but has no state record (a project
    that already had catalogues before it used this tool) is an existing translation,
    not a gap. It stays out of a broad run so it is never overwritten; when
    ``unrecorded`` is given those items are appended to it. ``force``, naming the key
    (``only_keys``) or ``skip_unrecorded=False`` retranslates them.
    """
    from .tiers import TIER_HUMAN, tier_for

    work: list[WorkItem] = []
    notes = ContextNotes(cfg.context_dir)
    for ns in namespaces:
        source = catalog.load(cfg.source_locale, ns)
        for locale in locales:
            target = catalog.load(locale, ns)
            allowed = only_keys.get(locale, set()) if only_keys is not None else None
            for key, value in source.items():
                if cfg.is_skipped(ns, key, value if isinstance(value, str) else None) or not isinstance(value, str) or not value.strip():
                    continue
                raw_current = target.get(key)
                current = raw_current if isinstance(raw_current, str) else ""
                entry = state.entry(locale, ns, key)
                status = translation_status(
                    value,
                    current if raw_current is not None else None,
                    entry,
                )
                item = WorkItem(ns, locale, key, value, current, status)
                if tier_for(cfg, notes, ns, key) == TIER_HUMAN:
                    if (
                        held is not None
                        and not is_locked(entry)
                        and not is_verified(entry)
                        and needs_translation(value, entry, force, **notes.stale_args(ns, key))
                    ):
                        held.append(item)
                    continue
                if allowed is None and cfg.is_request_only(ns, key):
                    continue  # ADR-104: only translated when the key is named explicitly
                if allowed is not None:
                    if state_key(ns, key) in allowed:
                        if is_locked(entry):
                            continue
                        if not force and is_verified(entry):
                            continue
                        work.append(item)
                    continue
                if is_locked(entry):
                    continue
                if not force and is_verified(entry):
                    continue
                if (
                    skip_unrecorded and not force and entry is None
                    and current.strip() and current != value
                ):
                    if unrecorded is not None:
                        unrecorded.append(item)
                    continue
                if needs_translation(value, entry, force, **notes.stale_args(ns, key)):
                    work.append(item)
    return work


def missing_keys(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str],
) -> dict[str, set[str]]:
    """Per locale, the keys whose target value is absent or empty (``--only-missing``).

    Same shape as ``only_keys``. Keys the source itself leaves empty or the
    project skips are not gaps.
    """
    from ..catalog.state import state_key

    out: dict[str, set[str]] = {}
    for ns in namespaces:
        source = catalog.load(cfg.source_locale, ns)
        for locale in locales:
            target = catalog.load(locale, ns)
            for key, value in source.items():
                if not isinstance(value, str) or not value.strip():
                    continue
                if cfg.is_skipped(ns, key, value):
                    continue
                current = target.get(key)
                if not isinstance(current, str) or not current.strip():
                    out.setdefault(locale, set()).add(state_key(ns, key))
    return out


def _order_locales(cfg: ProjectConfig, locales: list[str]) -> list[str]:
    """Pivot-safe order; ASAP preferred among ready locales (ADR-47)."""
    if hasattr(cfg, "order_locales"):
        return cfg.order_locales(list(locales))
    ordered: list[str] = []
    remaining = list(locales)
    while remaining:
        progressed = False
        for locale in list(remaining):
            reference = cfg.pivot_for(locale)
            if reference in remaining and reference != locale:
                continue
            ordered.append(locale)
            remaining.remove(locale)
            progressed = True
        if not progressed:
            ordered.extend(remaining)
            break
    return ordered






def run_translation(
    cfg: ProjectConfig,
    catalog: Catalog,
    provider: Provider | None = None,
    *,
    locales: list[str] | None = None,
    namespaces: list[str] | None = None,
    batch_size: int = 10,
    force: bool = False,
    dry_run: bool = False,
    only_keys: dict[str, set[str]] | None = None,
    trigger: str = "translate",
    pre_translate: bool = False,
    multi_sample: int | None = None,
    ignore_min_keys: bool = False,
    named_keys: list[str] | None = None,
    icu_only: bool = False,
    plain_only: bool = False,
    only_missing: bool = False,
    report: Reporter = queue_report,
) -> TranslationResult:
    """Translate everything that needs it. Returns a summary.

    ``only_missing`` limits the run to keys whose target value is absent or empty.
    """
    from ..catalog.flush_journal import flush_block_message
    from ..projects.context import require_context_json
    from .translate_icu import clear_fragment_cache

    clear_fragment_cache()
    blocked = flush_block_message(cfg.state_root())
    if blocked:
        report(blocked)
        return TranslationResult(aborted=True)
    require_context_json(cfg.context_dir)
    glossary = load_glossary(cfg.glossary_path)
    examples_by_locale = load_examples(cfg.examples_file)
    notes = ContextNotes(cfg.context_dir)
    stores = provenance_stores(cfg)
    state, history, scores = stores.state, stores.history, stores.scores
    tm = cfg.open_tm()
    threshold = getattr(cfg, "quality_threshold", DEFAULT_SCORE_THRESHOLD)
    n_samples = max(
        1, int(multi_sample if multi_sample is not None else getattr(cfg, "multi_sample", 1))
    )

    if pre_translate:
        trigger = "pre-translate"
    targets = _order_locales(cfg, cfg.resolve_locales(locales))
    ns_list = namespaces if namespaces is not None else cfg.namespaces_for(catalog)
    only_keys = _resolve_only_keys(
        cfg, catalog, targets, ns_list, only_keys,
        named_keys=named_keys, only_missing=only_missing,
    )
    if only_missing and not any(only_keys.values()):
        report("(100%) No missing keys - nothing to do.")
        return TranslationResult()

    held: list[WorkItem] = []
    unrecorded: list[WorkItem] = []
    work = collect_work(
        cfg, catalog, state,
        locales=targets, namespaces=ns_list, force=force, only_keys=only_keys, held=held,
        unrecorded=unrecorded,
    )
    _report_unrecorded(unrecorded, report)
    if held and not dry_run:
        from .tiers import ticket_held

        ticket_held(cfg, held, report)
    work = _filter_work(cfg, work, icu_only=icu_only, plain_only=plain_only, report=report)
    pin_guess = cfg.model_for(targets[0] if targets else "")
    defer_scoring = should_defer_scoring_for_translate(
        cfg, pin_guess, n_samples=n_samples,
    )
    pending_bt: list[PendingScoreItem] = []
    if defer_scoring:
        pending_bt = collect_pending_llm_scores(
            cfg, catalog, state, scores,
            locales=targets, namespaces=ns_list, only_keys=only_keys,
        )
    skipped_floor = False
    if work and not dry_run:
        work, skipped_floor = _apply_min_keys_floor(
            cfg, work, force=force, flagged=only_keys is not None,
            ignore_min_keys=ignore_min_keys, report=report,
        )
    from ..catalog.budget import BudgetStore

    decision = _cloud_gate(cfg, targets, work, named_keys, batch_size, dry_run)
    if decision.message:
        report(decision.message)
    if decision.refuse:
        return TranslationResult(total=len(work), dry_run=dry_run, aborted=True)
    hold_id = decision.hold_id
    try:
        if not work and not pending_bt:
            if skipped_floor and not dry_run:
                return TranslationResult(total=0, dry_run=False)
            report("(100%) Everything is already translated and up to date.")
            return TranslationResult(total=0, dry_run=dry_run)

        result = TranslationResult(
            total=len(work) if work else len(pending_bt), dry_run=dry_run,
            score_only=not work,
        )
        if not work and pending_bt:
            report(f"resuming deferred scoring: {len(pending_bt)} key(s)")

        prefix = "DRY RUN - " if dry_run else ""
        if work:
            report_progress(
                0, len(work),
                f"{prefix}Translating {len(work)} key-locale pair(s) across {len(ns_list)} namespace(s)",
            )
        if dry_run:
            # Before any provider is built: a dry run needs no key or server.
            _report_dry_run(work, pending_bt, report)
            return result

        _provider_for = _ProviderResolver(cfg, provider, report)
        probe = _provider_for(_probe_locale(targets, work, pending_bt))

        with project_mutation_lock(cfg):
            # Re-check under the lock: the early check can race a peer that
            # was mid-flush (false block) or crashed after it (missed block).
            blocked = flush_block_message(cfg.state_root())
            if blocked:
                report(blocked)
                return TranslationResult(aborted=True)
            return _run_translation_locked(
                cfg=cfg, catalog=catalog, provider=provider, work=work, result=result,
                targets=targets, ns_list=ns_list, glossary=glossary,
                examples_by_locale=examples_by_locale, notes=notes, state=state,
                history=history, scores=scores, tm=tm, threshold=threshold,
                n_samples=n_samples, batch_size=batch_size, force=force, trigger=trigger,
                pre_translate=pre_translate, report=report, _provider_for=_provider_for,
                probe=probe, only_keys=only_keys, defer_scoring=defer_scoring,
                pending_bt_resume=pending_bt, named_keys=named_keys,
            )
    finally:
        if hold_id:
            BudgetStore(cfg.budget_root()).release(hold_id)


# ---- run_translation helpers ------------------------------------------------


def _resolve_only_keys(
    cfg: ProjectConfig,
    catalog: Catalog,
    targets: list[str],
    ns_list: list[str],
    only_keys: dict[str, set[str]] | None,
    *,
    named_keys: list[str] | None,
    only_missing: bool,
) -> dict[str, set[str]] | None:
    """Narrow the run to named keys and/or keys missing from the catalogue."""
    if named_keys:
        from ..catalog.state import split_operator_key, state_key

        resolved = {
            state_key(*split_operator_key(raw, set(ns_list)))
            for raw in named_keys
        }
        only_keys = {loc: set(resolved) for loc in targets}
    if only_missing:
        gaps = missing_keys(cfg, catalog, locales=targets, namespaces=ns_list)
        if only_keys is None:
            only_keys = gaps
        else:
            only_keys = {
                loc: keys & gaps.get(loc, set()) for loc, keys in only_keys.items()
            }
    return only_keys


def _report_unrecorded(unrecorded: list[WorkItem], report: Reporter) -> None:
    if not unrecorded:
        return
    counts: dict[str, int] = {}
    for item in unrecorded:
        counts[item.locale] = counts.get(item.locale, 0) + 1
    report(
        "left as is: "
        + ", ".join(f"{loc} {n}" for loc, n in sorted(counts.items()))
        + " existing translation(s) with no state record; "
        "run `adopt` to record them, or --force / --keys to retranslate"
    )


def _filter_work(
    cfg: ProjectConfig, work: list[WorkItem], *, icu_only: bool, plain_only: bool,
    report: Reporter,
) -> list[WorkItem]:
    """Drop sources with syntax errors; apply the ICU / plain residual lane."""
    spec = get_standard(getattr(cfg, "catalog_standard", None))
    kept: list[WorkItem] = []
    for item in work:
        err = spec.syntax_error(item.source)
        if err:
            report(f"    SKIP {item.namespace}.{item.key}: {err}")
            continue
        kept.append(item)
    if not (icu_only or plain_only):
        return kept
    if not uses_icu(getattr(cfg, "catalog_standard", None)):
        return kept
    lane_items = [
        item for item in kept
        if bool(needs_icu_decomposition(item.source)) == bool(icu_only)
    ]
    lane = "icu-only" if icu_only else "plain-only"
    report(f"    residual lane={lane}: {len(lane_items)} key(s)")
    return lane_items


def _apply_min_keys_floor(
    cfg: ProjectConfig, work: list[WorkItem], *, force: bool, flagged: bool,
    ignore_min_keys: bool, report: Reporter,
) -> tuple[list[WorkItem], bool]:
    """Skip locales with fewer pending keys than ``translate_min_keys``."""
    min_keys = int(getattr(cfg, "translate_min_keys", 50) or 0)
    by_locale: dict[str, list[WorkItem]] = {}
    for item in work:
        by_locale.setdefault(item.locale, []).append(item)
    kept: list[WorkItem] = []
    skipped = False
    for loc, items in by_locale.items():
        skip_msg = min_keys_skip_message(
            len(items), min_keys,
            force=force, flagged=flagged,
            ignore_min_keys=ignore_min_keys, locale=loc,
        )
        if skip_msg:
            report(skip_msg)
            skipped = True
            continue
        kept.extend(items)
    return kept, skipped


def _cloud_gate(cfg, targets, work, named_keys, batch_size, dry_run):
    from ..catalog.cloud_cost import cloud_run_decision

    sources_by_locale: dict[str, list[str]] = {loc: [] for loc in targets}
    for item in work:  # one pass, not one per locale
        sources_by_locale.setdefault(item.locale, []).append(item.source)
    return cloud_run_decision(
        cfg, targets,
        {loc: sources_by_locale.get(loc, []) for loc in targets},
        named_keys=named_keys,
        batch_size=batch_size,
        take_hold=not dry_run,
    )


def _probe_locale(targets, work, pending_bt) -> str:
    if targets:
        return targets[0]
    if work:
        return work[0].locale
    if pending_bt:
        return pending_bt[0].locale
    return ""


def _report_dry_run(work: list[WorkItem], pending_bt: list, report: Reporter) -> None:
    for message in dry_run_messages(
        work,
        label_of=lambda item: (
            f"{item.namespace}.{item.key} -> {item.locale}"
            f" [{item.status}] current={item.current!r}"
        ),
    ):
        report(message)
    if pending_bt:
        report(f"Would also deferred-score {len(pending_bt)} key(s).")
    report(f"(100%) Dry run complete. Would translate {len(work)} key(s).")


class _ProviderResolver:
    """Provider per locale: the injected one when it fits, else built and cached."""

    def __init__(self, cfg: ProjectConfig, provider: Provider | None, report: Reporter) -> None:
        self.cfg = cfg
        self.provider = provider
        self.report = report
        self._cache: dict[str, Provider] = {}

    def __call__(self, locale: str) -> Provider:
        cfg, provider = self.cfg, self.provider
        if provider is not None and not cfg.locale_providers:
            return provider
        if provider is not None and cfg.provider_kind_for(locale) == (
            cfg.provider.kind or "ollama"
        ):
            return provider
        cached = self._cache.get(locale)
        if cached is None:
            cached = self._cache[locale] = provider_for_locale(cfg, locale, report=self.report)
        return cached


@dataclass
class _Run:
    """Run-wide mutable state shared by the helpers below."""
    cfg: Any
    catalog: Any
    state: Any
    history: Any
    scores: Any
    tm: Any
    notes: Any
    result: Any
    report: Any
    force: Any
    only_keys: Any
    trigger: Any
    pre_translate: Any
    defer_scoring: Any
    n_samples: Any
    work: Any
    pending: Any
    pending_history: Any
    baselines: Any
    target_cache: Any
    pivot_cache: Any
    ns_snapshots: Any
    native_notes: Any
    flag_store: Any
    flags_opened: Any
    phase_a_written: Any
    max_consec: Any
    done: int = 0
    consecutive_fail: int = 0
    abort_run: bool = False
    tm_hits: int = 0
    # Run-wide settings read by the per-locale-group helpers.
    ns_list: Any = None
    examples_by_locale: Any = None
    batch_size: int = 10
    named_keys: Any = None
    llm_score: bool = True
    provider_for: Any = None

    def queue_write(self, item, text: str) -> None:
        """Stage a catalogue write and remember the pick-time baseline for flush."""
        key = (item.namespace, item.locale)
        self.pending.setdefault(key, {})[item.key] = text
        base = item.current if isinstance(item.current, str) else None
        self.baselines.setdefault(key, {})[item.key] = base
        self.target_cache.setdefault((item.locale, item.namespace), {})[item.key] = text


def _bt_provider(cfg: ProjectConfig, locale: str, provider_for, report) -> Provider:
    """Provider for deferred BT scoring.

    ``[quality] score_provider`` wins. Without it the translator's provider scores, except that a
    cloud translator never receives a local scorer tag (``aya-expanse:8b``): that pairing scores on
    the project provider instead, which is how the 2026-11-01 cloud smoke ran.
    """
    from ..catalog.cloud_cost import paying_cloud_kind
    from ..providers import project_provider, score_provider_for
    from ..providers.preflight import looks_like_cloud_model
    from .scoring import score_model_for

    configured = score_provider_for(cfg, report=report)
    if configured is not None:
        return configured
    if paying_cloud_kind(cfg, locale) and not looks_like_cloud_model(score_model_for(cfg)):
        report(f"note: {locale} translates on cloud; BT scores locally with {score_model_for(cfg)}")
        return project_provider(cfg)
    return provider_for(locale)


def _flush_step(st: _Run) -> None:
    """Write staged keys, note out-of-band skips, resolve the flags of what was written (M3: repeated 4 times)."""
    flushed = _flush(
        st.cfg, st.catalog, st.state, st.scores, st.pending, st.history, st.pending_history,
        baselines=st.baselines,
    )
    _note_flush_skips(st, flushed)
    _resolve_flushed_flags(st.flag_store, st.only_keys, flushed.flushed, skip=st.flags_opened)


def _coherence_for_locale(st: _Run, ns_list, locale: str):
    """Catalogue siblings of *locale* for prompts; only trusted rows (human-ish status or score >= 0.80) count."""
    from ..catalog.coherence_index import CoherenceIndex

    cfg, catalog, state, scores = st.cfg, st.catalog, st.state, st.scores
    coherence_index = CoherenceIndex()
    rows: list[tuple[str, str, str, str]] = []
    for ns in ns_list:
        src_map = catalog.load(cfg.source_locale, ns)
        tgt_map = st.target_cache.get((locale, ns))
        if tgt_map is None:
            tgt_map = dict(catalog.load(locale, ns))  # own copy: mutated in place later
            st.target_cache[(locale, ns)] = tgt_map
        for k, en in src_map.items():
            if cfg.is_skipped(ns, k) or k not in tgt_map:
                continue
            if isinstance(en, str) and isinstance(tgt_map[k], str):
                rows.append((ns, k, en, tgt_map[k]))

    def _q_ok(ns: str, key: str) -> bool:
        entry = state.entry(locale, ns, key) or {}
        if entry.get("status") in {"human", "verified", "llm_reviewed", "agent", "imported"}:
            return True
        if entry.get("verified"):
            return True
        row = scores.get(locale, ns, key) or {}
        qs = row.get("quality_score")
        return qs is not None and float(qs) >= 0.80

    coherence_index.build(rows, quality_ok=_q_ok)
    return coherence_index


def _note_flush_skips(st: _Run, flushed) -> None:
    """Record catalogue keys skipped at flush because of an out-of-band edit."""
    skipped = getattr(flushed, "skipped_external", None) or []
    for locale, ns, key in skipped:
        label = f"{locale}/{ns}.{key}"
        if label not in st.result.external_edit:
            st.result.external_edit.append(label)
        st.report(
            f"    SKIP {ns}.{key}/{locale} at flush: "
            "target was edited outside the run; run adopt to keep it"
        )
        # Counted as written when queued; roll back the counter.
        if st.result.written > 0:
            st.result.written -= 1





def _finish_run(
    *, cfg, catalog, notes, state, st, result, work, scores, glossary, manifest, run_started, pin_model,
    pending_bt_resume, phase_a_written, flag_store, defer_scoring, batch_size, trigger, report, provider_for,
    prefetcher=None,
) -> None:
    """End of a translation run: the last flush, deferred back-translation scoring (phase 2), review tickets, the
    summary lines, the run manifest and the flush-journal cleanup."""
    phase_a_s: float | None = None
    phase_b_s: float | None = None
    phase_b_scored = 0
    _flush_step(st)

    if defer_scoring:
        written_keys = {
            (p.locale, p.namespace, p.key) for p in phase_a_written
        }
        phase_b_items = list(phase_a_written) + [
            p for p in pending_bt_resume
            if (p.locale, p.namespace, p.key) not in written_keys
        ]
        if phase_b_items:
            phase_b_start = time.perf_counter()
            if work:
                phase_a_s = round(phase_b_start - run_started, 3)
            bt_provider = (
                prefetcher.provider if prefetcher is not None
                else _bt_provider(cfg, phase_b_items[0].locale, provider_for, report)
            )
            with log_heartbeat(
                f"phase 2 BT scoring {len(phase_b_items)} key(s)",
                reporter=report,
            ):
                phase_b_scored = run_deferred_scoring_phase(
                    cfg, bt_provider, scores, glossary, phase_b_items,
                    pin_model=pin_model, report=report, flag_store=flag_store, prefetcher=prefetcher,
                )
            phase_b_s = round(time.perf_counter() - phase_b_start, 3)
            report(f"phase 2 complete: scored {phase_b_scored} key(s)")
    elif work:
        phase_a_s = round(time.perf_counter() - run_started, 3)

    if work and result.written:
        from .tiers import ticket_reviewed

        ticket_reviewed(cfg, notes, work, state, report)

    for ns, locale in sorted(result.touched):
        report(f"  OK {catalog.path_for(locale, ns)} - updated")

    report(_summary_line(result))
    try:
        manifest.bump("written", result.written)
        manifest.bump("rejected", len(result.rejected))
        manifest.finish(
            written=result.written,
            total=result.total,
            rejected=len(result.rejected),
            skipped=len(result.skipped),
            icu_failed=len(result.icu_failed),
            blocked=len(result.blocked),
            flagged_low_score=len(result.flagged_low_score),
            external_edit=len(result.external_edit),
            tm_hits=st.tm_hits,
            llm_keys=max(0, result.written - st.tm_hits),
            defer_scoring=defer_scoring,
            batch_size=batch_size,
            short_batch=bool(getattr(cfg, "translate_short_batch", False)),
            score_model=score_model_for(cfg) if defer_scoring else None,
            phase_a_s=phase_a_s,
            phase_b_s=phase_b_s,
            phase_b_scored=phase_b_scored,
            trigger=trigger,
        )
        manifest.write(cfg.state_root())
        report_run_summary(manifest)
    except OSError:
        pass
    # Clean end: drop progress checkpoint so the next run starts fresh.
    try:
        FlushJournal(cfg.state_root()).clear()
    except OSError:
        pass



def _run_translation_locked(
    *,
    cfg,
    catalog,
    provider,
    work,
    result,
    targets,
    ns_list,
    glossary,
    examples_by_locale,
    notes,
    state,
    history,
    scores,
    tm,
    threshold,
    n_samples,
    batch_size,
    force,
    trigger,
    pre_translate=False,
    report,
    _provider_for,
    probe,
    only_keys=None,
    defer_scoring=False,
    pending_bt_resume=None,
    named_keys=None,
) -> TranslationResult:
    # One model for the whole job. Mid-run swaps leave keep-alive residue and
    # time out the next load on a 6 GB card (wave-2 dogfood failure).
    pin_model = cfg.model_for("")
    pin_model, run_models = pin_run_model(
        work, model_for=lambda item: cfg.model_for(item.locale), fallback=pin_model,
    )
    resume_locales = sorted({p.locale for p in (pending_bt_resume or [])})
    manifest = _start_manifest(cfg, work, pin_model, resume_locales)
    manifest.bump("work", len(work))
    run_started = time.perf_counter()
    # Surface interrupted prior flush for operators.
    interrupted = FlushJournal(cfg.state_root()).interrupted()
    if interrupted is not None:
        report(
            f"WARN: incomplete flush journal from {interrupted.started_at} "
            f"phase={interrupted.phase} locales={interrupted.locales}"
        )
    # After teardown ``ollama stop``, /api/tags is up while weights reload —
    # warm the pinned model before the first real batch.
    if work:
        probe.ensure_ready(pin_model, report=report)
    llm_score = not defer_scoring
    phase_a_written: list[PendingScoreItem] = []
    pending_bt_resume = list(pending_bt_resume or [])
    if len(run_models) > 1:
        report(
            f"pinning one model for this run: {pin_model} "
            f"(config listed {', '.join(sorted(run_models))}; "
            f"use separate --locales jobs to load another model)"
        )

    groups: dict[tuple[str, str], list[WorkItem]] = defaultdict(list)
    for item in work:
        groups[(item.locale, pin_model)].append(item)

    native_notes: dict[str, dict[str, str]] = {}
    if catalog.carries_notes:
        for ns in ns_list:
            native_notes[ns] = {
                k: m.note
                for k, m in catalog.load_entries(cfg.source_locale, ns).items()
                if m.note
            }

    st = _Run(
        cfg=cfg, catalog=catalog, state=state, history=history, scores=scores, tm=tm,
        notes=notes, result=result, report=report, force=force, only_keys=only_keys,
        trigger=trigger, pre_translate=pre_translate, defer_scoring=defer_scoring,
        n_samples=n_samples, work=work,
        pending={}, pending_history=[], baselines={},
        target_cache={}, pivot_cache={}, ns_snapshots={},
        native_notes=native_notes,
        flag_store=FlagStore(cfg.flags_path),
        # Low-score / needs_context flags opened this run must survive flush
        # resolve (otherwise a full sweep writes then immediately clears them).
        flags_opened=set(),
        phase_a_written=phase_a_written,
        max_consec=int(getattr(cfg, "translate_max_consecutive_rejects", 10) or 0),
        ns_list=ns_list, examples_by_locale=examples_by_locale, batch_size=batch_size,
        named_keys=named_keys, llm_score=llm_score, provider_for=_provider_for,
    )
    overlap = _BtOverlap(st, multi_group=len(groups) > 1)

    try:
        locale_rank = {loc: idx for idx, loc in enumerate(targets)}
        for (locale, model), items in sorted(
            groups.items(),
            key=lambda kv: (locale_rank.get(kv[0][0], 10_000), kv[0][0], kv[0][1]),
        ):
            if st.abort_run:
                break
            lc = _translate_locale_group(st, locale, model, items)
            overlap.after_group(lc)

        _finish_run(
            cfg=cfg, catalog=catalog, notes=notes, state=state, st=st, result=result, work=work,
            scores=scores, glossary=glossary, manifest=manifest, run_started=run_started,
            pin_model=pin_model, pending_bt_resume=pending_bt_resume,
            phase_a_written=phase_a_written, flag_store=st.flag_store,
            defer_scoring=defer_scoring, batch_size=batch_size, trigger=trigger, report=report,
            provider_for=_provider_for, prefetcher=overlap.prefetcher,
        )
    finally:
        # Also on errors in the group loop: never leak BtPrefetcher threads.
        overlap.close()
    return result


def _translate_locale_group(st: _Run, locale: str, model: str, items: list[WorkItem]) -> _Loc:
    """Translate one locale's work items in batches; returns the locale context."""
    cfg, report = st.cfg, st.report
    loc_provider = st.provider_for(locale)
    from ..catalog.cloud_cost import paying_cloud_kind, resolve_translation_model

    cloud_kind = paying_cloud_kind(cfg, locale)
    if cloud_kind:
        model = resolve_translation_model(cfg, locale, cloud_kind)
    register, _style_notes = cfg.style_for(locale)
    if cfg.localize_prompt_for(model):
        from .prompt_i18n import ensure_localized

        ensure_localized(cfg, loc_provider, locale, model, report=report)
    lc = _Loc(locale=locale, model=model, loc_provider=loc_provider,
              language=language_name(locale), register=register,
              score_llm=st.llm_score and cloud_kind is None, cloud_kind=cloud_kind)
    ctx = _GroupCtx(
        threshold=improve_score_cut(cfg, scorer="bt", locale=locale),
        pivot_locale=cfg.pivot_for(locale),
        # Exact catalogue siblings always help prompts; fuzzy near needs the flag.
        coherence_index=_coherence_for_locale(st, st.ns_list, locale),
        use_cloud_async=bool(cloud_kind) and cloud_async_batch_enabled(cfg, loc_provider),
    )

    # Longer strings first so short labels can use them as siblings later.
    items = sorted(items, key=lambda it: (-len(it.source), it.namespace, it.key))
    # Hosted models take much larger batches than a small local model (HAIKU_BATCH_PROBE_2026-11-14: 50 keys per
    # request on Haiku 5.5, no parse misses, same BT, half the wall time). [translate] cloud_batch_size.
    loc_batch = (
        int(getattr(cfg, "translate_cloud_batch_size", 0) or st.batch_size)
        if cloud_kind else st.batch_size
    )
    queues = plan_batches(
        items,
        loc_batch,
        source_of=lambda item: item.source,
        screen_of=lambda item: st.notes.screen(item.namespace, item.key) or item.namespace,
        short_batch=bool(getattr(cfg, "translate_short_batch", False)),
    )
    for batch in queues:
        if st.abort_run:
            break
        report_progress(st.done, len(st.work), f"batch of {len(batch)}")
        _process_batch(st, lc, ctx, batch)

    _drain_cloud_async(st, lc, ctx)
    # Free this locale's catalogue copies; later groups never read them.
    # (Pivot cache is shared across locales and stays.)
    for cache in (st.target_cache, st.ns_snapshots):
        for ck in [k for k in cache if k[0] == locale]:
            del cache[ck]
    return lc


@dataclass
class _GroupCtx:
    """Per-locale-group settings and the queued cloud async jobs."""
    threshold: float
    pivot_locale: Any
    coherence_index: Any
    use_cloud_async: bool
    pending_cloud_jobs: list = field(default_factory=list)


def _process_batch(st: _Run, lc: _Loc, ctx: _GroupCtx, batch: list[WorkItem]) -> None:
    """Glossary/TM shortcuts, payloads, budget check, then one LLM call (or queue it)."""
    cfg, report, locale, model = st.cfg, st.report, lc.locale, lc.model
    llm_items = [item for item in batch
                 if not (_try_glossary_answer(st, lc, item) or _try_tm_hit(st, lc, item))]
    if not llm_items:
        _flush_step(st)
        return

    batch_glossary = _batch_glossary(cfg, st.notes, llm_items)
    glossary_block = glossary_prompt_block(
        batch_glossary, locale, lc.language, sources=[item.source for item in llm_items],
    )
    lc.glossary_block = glossary_block
    payloads = [
        _payload(
            cfg, st.catalog, st.notes, st.pivot_cache, ctx.pivot_locale, item,
            st.native_notes.get(item.namespace), st.target_cache, locale,
            examples=st.examples_by_locale.get(locale),
            scores=st.scores,
            tm=st.tm,
            force=st.force,
            glossary=batch_glossary,
            coherence_index=ctx.coherence_index,
            ns_snapshots=st.ns_snapshots,
        )
        for item in llm_items
    ]
    llm_items, payloads = _split_blocked(st, lc, llm_items, payloads)
    if not llm_items:
        return

    has_images = any(p.image_b64 for p in payloads)
    if lc.cloud_kind:
        from ..catalog.cloud_cost import cloud_run_decision

        batch_decision = cloud_run_decision(
            cfg, [locale],
            {locale: [item.source for item in llm_items]},
            named_keys=st.named_keys,
            batch_size=1,
            enforce_keys=False,
            take_hold=False,  # run-level hold already covers the ceiling
        )
        if batch_decision.refuse:
            report(batch_decision.message)
            st.result.aborted = True
            st.abort_run = True
            return
    if lc.warm is not None:
        from ..providers.residency import ResidencyTracker, switch

        switch(lc.loc_provider, to=model, tracker=ResidencyTracker(lc.warm), report=report)
        lc.warm = None
    if ctx.use_cloud_async and len(llm_items) > 1 and not has_images:
        # Cloud async Batch: collect multi-key LLM jobs, submit once via
        # Anthropic Message Batches / OpenAI Batch (~50% off, ADR cloud cost).
        ctx.pending_cloud_jobs.append({
            "llm_items": llm_items,
            "payloads": payloads,
            "glossary_block": glossary_block,
            "glossary": batch_glossary,
            "n_samples": st.n_samples,
            "threshold": ctx.threshold,
            "llm_score": lc.score_llm,
        })
        return
    translate_fn = _translate_singles if (len(llm_items) == 1 or has_images) else _translate_batch
    results = translate_fn(
        lc.loc_provider, payloads, lc.language, locale, model, cfg,
        glossary_block, lc.register, report,
        glossary=batch_glossary, n_samples=st.n_samples, threshold=ctx.threshold,
        llm_score=lc.score_llm,
    )
    _apply_results(st, lc, llm_items, payloads, results)


def _apply_results(st: _Run, lc: _Loc, llm_items, payloads, results) -> None:
    for idx, (item, translated) in enumerate(zip(llm_items, results)):
        if _process_translation(st, lc, idx, item, translated, llm_items, payloads):
            break
    _flush_step(st)


def _drain_cloud_async(st: _Run, lc: _Loc, ctx: _GroupCtx) -> None:
    """Submit the queued cloud async jobs for this locale group, once."""
    jobs, ctx.pending_cloud_jobs = ctx.pending_cloud_jobs, []
    if not jobs:
        return
    if st.abort_run:
        # Budget refused or run aborted: queued jobs were approved one by
        # one without counting each other, so sending them could pass the
        # ceiling. Keys stay pending for the next run.
        st.report(f"skipped {len(jobs)} queued cloud batch job(s): run aborted")
        return
    result_lists = translate_cloud_async_batches(
        lc.loc_provider, jobs, lc.language, lc.locale, lc.model, st.cfg, lc.register, st.report,
    )
    for job, results in zip(jobs, result_lists):
        if st.abort_run:
            break
        _apply_results(st, lc, job["llm_items"], job["payloads"], results)


class _BtOverlap:
    """Cloud scorer with several locale groups: back-translate what a group
    produced while the next group translates. Scoring itself stays in phase B."""

    def __init__(self, st: _Run, *, multi_group: bool) -> None:
        self.st = st
        self.enabled = multi_group and st.defer_scoring
        self.prefetcher = None
        self.off = False
        self.seen = 0

    def after_group(self, lc: _Loc) -> None:
        st = self.st
        if not (self.enabled and lc.cloud_kind) or st.abort_run:
            return
        fresh = st.phase_a_written[self.seen:]
        self.seen = len(st.phase_a_written)
        if not fresh or self.off:
            return
        if self.prefetcher is None:
            from .scoring import BtPrefetcher, _CLOUD_SCORER_KINDS

            bt_provider = _bt_provider(st.cfg, fresh[0].locale, st.provider_for, st.report)
            if (getattr(bt_provider, "kind", "") in _CLOUD_SCORER_KINDS
                    and int(getattr(st.cfg, "bt_workers", 4) or 1) > 1):
                self.prefetcher = BtPrefetcher(st.cfg, bt_provider, score_model_for(st.cfg), st.report)
            else:
                self.off = True
                return
        self.prefetcher.submit(fresh)

    def close(self) -> None:
        if self.prefetcher is not None:
            self.prefetcher.close()

