"""Slow improve loop: retranslate low-score / flagged / rejected keys.

Uses a stronger local model by default. Keeps the candidate only when the
automated quality score rises; otherwise rolls back via history/previous text.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ._shared import WorkItem, _item_context, _item_glossary
from ..catalog import Catalog, FlagStore, StateStore, build_catalog
from ..catalog.history import HistoryEvent, HistoryStore, make_history_event
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.scores import ScoreStore, quality_score_of
from ..catalog.state import is_locked, state_key, is_verified
from ..core.cldr import language_name
from ..catalog.tm import TranslationMemory
from ..core.hash import src_hash
from ..core.hyphens import apply_soft_hyphens
from ..core.quality import QualityResult, is_improvement, sample_consistency, with_consistency
from ..projects import ContextNotes, ProjectConfig, glossary_prompt_block, load_examples, load_glossary
from ..providers import CompletionRequest, Provider, ProviderError, metered_complete, score_provider_for
from ..reporting import log_heartbeat, progress_line, report_metric, report_run_summary
from .scoring import (
    backtranslate_batch,
    improve_score_cut,
    judge_model_for,
    score_candidate,
    score_model_for,
    score_with_backtranslation,
)
from .prompts import BatchItem, build_single_prompt
from ..core.standards import get_standard, uses_icu
from .candidates import validate_candidate
from .placeholder_mask import mask_bare_placeholders
from .recording import provenance_stores, record_candidate
from .run_manifest import RunManifest, config_fingerprint

__all__ = [
    "ImproveResult",
    "run_improve",
    "collect_improve_keys",
    "IMPROVE_STUCK_TRIGGERS",
]

Reporter = Callable[[str], None]

#: History triggers that mean "we already tried improve and got nothing".
IMPROVE_STUCK_TRIGGERS = frozenset({"improve-reject", "improve-fail"})


def _load_flagged(cfg: ProjectConfig) -> dict[str, set[str]]:
    return FlagStore(cfg.flags_path).grouped()


def _stuck_still_cooling(
    event: HistoryEvent | None,
    *,
    source: str,
    cooldown_hours: int,
) -> bool:
    """True when ``event`` is a recent improve KEEP/FAIL for the same source."""
    if event is None or event.trigger not in IMPROVE_STUCK_TRIGGERS:
        return False
    if event.src_sha != src_hash(source):
        return False
    if cooldown_hours <= 0:
        return True
    try:
        ts = datetime.fromisoformat(event.ts.replace("Z", "+00:00"))
    except ValueError:
        return False  # unparseable legacy timestamp — don't block re-improvement
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts < timedelta(hours=cooldown_hours)


@dataclass
class ImproveResult:
    considered: int = 0
    improved: int = 0
    kept_previous: int = 0
    failed: int = 0
    skipped_recent: int = 0
    skipped_external_edit: int = 0
    #: ``(locale, namespace, key)`` of targets edited outside the run and kept (M6: shown with editor links).
    skipped_external_keys: list[tuple[str, str, str]] = field(default_factory=list)
    dry_run: bool = False
    details: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.dry_run:
            return 0
        # Exit 1 retries the whole taskqueue job. Only do that when nothing
        # was written; a partial improve that already saved keys must exit 0.
        if self.improved == 0 and self.failed > 0:
            return 1
        return 0


def collect_improve_keys(
    cfg: ProjectConfig,
    catalog: Catalog,
    state: StateStore,
    scores: ScoreStore,
    *,
    locales: list[str],
    namespaces: list[str],
    limit: int,
    history: HistoryStore | None = None,
    include_rejected: bool = False,
    return_skipped: bool = False,
) -> list[tuple[str, str, str, str, float]] | tuple[list[tuple[str, str, str, str, float]], int]:
    """Return ``(locale, namespace, key, source, current_score)``.

    Flagged keys are preferred over merely low-scoring ones, then sorted
    ascending by score so the worst offenders come first within each group.

    Keys whose *overall* latest history event is ``improve-reject`` /
    ``improve-fail`` for the same source are skipped (cooldown) so repeated
    ``--limit N`` runs rotate through the backlog instead of re-burning the
    same stuck keys. A later successful ``improve`` clears the skip.
    Pass ``include_rejected=True`` to force a retry of those keys.

    When ``return_skipped=True``, also return how many cooldown-filtered keys
    would have been eligible without the cooldown.
    """
    lqs_cut = improve_score_cut(cfg, scorer="lqs")
    flagged = _load_flagged(cfg)
    candidates: list[tuple[str, str, str, str, float]] = []
    skipped_cooldown = 0
    skip_rejected = bool(getattr(cfg, "improve_skip_rejected", True)) and not include_rejected
    cooldown_h = int(getattr(cfg, "improve_reject_cooldown_hours", 168))
    latest_by_locale: dict[str, dict[str, HistoryEvent]] = {}

    for ns in namespaces:
        source = catalog.load(cfg.source_locale, ns)
        for locale in locales:
            target = catalog.load(locale, ns)
            if history is not None and locale not in latest_by_locale:
                latest_by_locale[locale] = history.latest_by_key(locale)
            for key, en in source.items():
                if cfg.is_skipped(ns, key, en) or key not in target or cfg.is_request_only(ns, key):
                    continue
                if not isinstance(en, str) or not en.strip():
                    continue
                sk = state_key(ns, key)
                entry = state.entry(locale, ns, key) or {}
                if is_locked(entry):
                    continue
                if is_verified(entry):
                    continue
                cooling = skip_rejected and _stuck_still_cooling(
                    latest_by_locale.get(locale, {}).get(sk),
                    source=en,
                    cooldown_hours=cooldown_h,
                )
                score_entry = scores.get(locale, ns, key) or {}
                parsed = quality_score_of(score_entry if isinstance(score_entry, dict) else None)
                score = 1.0 if parsed is None else parsed
                status = entry.get("status")
                is_flagged = sk in flagged.get(locale, set())
                cut = lqs_cut if score_entry.get("scorer") == "lqs" else improve_score_cut(
                    cfg, scorer="bt", locale=locale,
                )
                needs = status == "needs_better_model" or is_flagged or score < cut
                if not needs:
                    continue
                if cooling:
                    skipped_cooldown += 1
                    continue
                candidates.append((locale, ns, key, en, score))

    candidates.sort(
        key=lambda row: (
            0 if state_key(row[1], row[2]) in flagged.get(row[0], set()) else 1,
            row[4],
            row[0],
            row[1],
            row[2],
        )
    )
    out = candidates[:limit]
    if return_skipped:
        return out, skipped_cooldown
    return out


def parse_named_keys(
    raw: list[str] | None,
    namespaces: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Turn ``namespace.key`` strings into ``(namespace, key)`` pairs."""
    from ..catalog.state import split_operator_key

    if not raw:
        return []
    known = set(namespaces or [])
    out: list[tuple[str, str]] = []
    for item in raw:
        for part in str(item).split(","):
            part = part.strip()
            if not part:
                continue
            out.append(split_operator_key(part, known))
    return out


