"""Batch, single, retry, shorten and flush helpers for the translate engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..catalog import Catalog, FlagStore, StateStore
from ..catalog.history import HistoryEvent, HistoryStore
from ..catalog.scores import ScoreStore
from ..catalog.state import state_key
from ..catalog.pricing import estimate_tokens
from ..core.icu import needs_icu_decomposition
from ..core.quality import DEFAULT_SCORE_THRESHOLD, sample_consistency
from ..core.standards import get_standard, uses_icu
from ..providers import CompletionRequest, ProviderError
from ..providers.batch import PartialBatchError
from ..reporting import log_heartbeat, report as queue_report
from .prompts import (
    BATCH_SCHEMA,
    build_batch_prompt_parts,
    build_refine_prompt,
    build_shorten_prompt,
    build_single_prompt_parts,
)
from .candidates import soft_issues as _soft_issues
from .candidates import validate_candidate as _validate_candidate
from .frame_samples import has_icu_choice
from .translate_icu import (
    _bill_cloud, _translate_icu_decomposed, _translate_icu_skeleton, _translate_icu_whole,
)
from ._shared import WorkItem


from .scoring import (
    score_candidate,
)

Reporter = Callable[[str], None]


def _candidate(cfg, source, candidate, locale, glossary, **kwargs):
    """Accept gate with the project's message standard."""
    kwargs["standard"] = get_standard(getattr(cfg, "catalog_standard", None))
    kwargs.setdefault("prompt_text", getattr(cfg, "domain", None) or None)
    return _validate_candidate(source, candidate, locale, glossary, **kwargs)


def reject_duplicate_batch_outputs(
    sources: list[str], results: list[str | None]
) -> list[str | None]:
    """Null out results that duplicate another item's text when sources differ.

    Prevents batch bleed where the model repeats one translation for many keys
    (seen on dogfood: ``saved`` / ``saveRejected`` both got the error string).
    """
    out = list(results)
    first_index: dict[str, int] = {}
    for i, (src, tr) in enumerate(zip(sources, results)):
        if tr is None:
            continue
        norm = tr.strip()
        if not norm:
            out[i] = None
            continue
        if norm in first_index:
            j = first_index[norm]
            if sources[j].strip() != src.strip() and len(norm) > 3:
                out[i] = None
        else:
            first_index[norm] = i
    return out


def _parse_batch(raw: str, expected: int) -> list[str | None]:
    from .batch_parse import parse_batch_strings
    return parse_batch_strings(raw, expected)


_DEFAULT_TOKEN_CAP = 100_000
_CLOUD_ASYNC_KINDS = frozenset({"anthropic", "openai"})


def _batch_completion_request(
    system: str,
    user: str,
    payloads,
    language: str,
    locale: str,
    model: str,
    cfg,
    schema: dict,
    *,
    custom_id: str = "",
) -> CompletionRequest:
    """Build a cache-friendly batch CompletionRequest (system + user)."""
    # Cap max_tokens to JSON-array need (plan rule 7) — ~2× source tokens + floor.
    source_chars = sum(len(p.source) for p in payloads)
    est_out = max(256, estimate_tokens(source_chars, locale) * 3 + 64 * len(payloads))
    return CompletionRequest(
        prompt=user,
        system=system,
        model=model,
        schema=schema,
        timeout_s=cfg.provider.timeout_batch_s,
        options={
            "target_lang": locale,
            "locale": locale,
            "max_tokens": est_out,
            "prompt_cache_key": f"ll:{locale}:{language}",
        },
        source_texts=[p.source for p in payloads],
        target_locale=locale,
        custom_id=custom_id,
    )


def cloud_async_batch_enabled(cfg, provider) -> bool:
    """True when TQ/cloud should prefer vendor async Batch APIs (~50% off)."""
    if not bool(getattr(cfg, "budget_cloud_batch", True)):
        return False
    kind = (getattr(provider, "kind", "") or "").strip().lower()
    return kind in _CLOUD_ASYNC_KINDS


