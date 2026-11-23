"""Shared scoring helpers for translate, improve, and rescore (ADR-20)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..catalog import Catalog, StateStore
from ..catalog.pricing import CLOUD_DEFAULT_MODEL
from ..catalog.scores import ScoreStore, score_matches_text
from ..core.cldr import language_name
from ..core.quality import (
    QualityResult,
    quality_band,
    score_translation,
    token_overlap,
)
from ..core.standards import get_standard
from ..catalog.state import needs_translation, state_key
from ..projects import ProjectConfig, glossary_prompt_block
from ..providers import CompletionRequest, Provider, ProviderError, metered_complete
from ..reporting import log_heartbeat, report_metric, report_progress
from .judge import judge_translation, quality_from_judge
from .prompts import build_backtranslate_prompt, build_batch_backtranslate_prompt

__all__ = [
    "PendingScoreItem",
    "score_model_for",
    "judge_model_for",
    "backtranslate",
    "backtranslate_batch",
    "score_with_backtranslation",
    "score_heuristic",
    "score_candidate",
    "improve_score_cut",
    "should_defer_scoring_for_translate",
    "collect_pending_llm_scores",
    "rescore_items",
    "run_deferred_scoring_phase",
]


Reporter = Callable[[str], None]


#: rescore persists scores at least this often (keys), so a crash keeps work.
RESCORE_SAVE_EVERY = 50


@dataclass(frozen=True)
class PendingScoreItem:
    locale: str
    namespace: str
    key: str
    source: str
    translated: str
    max_chars: int | None = None
    message_key: str = ""
    context: str = ""


#: Cloud scorers (DeepL translates only, it cannot score).
_CLOUD_DEFAULTS = {k: v for k, v in CLOUD_DEFAULT_MODEL.items() if k != "deepl"}


def score_model_for(cfg: ProjectConfig) -> str:
    """Model used for back-translation scoring (never the translator by default)."""
    explicit = getattr(cfg, "score_model", None)
    if explicit:
        return explicit
    kind = score_provider_kind(cfg)
    if kind in _CLOUD_DEFAULTS:
        # A cloud scorer never inherits a local translator or improve tag.
        return _CLOUD_DEFAULTS[kind]
    model = cfg.improve_model
    if model:
        return model
    return cfg.model_for("")


def score_provider_kind(cfg: ProjectConfig) -> str | None:
    """Provider kind named by ``[quality] score_provider``, or None when unset."""
    ref = (getattr(cfg, "score_provider", None) or "").strip()
    if not ref:
        return None
    entry = (getattr(cfg, "providers", None) or {}).get(ref)
    return (getattr(entry, "kind", None) or ref) if entry is not None else ref


def judge_model_for(cfg: ProjectConfig, locale: str = "") -> str | None:
    """Configured LQS judge model, or None to keep BT-only scoring."""
    if hasattr(cfg, "judge_model_for"):
        return cfg.judge_model_for(locale)
    model = getattr(cfg, "judge_model", None)
    if isinstance(model, str) and model.strip():
        return model.strip()
    return None


def improve_score_cut(cfg: ProjectConfig, *, scorer: str, locale: str | None = None) -> float:
    """Score below which translate flags / improve targets the key.

    ``[quality.thresholds]`` overrides the global back-translation cut for one locale;
    the judge (LQS) cut stays band-based.
    """
    if scorer == "lqs":
        return float(getattr(cfg, "band_retranslate", 0.80))
    per_locale = getattr(cfg, "quality_thresholds", None) or {}
    if locale and locale in per_locale:
        return float(per_locale[locale])
    return float(getattr(cfg, "quality_threshold", 0.55))


def should_defer_scoring_for_translate(
    cfg: ProjectConfig,
    pin_model: str,
    *,
    n_samples: int = 1,
) -> bool:
    """True when LLM scoring should run in a second GPU phase after translate.

    Defer when the back-translation *or* judge model differs from the pinned
    translator — otherwise each key swaps models on a 6 GiB GPU and kills Ollama.
    """
    explicit = getattr(cfg, "defer_scoring", None)
    if explicit is False:
        return False
    if explicit is True:
        return True
    from ..providers.preflight import looks_like_cloud_model

    # A cloud translator never scores inline (translate turns llm_score off for cloud locales), and a
    # separate [quality] score_provider only runs as phase B: without deferral nothing would score at all.
    if score_provider_kind(cfg) or looks_like_cloud_model(pin_model):
        return True
    if n_samples >= 2:
        return False
    if score_model_for(cfg) != pin_model:
        return True
    judge = judge_model_for(cfg)
    return bool(judge and judge != pin_model)


def _needs_llm_rescore(
    row: dict | None,
    *,
    translated: str,
    source: str,
    entry: dict | None,
) -> bool:
    if entry is None or needs_translation(source, entry, force=False):
        return False
    if row is None:
        return True
    if row.get("scorer") == "heuristic":
        return True
    if not score_matches_text(row, translated):
        return True
    return False


def collect_pending_llm_scores(
    cfg: ProjectConfig,
    catalog: Catalog,
    state: StateStore,
    scores: ScoreStore,
    *,
    locales: list[str],
    namespaces: list[str],
    only_keys: dict[str, set[str]] | None = None,
) -> list[PendingScoreItem]:
    """Keys with catalogue text but provisional/missing LLM scores (restart path).

    ``only_keys`` (locale -> state keys) limits the scan to an explicit key run."""
    pending: list[PendingScoreItem] = []
    for locale in locales:
        allowed = only_keys.get(locale, set()) if only_keys is not None else None
        for ns in namespaces:
            source_map = catalog.load(cfg.source_locale, ns)
            target_map = catalog.load(locale, ns)
            for key, src in source_map.items():
                if allowed is not None and state_key(ns, key) not in allowed:
                    continue
                if cfg.is_skipped(ns, key, src) or not isinstance(src, str) or not src.strip():
                    continue
                if allowed is None and cfg.is_request_only(ns, key):
                    continue
                translated = target_map.get(key)
                if not isinstance(translated, str) or not translated.strip():
                    continue
                entry = state.entry(locale, ns, key)
                row = scores.get(locale, ns, key)
                if not _needs_llm_rescore(
                    row, translated=translated, source=src, entry=entry,
                ):
                    continue
                pending.append(PendingScoreItem(
                    locale=locale,
                    namespace=ns,
                    key=key,
                    source=src,
                    translated=translated,
                ))
    return pending


def score_heuristic(
    *,
    source: str,
    translated: str,
    locale: str,
    glossary: dict,
    max_chars: int | None = None,
    standard=None,
) -> QualityResult:
    """CPU-only structural/heuristic score (phase A when deferring LLM scoring)."""
    return score_translation(
        source, translated, locale, glossary, max_chars=max_chars, standard=standard,
    )


def backtranslate(
    provider: Provider,
    text: str,
    language: str,
    model: str,
    cfg: ProjectConfig,
    *,
    bill_locale: str | None = None,
) -> str | None:
    """Back-translate ``text`` to English; return None on failure."""
    if not (text or "").strip():
        return None
    try:
        raw = metered_complete(
            cfg, provider, bill_locale or getattr(cfg, "source_locale", "en") or "en",
            CompletionRequest(
                prompt=build_backtranslate_prompt(text, language),
                model=model,
                timeout_s=cfg.provider.timeout_single_s,
                options={"target_lang": "en", "locale": "en"},
                source_texts=[text], target_locale="en",
            ),
        )
        return (raw or "").strip()
    except ProviderError:
        return None


def backtranslate_batch(
    provider: Provider,
    texts: list[str],
    language: str,
    model: str,
    cfg: ProjectConfig,
    *,
    bill_locale: str | None = None,
) -> list[str | None]:
    """Back-translate a batch; fall back to single-key calls on parse failure."""
    cleaned = [(t or "").strip() for t in texts]
    if not cleaned or not any(cleaned):
        return [None] * len(texts)
    locale = bill_locale or getattr(cfg, "source_locale", "en") or "en"
    if len(cleaned) == 1:
        return [backtranslate(
            provider, cleaned[0], language, model, cfg, bill_locale=locale,
        )]

    numbered = list(enumerate(cleaned))
    try:
        raw = metered_complete(
            cfg, provider, locale,
            CompletionRequest(
                prompt=build_batch_backtranslate_prompt(numbered, language),
                model=model,
                timeout_s=cfg.provider.timeout_batch_s,
                options={"target_lang": "en", "locale": "en"},
                source_texts=cleaned,
                target_locale="en",
                schema={"type": "array", "items": {"type": "string"}},
            ),
        )
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, list) and len(parsed) == len(cleaned):
                return [str(v).strip() if v is not None else None for v in parsed]
    except (ProviderError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return [
        backtranslate(provider, text, language, model, cfg, bill_locale=locale)
        if text else None
        for text in cleaned
    ]


_PLACEHOLDER = re.compile(r"\{[^{}]*\}|%\(?\w*\)?[sdif]|\$\{[^}]*\}")
#: Score ceiling when a short source's back-translation shares no word with it (C3).
CONTRADICTION_CAP = 0.6


def is_risky_key(source: str) -> bool:
    """One or two words outside placeholders: labels, buttons and frames.

    Back-translation overlap on one word is trivially high or zero, so the BT score
    says little; these are the keys a judge should look at ("Zmniejsz" for "make big",
    "Zrzutka" for "Discard").
    """
    words = re.findall(r"[^\W\d_]+", _PLACEHOLDER.sub(" ", source or ""))
    return 0 < len(words) <= 2


def apply_contradiction_cap(quality: QualityResult, source: str, back: str | None) -> QualityResult:
    """A short source whose back-translation shares no word cannot score high."""
    if back is None or not is_risky_key(source) or token_overlap(source, back) > 0:
        return quality
    if quality.score <= CONTRADICTION_CAP:
        return quality
    quality.signals = list(quality.signals) + [
        f"contradiction: back-translation {back[:40]!r} shares no word with the source; "
        f"score capped at {CONTRADICTION_CAP}",
    ]
    quality.score = CONTRADICTION_CAP
    return quality


def risky_judge_model(cfg: ProjectConfig, locale: str, source: str) -> str | None:
    """The judge model for this key: the configured judge, else the scoring model for
    risky keys when ``[quality] judge_risky`` is on (default)."""
    configured = judge_model_for(cfg, locale)
    if configured:
        return configured
    if getattr(cfg, "judge_risky", True) and is_risky_key(source):
        return score_model_for(cfg)
    return None


def score_with_backtranslation(
    provider: Provider,
    *,
    source: str,
    translated: str,
    locale: str,
    language: str,
    glossary: dict,
    cfg: ProjectConfig,
    model: str | None = None,
    max_chars: int | None = None,
    back_translated: str | None = None,
) -> QualityResult:
    """Score one candidate with back-translation (BT path).

    ``model`` overrides the BT model only when neither ``score_model`` nor
    ``improve_model`` is configured — generation tags must not silently replace
    the scorer (ADR-20).
    """
    if getattr(cfg, "score_model", None) or cfg.improve_model:
        bt_model = score_model_for(cfg)
    else:
        bt_model = model or score_model_for(cfg)
    back = back_translated
    if back is None:
        back = backtranslate(
            provider, translated, language, bt_model, cfg, bill_locale=locale,
        )
    quality = score_translation(
        source, translated, locale, glossary,
        max_chars=max_chars, back_translated=back,
        standard=get_standard(getattr(cfg, "catalog_standard", None)),
    )
    if back is None and quality.scorer == "heuristic":
        # Dead BT must not look like a clean 1.0 final score.
        signals = list(quality.signals) + ["bt unavailable"]
        return QualityResult(
            round(min(quality.score, 0.49), 3),
            signals,
            dict(quality.dimensions),
            scorer="heuristic",
        )
    return apply_contradiction_cap(quality, source, back)


def _apply_bt_signal(
    quality: QualityResult,
    provider: Provider,
    *,
    source: str,
    translated: str,
    locale: str,
    language: str,
    cfg: ProjectConfig,
) -> QualityResult:
    bt_model = score_model_for(cfg)
    back = backtranslate(
        provider, translated, language, bt_model, cfg, bill_locale=locale,
    )
    if back is None:
        quality.signals = list(quality.signals) + ["bt unavailable"]
        return quality
    overlap = token_overlap(source, back)
    quality.signals = list(quality.signals)
    quality.dimensions = {**(quality.dimensions or {}), "bt_overlap": round(overlap, 3)}
    if overlap < 0.35:
        quality.signals.append(f"low back-translation overlap ({overlap:.0%})")
        quality.score = round(quality.score * (0.55 + 0.45 * overlap), 3)
    elif overlap < 0.55:
        quality.signals.append(f"moderate back-translation overlap ({overlap:.0%})")
        quality.score = round(quality.score * (0.75 + 0.25 * overlap), 3)
    return quality


def score_candidate(
    provider: Provider,
    *,
    source: str,
    translated: str,
    locale: str,
    language: str,
    glossary: dict,
    cfg: ProjectConfig,
    max_chars: int | None = None,
    message_key: str = "",
    context: str = "",
    force_bt: bool = False,
    llm_score: bool = True,
) -> QualityResult:
    """Score with LQS judge when configured, else BT (ADR-20)."""
    if not llm_score:
        return score_heuristic(
            source=source, translated=translated, locale=locale,
            glossary=glossary, max_chars=max_chars,
            standard=get_standard(getattr(cfg, "catalog_standard", None)),
        )

    judge_model = risky_judge_model(cfg, locale, source)
    if not judge_model:
        return score_with_backtranslation(
            provider,
            source=source, translated=translated, locale=locale,
            language=language, glossary=glossary, cfg=cfg, max_chars=max_chars,
        )

    standard = get_standard(getattr(cfg, "catalog_standard", None))
    # Hard structural gate before spending a judge call.
    structural = score_translation(
        source, translated, locale, glossary, max_chars=max_chars, standard=standard,
    )
    if structural.score <= 0.0:
        structural.scorer = "lqs"
        return structural

    glossary_block = glossary_prompt_block(
        glossary, locale, language, sources=[source],
    )
    judged = judge_translation(
        provider,
        source=source,
        translated=translated,
        language=language,
        model=judge_model,
        domain=cfg.domain,
        timeout_s=cfg.provider.timeout_single_s,
        glossary_block=glossary_block,
        message_key=message_key,
        context=context,
        source_locale=cfg.source_locale,
        locale=locale,
        cfg=cfg,
    )
    if not judged.ok:
        fallback = score_with_backtranslation(
            provider,
            source=source, translated=translated, locale=locale,
            language=language, glossary=glossary, cfg=cfg, max_chars=max_chars,
        )
        fallback.signals = list(fallback.signals) + [
            f"judge_parse_failed: {judged.error or 'unknown'}",
        ]
        fallback.scorer = "bt"
        return fallback

    quality = quality_from_judge(
        source=source, translated=translated, locale=locale,
        glossary=glossary, judgment=judged.judgment, max_chars=max_chars,
        standard=standard,
    )
    # Judge dimensions and the deterministic ones share one dict (names never clash).
    quality.dimensions = {**(structural.dimensions or {}), **(quality.dimensions or {})}
    band = quality_band(
        quality.score,
        scale="lqs",
        approve=float(getattr(cfg, "band_approve", 0.95)),
        flag=float(getattr(cfg, "band_flag", 0.90)),
        retranslate=float(getattr(cfg, "band_retranslate", 0.80)),
    )
    need_bt = force_bt or band in {"retranslate", "needs_review", "fail"}
    if need_bt:
        quality = _apply_bt_signal(
            quality, provider,
            source=source, translated=translated, locale=locale, language=language, cfg=cfg,
        )
    return quality


def _dedupe_pending(items: list[PendingScoreItem]) -> list[PendingScoreItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[PendingScoreItem] = []
    for item in items:
        ident = (item.locale, item.namespace, item.key)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(item)
    return out


def _locale_batches(
    items: list[PendingScoreItem], size: int,
) -> list[tuple[int, list[PendingScoreItem]]]:
    """``(start_index, batch)`` pairs; a batch never mixes locales.

    Back-translation and language naming use one locale per batch, so a mixed
    batch would score every item against the first item's language.
    """
    out: list[tuple[int, list[PendingScoreItem]]] = []
    run_start = 0
    for i in range(1, len(items) + 1):
        if i == len(items) or items[i].locale != items[run_start].locale:
            for s0 in range(run_start, i, size):
                out.append((s0, items[s0:min(s0 + size, i)]))
            run_start = i
    return out


_CLOUD_SCORER_KINDS = frozenset({"anthropic", "openai", "deepseek", "openai_compat"})


def _prefetch_back_translations(
    provider: Provider,
    cfg: ProjectConfig,
    bt_model: str,
    batches: list[tuple[int, list]],
    workers: int,
    report: Reporter,
) -> dict[int, list[str | None] | None]:
    """Back-translate the batches in parallel; ``{batch start: backs}``.

    Each task gets its own shallow copy of the provider so ``last_usage`` (read by the spend
    meter) is not shared between threads. A task that raises is left as ``None`` and the caller
    redoes that batch inline, so a failure costs time, never a score.
    """
    import copy
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    todo = [(start, batch) for start, batch in batches if not judge_model_for(cfg, batch[0].locale)]
    out: dict[int, list[str | None] | None] = {}
    if not todo:
        return out

    def work(batch):
        return backtranslate_batch(
            copy.copy(provider), [item.translated for item in batch],
            language_name(batch[0].locale), bt_model, cfg, bill_locale=batch[0].locale,
        )

    started = time.monotonic()
    done_keys = 0
    total_keys = sum(len(b) for _, b in todo)
    report(f"back-translating {total_keys} key(s) in {len(todo)} request(s), {workers} at a time")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, batch): (start, batch) for start, batch in todo}
        for future in as_completed(futures):
            start, batch = futures[future]
            try:
                out[start] = future.result()
            except Exception:  # noqa: BLE001 - redone inline by the caller
                out[start] = None
            done_keys += len(batch)
            report(f"back-translated {done_keys}/{total_keys} key(s), {int(time.monotonic() - started)}s")
    return out


class BtPrefetcher:
    """Back-translates finished translations in the background while later locales still translate.

    Only the slow network calls move; scoring and every ScoreStore write stay on the main thread
    in phase B, which asks :meth:`get` for a batch and falls back to an inline call when a batch
    was not prefetched or its request failed. A prefetched answer is keyed by locale, key and the
    exact translated text, so a text that changed after submission is never reused.
    """

    def __init__(self, cfg: ProjectConfig, provider: Provider, bt_model: str, report: Reporter) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self.cfg, self.provider, self.bt_model, self.report = cfg, provider, bt_model, report
        self.size = max(1, int(getattr(cfg, "bt_cloud_batch_size", 0)
                               or getattr(cfg, "translate_cloud_batch_size", 0) or 50))
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(getattr(cfg, "bt_workers", 4) or 1)))
        self._index: dict[tuple[str, str, str, str], tuple[object, int]] = {}
        self.submitted = 0

    @staticmethod
    def _key(item: PendingScoreItem) -> tuple[str, str, str, str]:
        return (item.locale, item.namespace, item.key, item.translated)

    def submit(self, items: list[PendingScoreItem]) -> None:
        import copy

        todo = [i for i in items if (i.translated or "").strip() and not judge_model_for(self.cfg, i.locale)]
        if not todo:
            return

        def work(batch):
            return backtranslate_batch(
                copy.copy(self.provider), [i.translated for i in batch],
                language_name(batch[0].locale), self.bt_model, self.cfg, bill_locale=batch[0].locale,
            )

        for _, batch in _locale_batches(todo, self.size):
            future = self._pool.submit(work, batch)
            for idx, item in enumerate(batch):
                self._index[self._key(item)] = (future, idx)
        self.submitted += len(todo)
        self.report(f"back-translating {len(todo)} key(s) in the background ({self.submitted} so far)")

    def covers(self, batch: list[PendingScoreItem]) -> bool:
        return all(self._key(i) in self._index for i in batch)

    def get(self, batch: list[PendingScoreItem]) -> list[str | None] | None:
        """Back-translations for ``batch`` in order, or ``None`` when any request failed."""
        try:
            out = []
            for item in batch:
                future, idx = self._index[self._key(item)]
                out.append(future.result()[idx])
            return out
        except Exception:  # noqa: BLE001 - the caller back-translates inline instead
            return None

    def close(self) -> None:
        self._pool.shutdown(wait=True)


def rescore_items(
    provider: Provider,
    cfg: ProjectConfig,
    scores: ScoreStore,
    glossary: dict,
    items: list[PendingScoreItem],
    *,
    report: Reporter | None = None,
    flag_store=None,
    force_bt: bool = False,
    save_every: int = RESCORE_SAVE_EVERY,
    prefetcher: BtPrefetcher | None = None,
) -> tuple[int, list[str]]:
    """Score existing strings; update ScoreStore. Returns (updated, low_keys).

    Scores are written every ``save_every`` keys (at a batch boundary) and on
    any exit, so a crash or Ctrl-C keeps the work already paid for.
    """
    if not items:
        return 0, []

    bt_model = score_model_for(cfg)
    batch_size = max(1, int(getattr(cfg, "bt_batch_size", 5) or 5))
    cloud_scorer = getattr(provider, "kind", "") in _CLOUD_SCORER_KINDS
    workers = 1
    if cloud_scorer:
        # A cloud scorer takes big requests (same BT at half the wall time, HAIKU_BATCH_PROBE)
        # and several at once; a local model keeps the small batches it was tuned with.
        batch_size = max(1, int(getattr(cfg, "bt_cloud_batch_size", 0)
                                or getattr(cfg, "translate_cloud_batch_size", 0) or batch_size))
        workers = max(1, int(getattr(cfg, "bt_workers", 4) or 1))
    updated = 0
    low: list[str] = []
    total = len(items)
    locales_touched: set[str] = set()
    if report is not None and total:
        report_progress(0, total, f"rescoring {total} key(s)")

    def _report(msg: str) -> None:
        if report is not None:
            report(msg)

    saved_at = 0
    locales_dirty: set[str] = set()
    batches = _locale_batches(items, batch_size)
    inline = [b for b in batches if not (prefetcher is not None and prefetcher.covers(b[1]))]
    prefetched = (
        _prefetch_back_translations(provider, cfg, bt_model, inline, workers, _report)
        if workers > 1 and len(inline) > 1 else {}
    )
    def _judge(item: PendingScoreItem, prov: Provider) -> QualityResult:
        return score_candidate(
            prov,
            source=item.source,
            translated=item.translated,
            locale=item.locale,
            language=language_name(item.locale),
            glossary=glossary,
            cfg=cfg,
            max_chars=item.max_chars,
            message_key=item.message_key or (
                f"{item.namespace}.{item.key}" if item.namespace else item.key
            ),
            context=item.context,
            force_bt=force_bt,
            llm_score=True,
        )

    # Judge calls are one request per key; a cloud scorer sends them several at a time.
    judged: dict[int, QualityResult] = {}
    to_judge = [i for i in items if risky_judge_model(cfg, i.locale, i.source)]
    if workers > 1 and len(to_judge) > 1:
        import copy
        from concurrent.futures import ThreadPoolExecutor

        def _try(item):
            try:
                return _judge(item, copy.copy(provider))
            except Exception:  # noqa: BLE001 - judged inline below instead
                return None

        _report(f"judging {len(to_judge)} short key(s), {workers} at a time")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for item, result in zip(to_judge, pool.map(_try, to_judge)):
                if result is not None:
                    judged[id(item)] = result
    try:
        for start, batch in batches:
            backs: list[str | None]
            if judge_model_for(cfg, batch[0].locale):
                backs = [None] * len(batch)
            elif prefetcher is not None and prefetcher.covers(batch) and (got := prefetcher.get(batch)) is not None:
                backs = got
            elif start in prefetched and prefetched[start] is not None:
                backs = prefetched[start]
            else:
                language = language_name(batch[0].locale)
                with log_heartbeat(
                    f"back-translating batch of {len(batch)}",
                    reporter=_report,
                ):
                    backs = backtranslate_batch(
                        provider,
                        [item.translated for item in batch],
                        language,
                        bt_model,
                        cfg,
                        bill_locale=batch[0].locale,
                    )

            for offset, item in enumerate(batch):
                done = start + offset + 1
                language = language_name(item.locale)
                # Same rule as the inline path: the configured judge, else (judge_risky) the scoring
                # model for one- and two-word keys, which back-translation cannot judge.
                if risky_judge_model(cfg, item.locale, item.source):
                    quality = judged.get(id(item)) or _judge(item, provider)
                else:
                    back = backs[offset] if offset < len(backs) else None
                    quality = score_with_backtranslation(
                        provider,
                        source=item.source,
                        translated=item.translated,
                        locale=item.locale,
                        language=language,
                        glossary=glossary,
                        cfg=cfg,
                        max_chars=item.max_chars,
                        back_translated=back,
                    )

                scores.record(
                    item.locale, item.namespace, item.key,
                    score=quality.score,
                    signals=quality.signals,
                    text=item.translated,
                    dimensions=quality.dimensions,
                    scorer=quality.scorer,
                )
                locales_touched.add(item.locale)
                locales_dirty.add(item.locale)
                updated += 1
                label = f"{item.namespace}.{item.key}" if item.namespace else item.key
                pct_label = f"{item.locale}/{label} score={quality.score:.2f}"
                _report(f"[{done}/{total}] {pct_label}")
                if report is not None:
                    report_progress(done, total, pct_label)
                    report_metric(done=done, total=total)

                cut = improve_score_cut(cfg, scorer=quality.scorer, locale=item.locale)
                if quality.score < cut:
                    reason = quality.signals[0] if quality.signals else "low quality score"
                    low.append(f"{item.locale}/{label}: {quality.score:.2f}")
                    if flag_store is not None:
                        flag_store.append({
                            "locale": item.locale,
                            "namespace": item.namespace,
                            "key": item.key,
                            "reason": reason,
                        })
                    _report(f"    LOW SCORE {quality.score:.2f}: {reason}")
            if updated - saved_at >= max(1, int(save_every)):
                for loc in locales_dirty:
                    scores.save(loc)
                locales_dirty.clear()
                saved_at = updated
    finally:
        for locale in locales_touched:
            scores.save(locale)

    return updated, low


def run_deferred_scoring_phase(
    cfg: ProjectConfig,
    provider: Provider,
    scores: ScoreStore,
    glossary: dict,
    items: list[PendingScoreItem],
    *,
    pin_model: str,
    report: Reporter,
    flag_store=None,
    prefetcher: BtPrefetcher | None = None,
) -> int:
    """Phase B: unload translator, warm score model, batch BT."""
    items = _dedupe_pending(items)
    if not items:
        return 0

    score_model = score_model_for(cfg)
    report(f"phase 2: BT scoring {len(items)} key(s) with {score_model}")
    stop = getattr(provider, "stop", None)
    if callable(stop):
        stop(pin_model)
    provider.ensure_ready(score_model, report=report)

    updated, _low = rescore_items(
        provider, cfg, scores, glossary, items,
        report=report, flag_store=flag_store, force_bt=False, prefetcher=prefetcher,
    )

    if callable(stop):
        stop(score_model)
    return updated