# Back-compat alias for callers that imported the private name.
_parse_named_keys = parse_named_keys


def collect_named_improve_keys(
    cfg: ProjectConfig,
    catalog: Catalog,
    state: StateStore,
    scores: ScoreStore,
    *,
    locales: list[str],
    named: list[tuple[str, str]],
) -> list[tuple[str, str, str, str, float]]:
    """Operator-named keys only. Skip locked and verified; ignore score gate."""
    rows: list[tuple[str, str, str, str, float]] = []
    for locale in locales:
        for ns, key in named:
            source = catalog.load(cfg.source_locale, ns)
            target = catalog.load(locale, ns)
            if key not in source or key not in target:
                continue
            en = source[key]
            if not isinstance(en, str) or not en.strip():
                continue
            if cfg.is_skipped(ns, key, en):
                continue
            entry = state.entry(locale, ns, key) or {}
            if is_locked(entry) or is_verified(entry):
                continue
            score_entry = scores.get(locale, ns, key) or {}
            parsed = quality_score_of(score_entry if isinstance(score_entry, dict) else None)
            score = 1.0 if parsed is None else parsed
            rows.append((locale, ns, key, en, score))
    return rows


def run_improve(
    cfg: ProjectConfig,
    catalog: Catalog | None = None,
    provider: Provider | None = None,
    *,
    locales: list[str] | None = None,
    namespaces: list[str] | None = None,
    limit: int | None = None,
    model: str | None = None,
    dry_run: bool = False,
    back_translate: bool = True,
    include_rejected: bool = False,
    keys: list[str] | None = None,
    report: Reporter = print,
) -> ImproveResult:
    if provider is None:
        raise ValueError("provider is required")
    from ..catalog.flush_journal import flush_block_message
    from ..projects.context import require_context_json

    blocked = flush_block_message(cfg.state_root())
    if blocked:
        report(blocked)
        return ImproveResult(failed=1, details=[blocked])
    require_context_json(cfg.context_dir)
    catalog = catalog or build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale
    )
    glossary = load_glossary(cfg.glossary_path)
    examples_by_locale = load_examples(cfg.examples_file)
    notes = ContextNotes(cfg.context_dir)
    stores = provenance_stores(cfg)
    state, history, scores = stores.state, stores.history, stores.scores
    tm = cfg.open_tm()
    improve_model = model or cfg.improve_model or cfg.model_for("")
    cap = limit if limit is not None else getattr(cfg, "improve_limit", 50)
    n_samples = max(
        1, int(getattr(cfg, "improve_multi_sample", None) or getattr(cfg, "multi_sample", 1))
    )

    targets = cfg.resolve_locales(locales)
    ns_list = namespaces if namespaces is not None else cfg.namespaces_for(catalog)
    named = _parse_named_keys(keys, ns_list)

    if named:
        work = collect_named_improve_keys(
            cfg, catalog, state, scores, locales=targets, named=named,
        )
        skipped_recent = 0
    else:
        work, skipped_recent = collect_improve_keys(
            cfg, catalog, state, scores,
            locales=targets, namespaces=ns_list, limit=cap,
            history=history, include_rejected=include_rejected,
            return_skipped=True,
        )
    result = ImproveResult(
        considered=len(work), dry_run=dry_run, skipped_recent=skipped_recent,
    )
    manifest = RunManifest.start(
        command="improve",
        locales=targets,
        model=improve_model,
        config_hash=config_fingerprint({
            "domain": cfg.domain,
            "improve_model": improve_model,
        }),
        source_locale=cfg.source_locale,
    )
    manifest.bump("work", len(work))
    from .run_context import RunContext

    run_ctx = RunContext(run_id=manifest.run_id)
    if not work:
        extra = f" ({skipped_recent} cooling from prior KEEP/FAIL)" if skipped_recent else ""
        report(progress_line(0, 0, f"No low-score / flagged keys to improve.{extra}"))
        manifest.finish(written=0, total=0, improved=0, kept_previous=0, failed=0)
        try:
            manifest.write(cfg.state_root())
            report_run_summary(manifest)
        except OSError:
            pass
        return result

    skip_note = f", skipping {skipped_recent} recent KEEP/FAIL" if skipped_recent else ""
    prefix = "DRY RUN - " if dry_run else ""
    total = len(work)
    report(progress_line(
        0, total,
        f"{prefix}Improving {total} key(s) with {improve_model}{skip_note}",
    ))
    if dry_run:
        for locale, ns, key, _en, score in work:
            report(f"  would improve {locale}/{ns}.{key} (score={score:.2f})")
        return result

    provider.ensure_ready(improve_model, report=report)

    flagged = _load_flagged(cfg)
    pending: dict[tuple[str, str], dict[str, str]] = {}
    register = getattr(cfg, "register", "informal")

    with project_mutation_lock(cfg):
        # Keys were collected before the lock; another process may have locked
        # or verified them since. State reads are mtime-cached, so this is fresh.
        work = [
            w for w in work
            if not _protected(state.entry(w[0], w[1], w[2]) or {})
        ]
        return _run_improve_locked(
            cfg=cfg,
            catalog=catalog,
            provider=provider,
            scorer=score_provider_for(cfg, report=report) or provider,
            work=work,
            result=result,
            manifest=manifest,
            glossary=glossary,
            examples_by_locale=examples_by_locale,
            notes=notes,
            state=state,
            history=history,
            scores=scores,
            tm=tm,
            improve_model=improve_model,
            n_samples=n_samples,
            back_translate=back_translate,
            flagged=flagged,
            pending=pending,
            register=register,
            total=total,
            report=report,
            run_ctx=run_ctx,
        )