def translate_cloud_async_batches(
    provider,
    jobs: list[dict],
    language: str,
    locale: str,
    model: str,
    cfg,
    register: str,
    report,
) -> list[list[str | None]]:
    """Run several prepared LLM batches via ``complete_many`` (Message/Batch APIs).

    Each job is ``{"payloads": [...], "glossary_block": str, "glossary": dict|None}``.
    Returns one result list per job (same shape as :func:`_translate_batch`).
    """
    if not jobs:
        return []
    requests: list[CompletionRequest] = []
    for i, job in enumerate(jobs):
        payloads = job["payloads"]
        system, user = build_batch_prompt_parts(
            payloads, language, locale, cfg.domain, job["glossary_block"],
            register=register,
            family=cfg.prompt_family_for(locale),
            style_notes=cfg.style_for(locale, model)[1],
        )
        _warn_token_budget(f"{system}\n{user}", locale, cfg, report)
        schema = {**BATCH_SCHEMA, "minItems": len(payloads), "maxItems": len(payloads)}
        requests.append(_batch_completion_request(
            system, user, payloads, language, locale, model, cfg, schema,
            custom_id=f"{locale}-{i}",
        ))
    try:
        with log_heartbeat(
            f"cloud async batch of {len(requests)} LLM call(s)",
            reporter=report,
        ):
            texts = provider.complete_many(requests)
        _bill_cloud(cfg, provider, locale, model)
    except PartialBatchError as exc:
        # Succeeded items were paid for: bill the batch and keep them; failed
        # jobs come back as all-None and are retried like any failed key.
        report(f"    WARN: cloud async batch partly failed: {exc}")
        _bill_cloud(cfg, provider, locale, model)
        texts = list(exc.results)
    except ProviderError as exc:
        report(f"    WARN: cloud async batch error: {exc}")
        return [[None] * len(job["payloads"]) for job in jobs]

    out: list[list[str | None]] = []
    for job, raw in zip(jobs, texts):
        payloads = job["payloads"]
        if raw is None:  # this job failed inside a partly-failed batch
            report("    Batch item failed -- retrying its keys one by one.")
            out.append(_translate_singles(
                provider, payloads, language, locale, model, cfg,
                job["glossary_block"], register, report,
                glossary=job.get("glossary"),
                n_samples=int(job.get("n_samples") or 1),
                threshold=float(job.get("threshold") or DEFAULT_SCORE_THRESHOLD),
                llm_score=bool(job.get("llm_score", True)),
            ))
            continue
        results = _parse_batch(raw, len(payloads))
        sources = [p.source for p in payloads]
        results = reject_duplicate_batch_outputs(sources, results)
        if any(r is not None for r in results) and any(r is None for r in results):
            report("    Duplicate/missing batch slots -- falling back per-key for gaps.")
            gap_payloads = [p for p, tr in zip(payloads, results) if tr is None]
            gap_results = _translate_singles(
                provider, gap_payloads, language, locale, model, cfg,
                job["glossary_block"], register, report,
                glossary=job.get("glossary"),
                n_samples=int(job.get("n_samples") or 1),
                threshold=float(job.get("threshold") or DEFAULT_SCORE_THRESHOLD),
                llm_score=bool(job.get("llm_score", True)),
            )
            gi = 0
            for i, tr in enumerate(results):
                if tr is None:
                    results[i] = gap_results[gi]
                    gi += 1
        elif all(r is None for r in results):
            report(
                f"    Batch failed -- falling back to per-key for {len(payloads)} items."
            )
            results = _translate_singles(
                provider, payloads, language, locale, model, cfg,
                job["glossary_block"], register, report,
                glossary=job.get("glossary"),
                n_samples=int(job.get("n_samples") or 1),
                threshold=float(job.get("threshold") or DEFAULT_SCORE_THRESHOLD),
                llm_score=bool(job.get("llm_score", True)),
            )
        out.append(results)
    return out


def _warn_token_budget(prompt: str, locale: str, cfg, report) -> None:
    cap = int(getattr(cfg, "prompt_token_cap", _DEFAULT_TOKEN_CAP))
    if cap <= 0:
        return
    estimated = estimate_tokens(len(prompt), locale)
    if estimated > cap:
        msg = (
            f"[token-budget] batch prompt is ~{estimated:,} tokens "
            f"(cap {cap:,}); consider reducing batch_size for {locale}"
        )
        (report or queue_report)(msg)


