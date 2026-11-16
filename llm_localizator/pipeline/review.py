"""LLM review pass: promote machine translations to reviewed.

A second, independent look at translations the first pass produced. Keys carry a
``status`` in the state file; this pass moves ``machine`` to ``llm_reviewed``
when the reviewer agrees, applies a correction when it offers one, and marks
``needs_better_model`` when it rejects outright -- which is the signal to route
that locale to a larger model rather than retry the same one.

The reviewer's verdict is only accepted if the corrected text still passes
:func:`validate_translation`. A reviewer that "fixes" a string by dropping a
placeholder must not be trusted over the validator.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field

from ..catalog import Catalog, StateStore
from ..catalog.history import HistoryEvent
from ..catalog.mutation_lock import project_mutation_lock
from ..core.cldr import language_name
from ..core.hash import src_hash
from ..core.quality import score_translation
from ..core.standards import get_standard
from ..core.validate import validate_translation  # noqa: F401 — kept for callers/tests
from .candidates import validate_candidate
from ..projects import ProjectConfig, glossary_prompt_block, load_glossary
from ..providers import CompletionRequest, Provider, ProviderError, metered_complete
from ..providers._prompt_utils import parse_json_array
from ..reporting import log_heartbeat, progress_line, report as default_report, report_metric, report_run_summary
from .recording import provenance_stores, record_candidate
from .run_manifest import RunManifest, config_fingerprint

__all__ = ["ReviewResult", "run_review", "STATUS_MACHINE", "STATUS_REVIEWED", "STATUS_REJECTED"]

Reporter = Callable[[str], None]

STATUS_MACHINE = "machine"
STATUS_REVIEWED = "llm_reviewed"
STATUS_REJECTED = "needs_better_model"

#: Statuses a review pass will pick up.
REVIEWABLE = frozenset({STATUS_MACHINE, STATUS_REJECTED})

#: Soft cap on EN+TR chars per review request. JSON-schema decode on small
#: local models is slow; packing by count alone still times out on long keys.
REVIEW_BATCH_CHARS = 2000

_VERDICT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "verdict": {"type": "string", "enum": ["ok", "fixed", "reject"]},
            "text": {"type": "string"},
        },
        "required": ["index", "verdict"],
    },
}


@dataclass
class ReviewResult:
    checked: int = 0
    approved: int = 0
    corrected: int = 0
    rejected: list[str] = field(default_factory=list)
    unanswered: int = 0
    unknown_keys: list[str] = field(default_factory=list)


def build_review_prompt(items: list[tuple[str, str]], language: str, domain: str,
                        glossary_block: str) -> str:
    lines = [f"{i}. EN: {en}\n   {language}: {tr}" for i, (en, tr) in enumerate(items)]
    glossary_line = f"{glossary_block}\n" if glossary_block else ""
    return (
        f"You are a senior reviewer of {language} translations for {domain}.\n"
        f"{glossary_line}"
        f"Review each numbered translation below.\n"
        f"\n"
        f"For each item return an object with:\n"
        f'  "index":   the item number exactly as shown (numbering starts at 0)\n'
        f'  "verdict": "ok" if the translation is correct and natural,\n'
        f'             "fixed" if you are supplying a better translation,\n'
        f'             "reject" if it is wrong and you cannot repair it\n'
        f'  "text":    required when verdict is "fixed" -- the corrected translation\n'
        f"\n"
        f"Rules:\n"
        f"1. Output ONLY a JSON array of {len(items)} objects.\n"
        f"2. ICU placeholders are English code identifiers in `{{name}}` form — keep every "
        f"one exactly as in the source (Latin letters, same spelling) in any correction.\n"
        f"3. Prefer 'ok' -- only correct a genuine error, not a stylistic preference.\n"
        f"\n"
        + "\n".join(lines)
    )


def run_review(
    cfg: ProjectConfig,
    catalog: Catalog,
    provider: Provider,
    *,
    locale: str,
    namespaces: list[str] | None = None,
    batch_size: int = 5,
    model: str | None = None,
    dry_run: bool = False,
    keys: list[str] | None = None,
    report: Reporter = default_report,
) -> ReviewResult:
    result = ReviewResult()
    glossary = load_glossary(cfg.glossary_path)
    stores = provenance_stores(cfg)
    state, history, scores = stores.state, stores.history, stores.scores
    language = language_name(locale)
    ns_list = namespaces or cfg.namespaces_for(catalog)
    from .improve import _parse_named_keys

    named = set(_parse_named_keys(keys, ns_list)) if keys else None

    review_model = (
        model
        or cfg.judge_model_for(locale)
        or cfg.model_for(locale)
    )

    def already_rejected(ns: str, key: str, text: str) -> bool:
        # A rejection by this same model of this same text would only repeat:
        # it waits for a larger model or a changed translation instead.
        entry = state.entry(locale, ns, key) or {}
        return (
            entry.get("status") == STATUS_REJECTED
            and entry.get("rejected_by") == review_model
            and entry.get("rejected_sha") == src_hash(text)
        )

    # Collect everything up front so progress denominators stay honest.
    pending: list[tuple[str, str, str, str]] = []  # ns, key, en, tr
    for ns in ns_list:
        source = catalog.load(cfg.source_locale, ns)
        target = catalog.load(locale, ns)

        # `needs_better_model` is re-reviewed as well as `machine`: that status
        # means a previous reviewer rejected the text outright, and the usual
        # response is to retry against a larger model rather than leave it
        # permanently unreviewed.
        pending.extend(
            (ns, key, source[key], target[key])
            for key in source
            if key in target
            and not cfg.is_skipped(ns, key)
            and (named is None or (ns, key) in named)
            and (state.entry(locale, ns, key) or {}).get("status") in REVIEWABLE
            and not already_rejected(ns, key, target[key])
        )

    if named:
        found = {(ns, key) for ns, key, _, _ in pending}
        result.unknown_keys = sorted(f"{ns}.{key}" for ns, key in named - found)
        for name in result.unknown_keys:
            report(f"  named key not reviewable for {locale}: {name}")

    glossary_block = glossary_prompt_block(
        glossary, locale, language,
        sources=[en for _, _, en, _ in pending],
    )

    total = len(pending)
    manifest = RunManifest.start(
        command="review",
        locales=[locale],
        model=review_model,
        config_hash=config_fingerprint({
            "domain": cfg.domain,
            "judge_model": getattr(cfg, "judge_model", None),
        }),
        source_locale=cfg.source_locale,
    )
    manifest.bump("work", total)
    prefix = "DRY RUN - " if dry_run else ""
    report(progress_line(0, total, f"{prefix}Reviewing {total} key(s) for {locale}"))
    if total == 0:
        report(
            "(100%) Reviewed 0: 0 approved, 0 corrected, 0 rejected."
        )
        manifest.finish(processed=0, total=0, approved=0, corrected=0, rejected=0)
        try:
            manifest.write(cfg.state_root())
            report_run_summary(manifest)
        except OSError:
            pass
        return result

    if not dry_run:
        provider.ensure_ready(review_model, report=report)

    # Queue of batches; oversized/timeout batches are split and re-queued.
    batches = _pack_review_batches(pending, max(1, batch_size))

    done = 0
    # Target catalog cache so corrections in earlier batches are visible later.
    target_cache: dict[str, dict[str, str]] = {}
    history_written_locales: set[str] = set()
    lock_cm = nullcontext() if dry_run else project_mutation_lock(cfg)

    with lock_cm:
      while batches:
        batch = batches.pop(0)
        if not dry_run:
            # `pending` was read before the lock; drop anything edited since.
            fresh = []
            for item in batch:
                if item[0] not in target_cache:
                    target_cache[item[0]] = catalog.load(locale, item[0])
                current = target_cache[item[0]].get(item[1])
                status = (state.entry(locale, item[0], item[1]) or {}).get("status")
                if current == item[3] and status in REVIEWABLE:
                    fresh.append(item)
            if len(fresh) != len(batch):
                total -= len(batch) - len(fresh)
                report(f"    skipped {len(batch) - len(fresh)} key(s) changed since the scan")
            batch = fresh
            if not batch:
                continue
        ns0 = batch[0][0]
        report(progress_line(done, total, f"batch of {len(batch)} ({ns0})"))
        result.checked += len(batch)

        if dry_run:
            done += len(batch)
            report(progress_line(done, total, f"would review {len(batch)} key(s)"))
            report_metric(done=done, total=total)
            continue

        prompt = build_review_prompt(
            [(en, tr) for _, _, en, tr in batch], language, cfg.domain, glossary_block
        )
        report(
            f"    → {review_model}: {len(batch)} key(s), {len(prompt)} chars"
        )

        def _ask(text: str, n: int) -> list[dict | None]:
            with log_heartbeat(
                f"waiting on {review_model} ({n} keys)",
                reporter=report,
            ):
                raw = metered_complete(cfg, provider, locale, CompletionRequest(
                    prompt=text, model=review_model,
                    schema=_VERDICT_SCHEMA, timeout_s=cfg.provider.timeout_batch_s,
                    options={"target_lang": locale, "locale": locale},
                ))
            return _parse(raw, n)

        try:
            verdicts = _ask(prompt, len(batch))
            missing = [i for i, v in enumerate(verdicts) if v is None]
            if missing:
                # Missing, duplicate, or out-of-range index: ask once more for
                # just those items. Never treat silence as approval.
                report(
                    f"    WARN: {len(missing)} of {len(batch)} verdict(s) missing "
                    f"or ambiguous; retrying once"
                )
                try:
                    retry = _ask(
                        build_review_prompt(
                            [(batch[i][2], batch[i][3]) for i in missing],
                            language, cfg.domain, glossary_block,
                        ),
                        len(missing),
                    )
                except ProviderError as exc:
                    # Keep what the first call answered; only the gaps stay open.
                    report(f"    WARN: retry for missing verdicts failed: {exc}")
                    retry = [None] * len(missing)
                for slot, verdict in zip(missing, retry):
                    verdicts[slot] = verdict
                left = sum(1 for v in verdicts if v is None)
                if left:
                    result.unanswered += left
                    report(f"    WARN: {left} not answered by {review_model}")
        except ProviderError as exc:
            _abort_provider(provider, review_model)
            if len(batch) > 1 and _looks_like_capacity_error(exc):
                mid = max(1, len(batch) // 2)
                report(
                    f"    WARN: review batch failed ({len(prompt)} chars, "
                    f"n={len(batch)}): {exc}; splitting into {mid}+{len(batch) - mid}"
                )
                # Undo the optimistic checked bump; halves re-count when processed.
                result.checked -= len(batch)
                batches.insert(0, batch[mid:])
                batches.insert(0, batch[:mid])
                continue
            report(
                f"    WARN: review batch failed ({len(prompt)} chars, "
                f"n={len(batch)}): {exc}"
            )
            done += len(batch)
            report(progress_line(done, total, "skipped batch after error"))
            report_metric(done=done, total=total)
            continue

        # Group updates by namespace so we rewrite each file once per batch.
        by_ns: dict[str, list[tuple[str, str, str, dict | None]]] = {}
        for (ns, key, en, tr), verdict in zip(batch, verdicts):
            by_ns.setdefault(ns, []).append((key, en, tr, verdict))

        for ns, items in by_ns.items():
            if ns not in target_cache:
                target_cache[ns] = catalog.load(locale, ns)
            source = catalog.load(cfg.source_locale, ns)
            target = target_cache[ns]

            updates: dict[str, str] = {}
            correction_scores: dict[str, tuple[float, list[str], str, dict | None]] = {}
            for key, en, tr, verdict in items:
                if verdict is None:
                    continue
                kind = verdict.get("verdict")

                if kind == "ok":
                    _set_status(state, locale, ns, key, STATUS_REVIEWED)
                    result.approved += 1
                elif kind == "fixed":
                    fixed = str(verdict.get("text", "")).strip()
                    if not fixed:
                        text, reason = None, "empty correction"
                    else:
                        text, reason = validate_candidate(
                            en, fixed, locale, glossary,
                            standard=get_standard(getattr(cfg, "catalog_standard", None)),
                        )
                    if text is None:
                        report(f"    REJECT correction for {ns}.{key}: {reason}")
                        # The reviewer judged the text wrong but could not repair it
                        # validly: surface it for a larger model, not as untouched.
                        _set_status(state, locale, ns, key, STATUS_REJECTED,
                                    rejected_by=review_model, text=tr)
                        continue
                    updates[key] = text
                    fixed = text
                    quality = score_translation(
                        en, fixed, locale, glossary,
                        standard=get_standard(getattr(cfg, "catalog_standard", None)),
                    )
                    correction_scores[key] = (quality.score, quality.signals, tr, quality.dimensions)
                    result.corrected += 1
                elif kind == "reject":
                    _set_status(state, locale, ns, key, STATUS_REJECTED,
                                rejected_by=review_model, text=tr)
                    result.rejected.append(f"{locale}/{ns}.{key}")

            if updates:
                merged = catalog.merge_for_write(source, target, updates)
                catalog.save(locale, ns, merged)
                target_cache[ns] = merged
                pending_history: list[tuple[str, HistoryEvent]] = []
                for key, (score, signals, previous, dims) in correction_scores.items():
                    record_candidate(
                        state=state, scores=scores, history=history,
                        locale=locale, namespace=ns, key=key,
                        source=source[key], previous=previous, text=updates[key],
                        model=review_model, quality_score=score,
                        quality_signals=signals, trigger="review", dimensions=dims,
                        status=STATUS_REVIEWED,
                        provider=cfg.provider_kind_for(locale),
                        pending_history=pending_history,
                    )
                state.save(locale)
                scores.save(locale)
                for hist_locale, event in pending_history:
                    history.append(hist_locale, event)
                history_written_locales.add(locale)
            else:
                state.save(locale)
                if correction_scores:
                    scores.save(locale)

        done += len(batch)
        label = f"{batch[-1][0]}.{batch[-1][1]}"
        report(progress_line(done, total, label))
        report_metric(done=done, total=total)

    for loc in history_written_locales:
        history.compact(loc)
    report(
        f"(100%) Reviewed {result.checked}: {result.approved} approved, "
        f"{result.corrected} corrected, {len(result.rejected)} rejected."
        + (f" {result.unanswered} not answered." if result.unanswered else "")
    )
    try:
        manifest.finish(
            processed=result.checked,
            total=total,
            approved=result.approved,
            corrected=result.corrected,
            rejected=len(result.rejected),
        )
        manifest.write(cfg.state_root())
        report_run_summary(manifest)
    except OSError:
        pass
    return result


def _pack_review_batches(
    pending: list[tuple[str, str, str, str]],
    batch_size: int,
    *,
    max_chars: int = REVIEW_BATCH_CHARS,
) -> list[list[tuple[str, str, str, str]]]:
    """Partition review work by count and EN+TR character budget."""
    batches: list[list[tuple[str, str, str, str]]] = []
    current: list[tuple[str, str, str, str]] = []
    chars = 0
    for item in pending:
        item_chars = len(item[2]) + len(item[3])
        would_overflow = current and (
            len(current) >= batch_size or chars + item_chars > max_chars
        )
        if would_overflow:
            batches.append(current)
            current = []
            chars = 0
        current.append(item)
        chars += item_chars
    if current:
        batches.append(current)
    return batches


def _abort_provider(provider: Provider, model: str) -> None:
    """Best-effort cancel/unload after a failed request (frees a stuck runner)."""
    stop = getattr(provider, "stop", None)
    if callable(stop):
        try:
            stop(model)
        except Exception:
            return


def _looks_like_capacity_error(exc: ProviderError) -> bool:
    """Timeouts and context overflows — worth retrying with a smaller batch."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "timed out",
            "timeout",
            "context length",
            "too long",
            "too large",
            "maximum context",
            "n_ctx",
        )
    )


def _set_status(
    state: StateStore, locale: str, ns: str, key: str, status: str,
    *, rejected_by: str | None = None, text: str | None = None,
) -> None:
    entry = state.entry(locale, ns, key)
    if entry is not None:
        entry["status"] = status
        if status == STATUS_REJECTED and rejected_by and text is not None:
            entry["rejected_by"] = rejected_by
            entry["rejected_sha"] = src_hash(text)
        else:
            entry.pop("rejected_by", None)
            entry.pop("rejected_sha", None)


def _parse(raw: str, expected: int) -> list[dict | None]:
    """Verdicts by item index. Missing, out-of-range or duplicated -> ``None``.

    A duplicated index is ambiguous (two answers for one item), so neither is
    used. Order in the array does not matter.
    """
    parsed = parse_json_array(raw)
    if parsed is None:
        return [None] * expected
    out: list[dict | None] = [None] * expected
    seen: set[int] = set()
    for item in parsed:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            index = item["index"]
            if 0 <= index < expected:
                if index in seen:
                    out[index] = None
                else:
                    out[index] = item
                seen.add(index)
    return out