def _protected(entry: dict) -> bool:
    if is_locked(entry) or is_verified(entry):
        return True
    # Hand-edited strings stay unless force/explicit; ADR-48 status=human.
    return str(entry.get("status") or "") == "human"


class _Flusher:
    """Batches improve writes: at most one batch is lost on a kill (not one key)."""

    def __init__(
        self, cfg, catalog, state, history, scores, pending, flush_every: int,
        *, run_id: str | None = None,
    ) -> None:
        self.cfg, self.catalog, self.state = cfg, catalog, state
        self.history, self.scores, self.pending = history, scores, pending
        self.flush_every = flush_every
        self.run_id = run_id
        self.pending_history: list[tuple[str, HistoryEvent]] = []
        self.baselines: dict[tuple[str, str], dict[str, str | None]] = {}
        self.dirty_score_locales: set[str] = set()
        self.pending_flag_resolves: list[tuple[str, str, str]] = []
        #: ``((locale, ns, key), record)``: TM writes held until the flush says the key was written.
        self.pending_tm: list[tuple[tuple[str, str, str], Callable[[], None]]] = []
        self.since_flush = 0
        self.skipped_external_at_flush = 0
        self.skipped_external_keys: list[tuple[str, str, str]] = []

    def queue_write(self, ns: str, locale: str, key: str, text: str, baseline: str | None) -> None:
        slot = (ns, locale)
        self.pending.setdefault(slot, {})[key] = text
        self.baselines.setdefault(slot, {})[key] = baseline

    def has_work(self) -> bool:
        return bool(
            self.pending or self.pending_history
            or self.dirty_score_locales or self.pending_flag_resolves or self.pending_tm
        )

    def flush(self) -> None:
        from .checkpoint import flush_pending

        outcome = flush_pending(
            self.cfg, self.catalog, self.state, self.scores,
            self.pending, self.history, self.pending_history,
            use_journal=True,
            history_compact_every=self.flush_every,
            baselines=self.baselines,
            run_id=self.run_id,
        )
        skipped = list(getattr(outcome, "skipped_external", None) or [])
        self.skipped_external_at_flush += len(skipped)
        self.skipped_external_keys.extend(skipped)
        keep = {(loc, n, k) for loc, n, k in skipped}
        if skipped:
            self.pending_flag_resolves = [
                row for row in self.pending_flag_resolves if row not in keep
            ]
        # Scores and TM only for keys the flush actually wrote (M0, audit ops #10): a key edited outside the run
        # keeps the outside text, so the candidate's score and TM entry would describe text that is not there.
        for loc, n, k in skipped:
            self.scores.forget(loc, n, k)
        for loc in sorted(self.dirty_score_locales):
            self.scores.save(loc)
        self.dirty_score_locales.clear()
        for slot, record in self.pending_tm:
            if slot not in keep:
                record()
        self.pending_tm.clear()
        if self.pending_flag_resolves:
            FlagStore(self.cfg.flags_path).resolve_many(self.pending_flag_resolves)
            self.pending_flag_resolves.clear()
        self.since_flush = 0

    def tick(self) -> None:
        self.since_flush += 1
        if self.since_flush >= self.flush_every:
            self.flush()