def _translate_batch(
    provider, payloads, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
    n_samples: int = 1,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    llm_score: bool = True,
) -> list[str | None]:
    if uses_icu(getattr(cfg, "catalog_standard", None)) and any(
        needs_icu_decomposition(p.source) for p in payloads
    ):
        return [
            _translate_payload(
                provider, payload, language, locale, model, cfg, glossary_block, register,
                report, glossary=glossary, n_samples=n_samples, threshold=threshold,
                llm_score=llm_score,
            )
            for payload in payloads
        ]
    system, user = build_batch_prompt_parts(
        payloads, language, locale, cfg.domain, glossary_block, register=register,
        family=cfg.prompt_family_for(locale),
        style_notes=cfg.style_for(locale, model)[1],
    )
    _warn_token_budget(f"{system}\n{user}", locale, cfg, report)
    schema = {**BATCH_SCHEMA, "minItems": len(payloads), "maxItems": len(payloads)}
    try:
        with log_heartbeat(f"translating batch of {len(payloads)}", reporter=report):
            raw = provider.complete(_batch_completion_request(
                system, user, payloads, language, locale, model, cfg, schema,
            ))
        _bill_cloud(cfg, provider, locale, model)
        results = _parse_batch(raw, len(payloads))
    except ProviderError as exc:
        # Dead provider: do not fan out to N singles (up to ~1h of timeouts).
        report(f"    WARN: batch provider error (no singles fallback): {exc}")
        return [None] * len(payloads)

    sources = [p.source for p in payloads]
    results = reject_duplicate_batch_outputs(sources, results)

    if any(r is not None for r in results) and any(r is None for r in results):
        # Partial success: retry only the nulled slots as singles.
        report("    Duplicate/missing batch slots -- falling back per-key for gaps.")
        gap_payloads = [p for p, tr in zip(payloads, results) if tr is None]
        gap_results = _translate_singles(
            provider, gap_payloads, language, locale, model, cfg, glossary_block,
            register, report, glossary=glossary, n_samples=n_samples, threshold=threshold,
            llm_score=llm_score,
        )
        gi = 0
        for i, tr in enumerate(results):
            if tr is None:
                results[i] = gap_results[gi]
                gi += 1
        return results

    if not all(r is None for r in results):
        return results

    report(f"    Batch failed -- falling back to per-key for {len(payloads)} items.")
    return _translate_singles(
        provider, payloads, language, locale, model, cfg, glossary_block, register, report,
        glossary=glossary, n_samples=n_samples, threshold=threshold,
        llm_score=llm_score,
    )


def _translate_payload(
    provider, payload, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
    n_samples: int = 1,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    llm_score: bool = True,
) -> str | None:
    if uses_icu(getattr(cfg, "catalog_standard", None)) and needs_icu_decomposition(payload.source):
        return _translate_icu_message(
            provider, payload, language, locale, model, cfg, glossary_block, register,
            report, glossary=glossary, n_samples=n_samples, threshold=threshold,
            llm_score=llm_score,
        )
    return _translate_one_with_samples(
        provider, payload, language, locale, model, cfg, glossary_block, register,
        report, glossary=glossary, n_samples=n_samples, threshold=threshold,
        llm_score=llm_score,
    )


def _translate_icu_message(
    provider, payload, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
    n_samples: int = 1,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    llm_score: bool = True,
) -> str | None:
    """Whole message first, fragments as the fallback (ADR-124).

    A plural/select message goes to the ICU whole-message prompt; a string with
    several bare placeholders goes to the ordinary single prompt (masked, with
    frame samples when short). Fragment mode runs only when that fails. On a final
    failure ``payload.icu_failure`` says why, so the engine can escalate and flag
    ``icu_failed`` instead of counting a provider error.
    """
    reason: str | None = None
    if has_icu_choice(payload.source):
        text, reason, provider_failed = _translate_icu_whole(
            provider, payload, language, locale, model, cfg, glossary_block, register,
            report, glossary=glossary,
        )
        if text is not None:
            return text
        if provider_failed:
            return None  # dead provider: fragments would only time out one by one
        report(f"    ICU whole message rejected ({reason}); trying fragment by fragment")
    else:
        cand = _translate_one_with_samples(
            provider, payload, language, locale, model, cfg, glossary_block, register,
            report, glossary=glossary, n_samples=n_samples, threshold=threshold,
            llm_score=llm_score,
        )
        if cand is not None:
            checked, reason = _candidate(
                cfg, payload.source, cand, locale, glossary or {},
                placeholder_mask=payload.placeholder_mask,
                check_html=True if payload.html else None,
                frame_samples=payload.frame_samples,
            )
            if checked is not None:
                return checked
    out = _translate_icu_decomposed(
        provider, payload, language, locale, model, cfg, glossary_block, register,
        report, glossary=glossary,
    )
    if out is None and needs_icu_decomposition(payload.source):
        out = _translate_icu_skeleton(
            provider, payload, language, locale, model, cfg, glossary_block, register,
            report, glossary=glossary,
        )
    if out is None:
        payload.icu_failure = reason or "the ICU message failed fragment by fragment"
    return out


