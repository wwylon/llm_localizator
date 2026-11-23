"""Per-item translation steps: glossary and memory shortcuts, blocked splits, dual candidates, the item pass
(split from ``translate.py``, which re-exports these names)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..catalog import FlagStore
from .checkpoint import accept_allowed
from ..catalog.review_queue import STATUS_BLOCKED, open_review_queue
from ..core.hyphens import apply_soft_hyphens
from ..core.icu import needs_icu_decomposition
from ..core.quality import with_consistency
from ..core.standards import uses_icu
from ..core.validate import check_translation_length
from ..reporting import report_metric, report_progress
from .write_policy import hold_as_draft, hold_reason
from ._shared import WorkItem, _item_context, _item_glossary
from .ensemble import CandidateRecord, needs_secondary_pass, pick_better
from .translate_icu import _bill_cloud  # noqa: F401 (re-exported for tests)
from .translate_icu import _translate_icu_whole
from .frame_samples import has_icu_choice
from .translate_items import (
    _candidate,
    _retry_rejected,
    _shorten,
    _soft_retry,
    _translate_payload,
    reject_duplicate_batch_outputs,
)


from .recording import record_candidate
from .scoring import (
    PendingScoreItem,
    improve_score_cut,
    score_candidate,
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

if TYPE_CHECKING:
    from .translate import _Run


ICU_FAILED = "icu_failed"


def _append_flag(
    store: FlagStore,
    locale: str,
    namespace: str,
    key: str,
    reason: str,
    *,
    opened: set[tuple[str, str, str]] | None = None,
) -> None:
    store.append({
        "locale": locale, "namespace": namespace, "key": key, "reason": reason,
    })
    if opened is not None:
        opened.add((locale, namespace, key))


@dataclass
class _Loc:
    """Per-locale (and per-batch glossary) context."""
    locale: Any = None
    model: Any = None
    loc_provider: Any = None
    language: Any = None
    register: Any = None
    glossary_block: Any = None
    score_llm: Any = None
    cloud_kind: Any = None
    # Model last warmed by a secondary pass; None means the primary is warm.
    warm: Any = None

def _try_glossary_answer(st: _Run, lc: _Loc, item) -> bool:
    """A label that is one glossary term gets the approved word, no model (ADR-128)."""
    from ..core.validate import glossary_answer

    item_glossary = _item_glossary(st.cfg, st.notes, item)
    trigger = "glossary"
    answer = None
    # A person-approved translation in the key's context entry wins (ADR-137):
    # {"card.name": {"note": "...", "approved": {"pl": "{rank} {suit}"}}}. It still
    # passes the candidate gate, so a stale entry (source changed) is not written.
    entry = st.notes.entry(item.namespace, item.key)
    approved = entry.get("approved") if isinstance(entry, dict) else None
    if isinstance(approved, dict) and isinstance(approved.get(lc.locale), str):
        from .candidates import validate_candidate

        answer, _why = validate_candidate(item.source, approved[lc.locale], lc.locale, item_glossary)
        trigger = "context"
    if not answer:
        answer = glossary_answer(item.source, item_glossary, lc.locale)
        trigger = "glossary"
    if not answer:
        return False
    locale = lc.locale
    prev = st.catalog.load(locale, item.namespace).get(item.key)
    st.done += 1
    if prev == answer and not st.force:
        return True
    record_candidate(
        state=st.state, scores=st.scores, history=st.history,
        locale=locale, namespace=item.namespace, key=item.key,
        source=item.source, previous=prev, text=answer, model=trigger,
        quality_score=1.0, quality_signals=[f"{trigger} approved translation"],
        trigger=trigger, provider=trigger, scorer="heuristic",
        pending_history=st.pending_history,
        **st.notes.stale_args(item.namespace, item.key),
    )
    st.queue_write(item, answer)
    st.result.touched.add((item.namespace, locale))
    st.result.written += 1
    st.report(f"    {trigger.upper()}: {item.namespace}.{item.key}/{locale} -> {answer}")
    return True


def _try_tm_hit(st: _Run, lc: _Loc, item) -> bool:
    """Serve ``item`` from an exact TM hit; True when it was consumed (written or skipped)."""
    cfg = st.cfg
    catalog = st.catalog
    state = st.state
    history = st.history
    scores = st.scores
    tm = st.tm
    notes = st.notes
    result = st.result
    report = st.report
    force = st.force
    only_keys = st.only_keys
    trigger = st.trigger
    work = st.work
    pending = st.pending
    pending_history = st.pending_history
    target_cache = st.target_cache
    native_notes = st.native_notes
    locale = lc.locale
    model = lc.model
    context = _item_context(notes, native_notes.get(item.namespace), item)
    if not force:
        hit = tm.exact(locale, item.source, context=context)
        if hit and (hit.text or "").strip():
            item_glossary = _item_glossary(cfg, notes, item)
            accepted, reason = _candidate(cfg, 
                item.source, hit.text, locale, item_glossary,
                check_html=True if notes.html(item.namespace, item.key) else None,
            )
            if accepted is not None:
                entry_now = state.entry(locale, item.namespace, item.key)
                if not accept_allowed(
                    item.source, entry_now,
                    force=force, allow_current=only_keys is not None,
                    context=notes.stale_args(item.namespace, item.key),
                ):
                    st.done += 1
                    return True
                st.done += 1
                report_progress(
                    st.done, len(work),
                    f"{item.namespace}.{item.key} -> {item.locale} (tm)",
                )
                report_metric(done=st.done, total=len(work))
                st.consecutive_fail = 0
                prev = catalog.load(locale, item.namespace).get(item.key)
                record_candidate(
                    state=state, scores=scores, history=history,
                    locale=locale, namespace=item.namespace, key=item.key,
                    source=item.source, previous=prev, text=accepted,
                    model=hit.model or model,
                    quality_score=(
                        hit.quality_score
                        if hit.quality_score is not None
                        else 0.0
                    ),
                    quality_signals=(
                        ["tm exact hit"]
                        if hit.quality_score is not None
                        else ["tm exact hit", "tm unscored"]
                    ),
                    trigger="tm-hit",
                    provider=hit.provider or "import",
                    scorer="tm" if hit.quality_score is not None else "heuristic",
                    pending_history=pending_history,
                    **notes.stale_args(item.namespace, item.key),
                )
                st.queue_write(item, accepted)
                result.touched.add((item.namespace, locale))
                result.written += 1
                st.tm_hits += 1
                report(
                    f"    TM HIT: {item.namespace}.{item.key}/{locale}"
                )
                return True
    return False



def _split_blocked(st: _Run, lc: _Loc, llm_items, payloads):
    """Report and ticket needs_context items; return the items still to translate."""
    cfg = st.cfg
    result = st.result
    report = st.report
    work = st.work
    flag_store = st.flag_store
    flags_opened = st.flags_opened
    locale = lc.locale
    review_q = open_review_queue(cfg)
    active_items: list[WorkItem] = []
    active_payloads: list = []
    blocked_tickets: list[dict] = []
    for item, payload in zip(llm_items, payloads):
        if payload.block_translate:
            reasons = ",".join(payload.incomplete or ["needs_context"])
            report(
                f"    BLOCK needs_context: {item.namespace}.{item.key}/{locale} "
                f"-- {reasons}"
            )
            blocked_tickets.append({
                "locale": locale,
                "namespace": item.namespace,
                "key": item.key,
                "reason": f"needs_context:{reasons}",
                "source": item.source,
                "status": STATUS_BLOCKED,
            })
            _append_flag(
                flag_store, locale, item.namespace, item.key,
                f"needs_context:{reasons}",
                opened=flags_opened,
            )
            st.done += 1
            report_progress(
                st.done, len(work),
                f"{item.namespace}.{item.key} -> {item.locale} (needs_context)",
            )
            result.blocked.append(f"{locale}/{item.namespace}.{item.key}")
            continue
        active_items.append(item)
        active_payloads.append(payload)
    review_q.enqueue_many(blocked_tickets)
    llm_items = active_items
    payloads = active_payloads
    return llm_items, payloads



def _dual_candidate(st: _Run, lc: _Loc, idx: int, item, translated, quality,
                    item_glossary, max_chars, payloads):
    """Optionally generate a secondary-model candidate; return the winner.

    Returns ``(translated, quality, used_model, candidates_payload)``."""
    cfg = st.cfg
    notes = st.notes
    report = st.report
    locale = lc.locale
    model = lc.model
    loc_provider = lc.loc_provider
    language = lc.language
    register = lc.register
    glossary_block = lc.glossary_block
    score_llm = lc.score_llm
    cloud_kind = lc.cloud_kind
    used_model = model
    candidates_payload: list[dict] | None = None
    role = cfg.role_for(locale)
    if not cloud_kind and needs_secondary_pass(
        cfg, locale,
        source=item.source, translated=translated,
        quality=quality, role=role,
    ):
        secondary_model = role.secondary
        assert secondary_model  # guarded by needs_secondary_pass
        report(
            f"    dual-candidate secondary={secondary_model} "
            f"for {item.namespace}.{item.key}/{locale}"
        )
        if lc.warm != secondary_model:
            # Warm once and stay: swapping back per item reloads both models
            # for every key. The primary is re-warmed at the next batch.
            # Unload the resident primary first — on 6 GiB GPUs, loading the
            # secondary while aya is still pinned often kills Ollama.
            from ..providers.residency import ResidencyTracker, switch

            tracker = ResidencyTracker(lc.warm or model)
            switch(
                loc_provider, to=secondary_model, tracker=tracker, report=report,
            )
            lc.warm = secondary_model if secondary_model != model else None
        payload = payloads[idx]
        sec = _translate_payload(
            loc_provider, payload, language, locale, secondary_model,
            cfg, glossary_block, register, report,
            glossary=item_glossary, n_samples=1,
            threshold=improve_score_cut(cfg, scorer=quality.scorer, locale=locale),
            llm_score=score_llm,
        )
        secondary_rec: CandidateRecord | None = None
        if sec:
            sec, _reason = _candidate(cfg, 
                item.source, sec, locale, item_glossary,
                placeholder_mask=payload.placeholder_mask,
                frame_samples=payload.frame_samples,
                check_html=True if payload.html else None,
            )
            if sec is not None:
                if max_chars and len(sec) > max_chars:
                    sec = _shorten(
                        loc_provider, item, sec, language, max_chars,
                        secondary_model, cfg, glossary_block, notes,
                        register, report,
                        glossary=item_glossary,
                        check_html=True if payload.html else None,
                    )
                sec = apply_soft_hyphens(sec, locale)
                sec_quality = score_candidate(
                    loc_provider,
                    source=item.source, translated=sec, locale=locale,
                    language=language, glossary=item_glossary, cfg=cfg,
                    max_chars=max_chars,
                    message_key=payload.message_key,
                    context=payload.context,
                    llm_score=score_llm,
                )
                secondary_rec = CandidateRecord(
                    text=sec,
                    model=secondary_model,
                    score=sec_quality.score,
                    provider=cfg.provider_kind_for(locale),
                    signals=list(sec_quality.signals),
                )
        primary_rec = CandidateRecord(
            text=translated,
            model=model,
            score=quality.score,
            provider=cfg.provider_kind_for(locale),
            signals=list(quality.signals),
        )
        winner, cand_payload = pick_better(primary_rec, secondary_rec)
        candidates_payload = (
            cand_payload if secondary_rec is not None else None
        )
        if winner.model != used_model or winner.text != translated:
            translated = winner.text
            used_model = winner.model
            if secondary_rec is not None and winner.model == secondary_model:
                quality = sec_quality
    return translated, quality, used_model, candidates_payload


def _process_translation(st: _Run, lc: _Loc, idx: int, item, translated, llm_items, payloads) -> bool:
    """Validate, score, and record one generated translation; True means abort the run."""
    cfg = st.cfg
    catalog = st.catalog
    state = st.state
    history = st.history
    scores = st.scores
    tm = st.tm
    notes = st.notes
    result = st.result
    report = st.report
    force = st.force
    only_keys = st.only_keys
    trigger = st.trigger
    pre_translate = st.pre_translate
    defer_scoring = st.defer_scoring
    n_samples = st.n_samples
    work = st.work
    pending = st.pending
    pending_history = st.pending_history
    target_cache = st.target_cache
    flag_store = st.flag_store
    flags_opened = st.flags_opened
    phase_a_written = st.phase_a_written
    max_consec = st.max_consec
    locale = lc.locale
    model = lc.model
    loc_provider = lc.loc_provider
    language = lc.language
    register = lc.register
    glossary_block = lc.glossary_block
    score_llm = lc.score_llm
    cloud_kind = lc.cloud_kind
    st.done += 1
    report_progress(st.done, len(work), f"{item.namespace}.{item.key} -> {item.locale}")
    report_metric(done=st.done, total=len(work))

    item_glossary = _item_glossary(cfg, notes, item)

    secondary = None if cloud_kind else cfg.secondary_model_for(locale)
    if secondary == model:
        secondary = None

    def _escalate(why: str) -> tuple[str | None, str | None]:
        """Whole-message retry with the locale's secondary model (ADR-21)."""
        if not secondary:
            return None, why
        report(f"    ESCALATE: {item.namespace}.{item.key}/{locale} -> {secondary} -- {why}")
        if icu_choice:
            # Plural/select: the secondary gets the ICU whole-message prompt (ADR-124).
            out, why2, _dead = _translate_icu_whole(
                loc_provider, payloads[idx], language, locale, secondary, cfg,
                glossary_block, register, report, glossary=item_glossary, rejection=why,
            )
        else:
            out, why2 = _retry_rejected(
                loc_provider, payloads[idx], why, language, locale, secondary, cfg,
                glossary_block, register, report, glossary=item_glossary,
            )
        if out is not None:
            result.escalated.append(f"{locale}/{item.namespace}.{item.key}")
        return out, why2

    icu_choice = uses_icu(getattr(cfg, "catalog_standard", None)) and has_icu_choice(item.source)
    if translated is None and payloads[idx].icu_failure is not None:
        # The ICU route already tried the whole message and then fragments on the
        # primary model (ADR-124); only the secondary model is left. A final failure
        # is flagged icu_failed, not counted as a provider error, and does not
        # count toward the consecutive-reject breaker.
        translated, reason = _escalate(payloads[idx].icu_failure)
        if translated is None:
            report(f"    SKIP (icu_failed): {item.namespace}.{item.key}/{locale} -- {reason}")
            result.icu_failed.append(f"{locale}/{item.namespace}.{item.key}")
            _append_flag(
                flag_store, locale, item.namespace, item.key, ICU_FAILED,
                opened=flags_opened,
            )
            return False
    elif translated is None:
        # Soft skip (empty provider slot, provider error). Retry once, then the
        # secondary model, before giving up. A skip does not count toward the
        # consecutive-reject breaker.
        why = "the previous attempt returned nothing; translate the whole message"
        translated, reason = _retry_rejected(
            loc_provider, payloads[idx], why, language, locale, model, cfg,
            glossary_block, register, report, glossary=item_glossary,
        )
        if translated is None:
            translated, reason = _escalate(reason or why)
        if translated is None:
            report(f"    SKIP (provider): {item.namespace}.{item.key}/{locale} -- {reason}")
            result.skipped.append(f"{locale}/{item.namespace}.{item.key}")
            return False
    else:
        translated, reason = _candidate(cfg,
            item.source, translated, locale, item_glossary,
            placeholder_mask=payloads[idx].placeholder_mask,
            frame_samples=payloads[idx].frame_samples,
            check_html=True if payloads[idx].html else None,
        )
        if (translated is None and reason and uses_icu(getattr(cfg, "catalog_standard", None))
                and needs_icu_decomposition(item.source)):
            # A long ICU message rejected by the per-key gate (e.g. a forbidden term the
            # batch glossary lacked): a whole-text retry drops arguments, so go back
            # through the ICU strategies with this key's glossary (ADR-132).
            from .translate_items import _translate_icu_message

            report(f"    RETRY (ICU): {item.namespace}.{item.key}/{locale} -- {reason}")
            retried = _translate_icu_message(
                loc_provider, payloads[idx], language, locale, model, cfg, glossary_block,
                register, report, glossary=item_glossary,
            )
            if retried is not None:
                translated, reason = retried, None
        if translated is None and reason:
            report(f"    RETRY: {item.namespace}.{item.key}/{locale} -- {reason}")
            translated, reason = _retry_rejected(
                loc_provider, payloads[idx], reason, language, locale, model, cfg,
                glossary_block, register, report, glossary=item_glossary,
            )
        if translated is None and reason:
            translated, reason = _escalate(reason)
    if translated is not None and getattr(cfg, "translate_soft_retry", True):
        translated = _soft_retry(
            loc_provider, payloads[idx], item, translated, item_glossary,
            language, locale,
            model, cfg, glossary_block, register, report,
        )
    if translated is None:
        report(f"    REJECT: {item.namespace}.{item.key}/{locale} -- {reason}")
        result.rejected.append(f"{locale}/{item.namespace}.{item.key}")
        st.consecutive_fail += 1
        if max_consec and st.consecutive_fail >= max_consec:
            report(
                f"abort: {st.consecutive_fail} consecutive rejects/skips — "
                "check model/prompt (missing pin, wrong model, or few-shot bleed)"
            )
            result.aborted = True
            st.abort_run = True
            return True
        return False

    st.consecutive_fail = 0

    max_chars = notes.max_chars(item.namespace, item.key)
    warn = check_translation_length(item.source, translated, locale, max_chars)
    if warn:
        report(f"    WARN: {item.namespace}.{item.key}/{locale} -- {warn}")

    long_candidate = translated
    if max_chars and len(translated) > max_chars:
        translated = _shorten(
            loc_provider, item, translated, language, max_chars, model,
            cfg, glossary_block, notes, register, report,
            glossary=item_glossary,
            check_html=True if payloads[idx].html else None,
        )

    translated = apply_soft_hyphens(translated, locale)

    full_key = notes.full_key(item.namespace, item.key)
    unshortened_meta: list[dict] | None = None
    if (
        full_key
        and max_chars
        and locale in getattr(cfg, "length_sensitive", ["de"])
        and long_candidate != translated
    ):
        # Keep the unshortened string in history metadata only —
        # never write a sibling fullKey via this short-key path.
        unshortened_meta = [{
            "role": "unshortened",
            "fullKey": full_key,
            "text": long_candidate,
        }]

    prev = catalog.load(locale, item.namespace).get(item.key)
    if pre_translate:
        entry_now = state.entry(locale, item.namespace, item.key)
        if not accept_allowed(
            item.source, entry_now,
            force=force, allow_current=only_keys is not None,
            context=notes.stale_args(item.namespace, item.key),
        ):
            report(
                f"    SKIP {item.namespace}.{item.key}/{locale}: "
                "no longer needs write (verified or already current)"
            )
            return False
        record_candidate(
            state=state, scores=scores, history=history,
            locale=locale, namespace=item.namespace, key=item.key,
            source=item.source, previous=prev, text=translated,
            model=model, quality_score=0.0, quality_signals=[],
            trigger="pre-translate", status="machine",
            provider=cfg.provider_kind_for(locale),
            pending_history=pending_history,
            record_score=False,
            **notes.stale_args(item.namespace, item.key),
        )
        st.queue_write(item, translated)
        result.touched.add((item.namespace, locale))
        result.written += 1
        return False
    quality = score_candidate(
        loc_provider,
        source=item.source, translated=translated, locale=locale,
        language=language, glossary=item_glossary, cfg=cfg,
        max_chars=max_chars,
        message_key=(
            f"{item.namespace}.{item.key}" if item.namespace else item.key
        ),
        context=payloads[idx].context,
        llm_score=score_llm,
    )

    cut = improve_score_cut(cfg, scorer=quality.scorer, locale=locale)
    if len(llm_items) > 1 and quality.score < cut:
        payload = payloads[idx]
        alt = _translate_payload(
            loc_provider, payload, language, locale, model, cfg,
            glossary_block, register, report,
            glossary=item_glossary, n_samples=n_samples, threshold=cut,
            llm_score=score_llm,
        )
        if alt:
            alt, reason = _candidate(cfg, 
                item.source, alt, locale, item_glossary,
                placeholder_mask=payload.placeholder_mask,
                frame_samples=payload.frame_samples,
                check_html=True if payload.html else None,
            )
            if alt is not None:
                alt_quality = score_candidate(
                    loc_provider,
                    source=item.source, translated=alt, locale=locale,
                    language=language, glossary=item_glossary, cfg=cfg,
                    max_chars=max_chars,
                    message_key=payload.message_key,
                    context=payload.context,
                    llm_score=score_llm,
                )
                if alt_quality.score > quality.score:
                    translated, quality = alt, alt_quality

    translated, quality, used_model, candidates_payload = _dual_candidate(
        st, lc, idx, item, translated, quality, item_glossary, max_chars, payloads,
    )

    cut = improve_score_cut(cfg, scorer=quality.scorer, locale=locale)
    if quality.score < cut and not defer_scoring:
        reason = quality.signals[0] if quality.signals else "low quality score"
        _append_flag(
            flag_store, locale, item.namespace, item.key, reason,
            opened=flags_opened,
        )
        result.flagged_low_score.append(f"{locale}/{item.namespace}.{item.key}")
        report(f"    LOW SCORE {quality.score:.2f}: {reason}")

    if not defer_scoring:
        held = hold_reason(
            cfg, source=item.source, previous=prev,
            entry=state.entry(locale, item.namespace, item.key),
            old_score=scores.get(locale, item.namespace, item.key),
            text=translated, quality=quality,
        )
        if held:
            hold_as_draft(
                cfg, locale=locale, namespace=item.namespace, key=item.key,
                source=item.source, text=translated, score=quality.score,
                model=used_model, reason=held,
            )
            result.held.append(f"{locale}/{item.namespace}.{item.key}")
            report(f"    HOLD {item.namespace}.{item.key}/{locale}: {held} (kept as draft)")
            return False

    hist_candidates = candidates_payload
    if unshortened_meta:
        hist_candidates = list(candidates_payload or []) + unshortened_meta

    entry_now = state.entry(locale, item.namespace, item.key)
    if not accept_allowed(
        item.source, entry_now,
        force=force, allow_current=only_keys is not None,
        context=notes.stale_args(item.namespace, item.key),
    ):
        report(
            f"    SKIP {item.namespace}.{item.key}/{locale}: "
            "no longer needs write (verified or already current)"
        )
        return False
    fresh = catalog.load(locale, item.namespace).get(item.key)
    if (
        item.current and isinstance(fresh, str) and fresh != item.current
        and item.key not in pending.get((item.namespace, locale), {})
    ):
        report(
            f"    SKIP {item.namespace}.{item.key}/{locale}: "
            "target was edited outside the run; run adopt to keep it"
        )
        result.external_edit.append(f"{locale}/{item.namespace}.{item.key}")
        return False

    quality = with_consistency(quality, payloads[idx].sample_consistency)
    entry = record_candidate(
        state=state, scores=scores, history=history,
        locale=locale, namespace=item.namespace, key=item.key,
        source=item.source, previous=prev, text=translated,
        model=used_model, quality_score=quality.score,
        quality_signals=quality.signals, trigger=trigger,
        provider=cfg.provider_kind_for(locale),
        dimensions=quality.dimensions, scorer=quality.scorer,
        candidates=hist_candidates,
        pending_history=pending_history,
        **notes.stale_args(item.namespace, item.key),
    )
    tm.record(
        locale=locale,
        source=item.source,
        text=translated,
        model=used_model,
        context=payloads[idx].context,
        provider=cfg.provider_kind_for(locale),
        quality_score=quality.score,
        verified=bool(entry.get("verified_at")),
    )

    st.queue_write(item, translated)
    result.touched.add((item.namespace, locale))
    result.written += 1
    if defer_scoring:
        phase_a_written.append(PendingScoreItem(
            locale=locale,
            namespace=item.namespace,
            key=item.key,
            source=item.source,
            translated=translated,
            max_chars=max_chars,
            message_key=(
                f"{item.namespace}.{item.key}" if item.namespace else item.key
            ),
            context=payloads[idx].context,
        ))
    return False