def _generate_candidates(
    cfg, provider, notes, glossary, examples_by_locale, improve_model, n_samples, report,
    *, locale, ns, key, en, language, glossary_block, register, style_notes, label,
):
    """Sample ``n_samples`` valid candidates; returns (payload, candidates, last_error, saw_invalid)."""
    icu = uses_icu(getattr(cfg, "catalog_standard", None))
    if icu:
        masked_source, ph_mask = mask_bare_placeholders(en)
    else:
        masked_source, ph_mask = en, {}
    from ..core.glossary_match import format_glossary_annotation, glossary_hits

    payload = BatchItem(
        source=en,
        prompt_source=masked_source if ph_mask else None,
        placeholder_mask=ph_mask or None,
        context=notes.note(ns, key),
        llm_note=notes.llm_note(ns, key),
        max_chars=notes.max_chars(ns, key),
        examples=examples_by_locale.get(locale),
        message_key=f"{ns}.{key}" if ns else key,
        html=notes.html(ns, key),
        glossary_note=format_glossary_annotation(
            glossary_hits(en, glossary, locale),
        ),
    )
    if not icu:
        spec = get_standard(cfg.catalog_standard)
        payload.native_standard = True
        payload.preserve_tokens = tuple(sorted(spec.tokens(en)))
    max_chars = notes.max_chars(ns, key)

    # Best-of-N: the improve loop already pays for a stronger model, so a
    # few independent samples (higher temperature past the first) scored
    # against back-translation buys extra quality cheaply.
    raw_candidates: list[str] = []
    last_error: ProviderError | None = None
    saw_invalid = False
    with log_heartbeat(f"improving {label}", reporter=report):
        for sample_idx in range(n_samples):
            opts = {"target_lang": locale, "locale": locale}
            if sample_idx > 0:
                opts["temperature"] = 0.3
            try:
                raw = metered_complete(cfg, provider, locale, CompletionRequest(
                    prompt=build_single_prompt(
                        payload, language, cfg.domain, glossary_block, register=register,
                        locale=locale, family=cfg.prompt_family_for(locale),
                        style_notes=style_notes,
                    ),
                    model=improve_model,
                    timeout_s=cfg.provider.timeout_single_s,
                    options=opts,
                    source_texts=[en], target_locale=locale,
                ))
            except ProviderError as exc:
                last_error = exc
                continue
            cand, reason = validate_candidate(
                en, (raw or "").strip(), locale, glossary,
                placeholder_mask=payload.placeholder_mask,
                check_html=True if payload.html else None,
                standard=get_standard(getattr(cfg, "catalog_standard", None)),
            )
            if cand is None:
                saw_invalid = True
                continue
            raw_candidates.append(apply_soft_hyphens(cand, locale))
    return payload, raw_candidates, last_error, saw_invalid