def _translate_one_with_samples(
    provider, payload, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
    n_samples: int = 1,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    llm_score: bool = True,
) -> str | None:
    """Best-of-N (+ optional refine) for a single string."""
    opts_base = {"target_lang": locale, "locale": locale}
    vision_model = getattr(cfg, "vision_model", None)
    gen_model = vision_model if (payload.image_b64 and vision_model) else model
    candidates: list[str] = []
    for _ in range(max(1, n_samples)):
        opts = dict(opts_base)
        if n_samples >= 2:
            opts["temperature"] = 0.3
        try:
            system, user = build_single_prompt_parts(
                payload, language, cfg.domain, glossary_block, register=register,
                locale=locale, family=cfg.prompt_family_for(locale),
                style_notes=cfg.style_for(locale, model)[1],
            )
            est_out = max(128, estimate_tokens(len(payload.source), locale) * 3 + 64)
            opts = {**opts, "max_tokens": est_out, "prompt_cache_key": f"ll:{locale}"}
            text = provider.complete(CompletionRequest(
                prompt=user,
                system=system,
                model=gen_model,
                timeout_s=cfg.provider.timeout_single_s,
                options=opts,
                source_texts=[payload.source], target_locale=locale,
                images=[payload.image_b64] if payload.image_b64 else None,
            ))
            _bill_cloud(cfg, provider, locale, gen_model)
            cand = (text or "").strip()
        except ProviderError as exc:
            report(f"    WARN: {exc}")
            continue
        if not cand:
            continue
        if n_samples >= 2:
            checked, _ = _candidate(cfg, 
                payload.source, cand, locale, glossary or {},
                placeholder_mask=payload.placeholder_mask,
                frame_samples=payload.frame_samples,
                check_html=True if payload.html else None,
            )
            if checked is None:
                continue
            cand = checked
        candidates.append(cand)

    if not candidates:
        return None

    if n_samples < 2:
        return candidates[0]

    scored = [
        (c, score_candidate(
            provider,
            source=payload.source, translated=c, locale=locale,
            language=language, glossary=glossary or {}, cfg=cfg,
            max_chars=payload.max_chars,
            message_key=payload.message_key,
            context=payload.context,
            llm_score=llm_score,
        ).score)
        for c in candidates
    ]
    scored.sort(key=lambda row: row[1], reverse=True)
    best, best_score = scored[0]
    payload.sample_consistency = sample_consistency(best, candidates)

    # Refine when best is still below threshold.
    if best_score < threshold:
        refine_reason: str | None = None
        for _ in range(3):
            try:
                improved = provider.complete(CompletionRequest(
                    prompt=build_refine_prompt(
                        payload, best, language, cfg.domain, glossary_block,
                        register=register,
                        family=cfg.prompt_family_for(locale),
                        style_notes=cfg.style_for(locale, model)[1],
                        rejection=refine_reason,
                    ),
                    model=model,
                    timeout_s=cfg.provider.timeout_single_s,
                    options={**opts_base, "temperature": 0.3},
                    source_texts=[payload.source], target_locale=locale,
                ))
                _bill_cloud(cfg, provider, locale, model)
                improved = improved.strip()
            except ProviderError:
                break
            improved, refine_reason = _candidate(cfg, 
                payload.source, improved, locale, glossary or {},
                placeholder_mask=payload.placeholder_mask,
                frame_samples=payload.frame_samples,
                check_html=True if payload.html else None,
            )
            if improved is None:
                continue
            new_score = score_candidate(
                provider,
                source=payload.source, translated=improved, locale=locale,
                language=language, glossary=glossary or {}, cfg=cfg,
                max_chars=payload.max_chars,
                message_key=payload.message_key,
                context=payload.context,
                llm_score=llm_score,
            ).score
            if new_score > best_score:
                best, best_score = improved, new_score
            else:
                break
            if best_score >= threshold:
                break

    return best


def _soft_retry(
    provider, payload, item, translated, glossary, language, locale, model, cfg,
    glossary_block, register, report,
) -> str:
    """Retry once when an accepted translation carries a soft defect; keep whichever is better."""
    first = _soft_issues(item.source, translated, locale, glossary or {})
    if not first:
        return translated
    report(f"    SOFT-RETRY: {item.namespace}.{item.key}/{locale} -- {first[0]}")
    again, _ = _retry_rejected(
        provider, payload, first[0], language, locale, model, cfg, glossary_block, register,
        report, glossary=glossary,
    )
    if again is not None and len(_soft_issues(item.source, again, locale, glossary or {})) < len(first):
        return again
    return translated