def _score_candidates(
    cfg, provider, scores, glossary, report, dirty_score_locales, back_translate,
    *, locale, ns, key, en, old_score, prev, language, max_chars, payload, raw_candidates, label,
):
    """Score the stored text and the candidates; returns (candidate, quality, baseline, baseline_dims)."""
    with log_heartbeat(f"scoring {label}", reporter=report):
        texts_to_score: list[str] = []
        if (prev or "").strip():
            texts_to_score.append(prev)
        texts_to_score.extend(raw_candidates)

        backs: list[str | None] | None = None
        if (
            back_translate
            and not judge_model_for(cfg, locale)
            and len(texts_to_score) > 1
        ):
            backs = backtranslate_batch(
                provider,
                texts_to_score,
                language,
                score_model_for(cfg),
                cfg,
            )

        def _score_one(text: str, back_idx: int) -> QualityResult:
            if backs is not None:
                return score_with_backtranslation(
                    provider,
                    source=en, translated=text, locale=locale,
                    language=language, glossary=glossary, cfg=cfg,
                    max_chars=max_chars,
                    back_translated=backs[back_idx] if back_idx < len(backs) else None,
                )
            return score_candidate(
                provider, source=en, translated=text, locale=locale,
                language=language, glossary=glossary, cfg=cfg,
                max_chars=max_chars,
                message_key=payload.message_key,
                context=payload.context,
            )

        offset = 0
        baseline = old_score
        baseline_dims = None
        if (prev or "").strip():
            prev_quality = _score_one(prev, offset)
            offset += 1
            baseline = prev_quality.score
            baseline_dims = prev_quality.dimensions
            if back_translate:
                scores.record(
                    locale, ns, key,
                    score=baseline, signals=prev_quality.signals, text=prev,
                    dimensions=prev_quality.dimensions, scorer=prev_quality.scorer,
                )
                dirty_score_locales.add(locale)

        if len(raw_candidates) == 1:
            candidate = raw_candidates[0]
            quality = _score_one(candidate, offset)
        else:
            scored_candidates = [
                (c, _score_one(c, offset + i))
                for i, c in enumerate(raw_candidates)
            ]
            scored_candidates.sort(key=lambda row: row[1].score, reverse=True)
            candidate, quality = scored_candidates[0]
            quality = with_consistency(quality, sample_consistency(candidate, raw_candidates))
    return candidate, quality, baseline, baseline_dims


def decide_accept(cfg, locale: str, quality, baseline: float, baseline_dims, *, is_flagged: bool) -> str:
    """``improved`` when the candidate beats the baseline, ``flagged`` when a human-flagged key clears the cut
    anyway, else ``keep`` (M3: the decision, split from run_improve's bookkeeping).

    Human-flagged keys: the stored/back-translation baseline can still be inflated (short calques score high), so
    any valid candidate that clears the quality threshold is accepted — the flag is a veto of the current string.
    """
    if is_improvement(quality.score, quality.dimensions, baseline, baseline_dims):
        return "improved"
    if is_flagged and quality.score >= improve_score_cut(cfg, scorer=quality.scorer, locale=locale):
        return "flagged"
    return "keep"


def _run_improve_locked(
    *,
    cfg,
    catalog,
    provider,
    scorer=None,
    work,
    result,
    manifest,
    glossary,
    examples_by_locale,
    notes,
    state,
    history,
    scores,
    tm,
    improve_model,
    n_samples,
    back_translate,
    flagged,
    pending,
    register,
    total,
    report,
    run_ctx,
) -> ImproveResult:
    # Batch flush: at most one batch lost on kill (not one key).
    flush_every = max(1, cfg.history_compact_every)
    fl = _Flusher(
        cfg, catalog, state, history, scores, pending, flush_every,
        run_id=run_ctx.flush_run_id,
    )

    for idx, (locale, ns, key, en, old_score) in enumerate(work, start=1):
        register, style_notes = cfg.style_for(locale, cfg.model_for(locale))
        language = language_name(locale)
        # Same per-key glossary as translate: domain terms for this namespace
        # and key, shared glossaries merged by the configured conflict rule.
        item = WorkItem(namespace=ns, locale=locale, key=key, source=en)
        item_glossary = _item_glossary(cfg, notes, item) if cfg.glossary_path else glossary
        glossary_block = glossary_prompt_block(
            item_glossary, locale, language, sources=[en],
        )
        existing = catalog.load(locale, ns)
        prev = existing.get(key, "")
        is_flagged = state_key(ns, key) in flagged.get(locale, set())
        label = f"{locale}/{ns}.{key}"
        progress = progress_line(idx, total, label)
        report(progress)
        report_metric(done=idx, total=total)
        payload, raw_candidates, last_error, saw_invalid = _generate_candidates(
            cfg, provider, notes, item_glossary, examples_by_locale, improve_model, n_samples, report,
            locale=locale, ns=ns, key=key, en=en, language=language,
            glossary_block=glossary_block, register=register, style_notes=style_notes,
            label=label,
        )
        max_chars = payload.max_chars

        if not raw_candidates:
            report(
                f"  {progress} FAIL {locale}/{ns}.{key}: "
                f"{last_error or 'no valid candidate'}"
            )
            result.failed += 1
            trigger = (
                "improve-error"
                if last_error is not None and not saw_invalid
                else "improve-fail"
            )
            fl.pending_history.append((locale, make_history_event(
                namespace=ns, key=key, prev=prev, next_text=prev or "",
                model=improve_model, status="machine",
                src_sha=src_hash(en), trigger=trigger,
                quality_score=old_score,
                provider=cfg.provider_kind_for(locale),
            )))
            fl.tick()
            continue

        candidate, quality, baseline, baseline_dims = _score_candidates(
            cfg, scorer or provider, scores, item_glossary, report, fl.dirty_score_locales, back_translate,
            locale=locale, ns=ns, key=key, en=en, old_score=old_score, prev=prev,
            language=language, max_chars=max_chars, payload=payload,
            raw_candidates=raw_candidates, label=label,
        )

        decision = decide_accept(cfg, locale, quality, baseline, baseline_dims, is_flagged=is_flagged)
        if decision == "keep":
            report(
                f"  {progress} KEEP {locale}/{ns}.{key}: new {quality.score:.2f} not better than "
                f"baseline {baseline:.2f} (stored {old_score:.2f})"
            )
            result.kept_previous += 1
            fl.pending_history.append((locale, make_history_event(
                namespace=ns, key=key, prev=prev, next_text=prev,
                model=improve_model, status="machine",
                src_sha=src_hash(en), trigger="improve-reject",
                quality_score=baseline,
                provider=cfg.provider_kind_for(locale),
            )))
            fl.dirty_score_locales.add(locale)
            fl.tick()
            continue
        if decision == "flagged":
            report(
                f"  {progress} IMPROVED {locale}/{ns}.{key}: flagged accept "
                f"{quality.score:.2f} (baseline {baseline:.2f}, stored {old_score:.2f})"
            )
        else:
            report(
                f"  {progress} IMPROVED {locale}/{ns}.{key}: "
                f"{baseline:.2f} -> {quality.score:.2f} "
                f"(stored was {old_score:.2f})"
            )

        fresh = catalog.load(locale, ns).get(key, "")
        if prev and fresh != prev and key not in pending.get((ns, locale), {}):
            report(
                f"  {progress} SKIP {locale}/{ns}.{key}: "
                "target was edited outside the run; run adopt to keep it"
            )
            result.skipped_external_edit += 1
            result.skipped_external_keys.append((locale, ns, key))
            fl.tick()
            continue
        fl.queue_write(ns, locale, key, candidate, prev if isinstance(prev, str) else None)
        record_candidate(
            state=state, scores=scores, history=history,
            locale=locale, namespace=ns, key=key, source=en, previous=prev,
            text=candidate, model=improve_model, quality_score=quality.score,
            quality_signals=quality.signals, trigger="improve",
            provider=cfg.provider_kind_for(locale),
            dimensions=quality.dimensions, scorer=quality.scorer,
            pending_history=fl.pending_history,
            **notes.stale_args(ns, key),
        )
        fl.dirty_score_locales.add(locale)
        context = _item_context(notes, None, item)
        tm_args = dict(
            locale=locale, source=en, text=candidate, model=improve_model,
            context=context, provider=cfg.provider_kind_for(locale),
            quality_score=quality.score,
        )
        fl.pending_tm.append(((locale, ns, key), functools.partial(tm.record, **tm_args)))
        result.improved += 1
        result.details.append(
            f"{locale}/{ns}.{key}: {baseline:.2f} -> {quality.score:.2f}"
        )
        if is_flagged:
            fl.pending_flag_resolves.append((locale, ns, key))
        fl.tick()

    if fl.has_work():
        fl.flush()
    if fl.skipped_external_at_flush:
        result.skipped_external_edit += fl.skipped_external_at_flush
        result.skipped_external_keys.extend(fl.skipped_external_keys)
        result.improved = max(0, result.improved - fl.skipped_external_at_flush)

    skip_part = (
        f", {result.skipped_recent} cooling from prior KEEP/FAIL"
        if result.skipped_recent else ""
    )
    if result.skipped_external_edit:
        skip_part += f", {result.skipped_external_edit} edited outside the run (kept; run adopt)"
    report(progress_line(
        total, total,
        f"Improve done: {result.improved} improved, "
        f"{result.kept_previous} kept previous, {result.failed} failed "
        f"of {result.considered}{skip_part}",
    ))
    try:
        manifest.finish(
            written=result.improved,
            total=total,
            improved=result.improved,
            kept_previous=result.kept_previous,
            failed=result.failed,
            skipped_recent=result.skipped_recent,
            skipped_external_edit=result.skipped_external_edit,
        )
        manifest.write(cfg.state_root())
        report_run_summary(manifest)
    except OSError:
        pass
    return result