def _retry_rejected(
    provider, payload, reason, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
) -> tuple[str | None, str | None]:
    """One single-item retry that tells the model why the last attempt was discarded."""
    retry = replace(payload, previous_rejection=reason)
    try:
        system, user = build_single_prompt_parts(
            retry, language, cfg.domain, glossary_block, register=register,
            locale=locale, family=cfg.prompt_family_for(locale),
            style_notes=cfg.style_for(locale, model)[1],
        )
        text = provider.complete(CompletionRequest(
            prompt=user,
            system=system,
            model=model,
            timeout_s=cfg.provider.timeout_single_s,
            options={"target_lang": locale, "locale": locale},
            source_texts=[payload.source], target_locale=locale,
        ))
        _bill_cloud(cfg, provider, locale, model)
    except ProviderError as exc:
        report(f"    WARN: {exc}")
        return None, reason
    return _candidate(
        cfg, payload.source, (text or "").strip(), locale, glossary or {},
        placeholder_mask=payload.placeholder_mask,
        frame_samples=payload.frame_samples,
        check_html=True if payload.html else None,
    )


def _translate_singles(
    provider, payloads, language, locale, model, cfg, glossary_block, register, report,
    *,
    glossary=None,
    n_samples: int = 1,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    llm_score: bool = True,
) -> list[str | None]:
    return [
        _translate_payload(
            provider, payload, language, locale, model, cfg, glossary_block, register,
            report, glossary=glossary, n_samples=n_samples, threshold=threshold,
            llm_score=llm_score,
        )
        for payload in payloads
    ]


def _shorten(provider, item, translated, language, max_chars, model,
             cfg, glossary_block, notes, register, report, *,
             glossary: dict | None = None, check_html: bool | None = None) -> str:
    prompt = build_shorten_prompt(
        item.source, translated, language, max_chars, cfg.domain, glossary_block,
        notes.note(item.namespace, item.key), register=register,
        style_notes=cfg.style_for(item.locale, model)[1],
    )
    try:
        shortened = provider.complete(CompletionRequest(
            prompt=prompt, model=model, timeout_s=cfg.provider.timeout_shorten_s,
            options={"target_lang": item.locale, "locale": item.locale},
            source_texts=[translated], target_locale=item.locale,
        ))
        _bill_cloud(cfg, provider, item.locale, model)
    except ProviderError:
        return translated

    shortened = (shortened or "").strip()
    if not shortened:
        return translated
    if len(shortened) > max_chars:
        report(f"    WARN: shorten pass still over budget "
               f"({len(shortened)} > {max_chars}), keeping original")
        return translated
    accepted, reason = _candidate(cfg, 
        item.source, shortened, item.locale, glossary or {},
        check_html=check_html,
    )
    if accepted is None:
        report(f"    WARN: shorten rejected -- {reason}")
        return translated
    return accepted


def _flush(
    cfg,
    catalog: Catalog,
    state: StateStore,
    scores: ScoreStore,
    pending: dict,
    history: HistoryStore | None = None,
    pending_history: list[tuple[str, HistoryEvent]] | None = None,
    baselines: dict | None = None,
):
    """Write pending catalogue/state/scores/history. Returns FlushResult."""
    from .checkpoint import flush_pending

    return flush_pending(
        cfg, catalog, state, scores, pending, history, pending_history,
        history_compact_every=cfg.history_compact_every,
        baselines=baselines,
    )


def _resolve_flushed_flags(
    flag_store: FlagStore,
    only_keys: dict[str, set[str]] | None,
    flushed: list[tuple[str, str, str]],
    *,
    skip: set[tuple[str, str, str]] | None = None,
) -> None:
    """Clear flags for successfully flushed keys.

    Keys that opened a flag in this same run (low score / needs_context) are
    skipped so the flag survives for improve / ``--flagged`` queues.
    """
    if not flushed:
        return
    opened = skip or set()
    flag_store.resolve_many(
        (locale, ns, key)
        for locale, ns, key in flushed
        if (locale, ns, key) not in opened
        and (only_keys is None or state_key(ns, key) in only_keys.get(locale, set()))
    )