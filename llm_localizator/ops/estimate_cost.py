"""Pre-flight maximum cost. No provider call."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from ..catalog.budget import BudgetStore
from ..catalog.cloud_cost import paying_cloud_kind, quote_locale
from ..catalog.pricing import PricingError
from ..catalog.state import state_key
from ..projects import ProjectConfig
from ..projects.context import ContextNotes
from .catalogue_gaps import iter_catalogue_gaps
from .types import EstimateCostRequest, OpResult, resolve_namespaces

__all__ = ["op_estimate_cost", "sources_for_estimate"]

_DUE = frozenset({"missing", "empty", "stale"})


def sources_for_estimate(
    cfg: ProjectConfig,
    req: EstimateCostRequest,
) -> dict[str, list[str]]:
    """Source strings that a cloud run would send, grouped by locale."""
    locales = list(req.locales) if req.locales else list(cfg.active_targets())
    if req.collection and req.collection != "messages":
        return _remote_sources(cfg, req.collection, locales, req.keys)

    namespaces = resolve_namespaces(req.namespace, req.namespaces)
    wanted = set(req.keys) if req.keys else None
    grouped: dict[str, list[str]] = defaultdict(list)
    notes = ContextNotes(cfg.context_dir)
    for gap in iter_catalogue_gaps(
        cfg, locales=locales, namespaces=namespaces, reasons=_DUE,
    ):
        label = state_key(gap.namespace, gap.key)
        if wanted is not None and label not in wanted and gap.key not in wanted:
            continue
        text = gap.source
        # C-050: per-key notes ride in the prompt and are billed as input. DeepL gets
        # the bare source, so its character count must not include them.
        if isinstance(text, str) and paying_cloud_kind(cfg, gap.locale) != "deepl":
            extra = " ".join(
                n for n in (notes.note(gap.namespace, gap.key), notes.llm_note(gap.namespace, gap.key)) if n
            )
            glossary = _glossary_for(cfg, notes, gap.namespace, gap.key)
            if glossary:
                from ..core.glossary_match import format_glossary_annotation, glossary_hits

                hits = format_glossary_annotation(glossary_hits(text, glossary, gap.locale))
                extra = " ".join(n for n in (extra, hits) if n)
            if extra:
                text = f"{text}\n{extra}"
        grouped[gap.locale].append(text)
    return dict(grouped)


def _glossary_for(cfg, notes, namespace: str, key: str) -> dict:
    """The glossary a translate run would use for this key; empty when none is set."""
    if not getattr(cfg, "glossary_path", None):
        return {}
    from ..projects import effective_glossary_for

    domains = cfg.glossary_domains_for(namespace, key_domain=notes.domain(namespace, key))
    return effective_glossary_for(
        cfg.glossary_path, domains=domains,
        shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )


def _eta_seconds(cfg: ProjectConfig, keys: int) -> float | None:
    """Rough wall time from the median speed of recent translate runs; None when unknown."""
    if keys <= 0:
        return None
    from ..pipeline.run_manifest import iter_run_records

    try:
        records = iter_run_records(cfg.state_root())
    except OSError:
        return None
    rates = [
        float(r["metrics"]["keys_per_s"])
        for r in records
        if r.get("command") == "translate"
        and float((r.get("metrics") or {}).get("keys_per_s") or 0) > 0
    ][:10]
    if not rates:
        return None
    return round(keys / median(rates), 1)


def _judged_pairs(cfg: ProjectConfig, req: EstimateCostRequest, locales: list[str]) -> dict[str, list[str]]:
    """Source + target of every translated string a review/rescore run would send, grouped by locale."""
    from ..catalog import catalog_for

    catalog = catalog_for(cfg)
    namespaces = resolve_namespaces(req.namespace, req.namespaces) or cfg.namespaces_for(catalog)
    wanted = set(req.keys) if req.keys else None
    grouped: dict[str, list[str]] = defaultdict(list)
    for ns in namespaces:
        source = catalog.load(cfg.source_locale, ns)
        for locale in locales:
            for key, target in catalog.load(locale, ns).items():
                if wanted is not None and key not in wanted and state_key(ns, key) not in wanted:
                    continue
                if isinstance(target, str) and target.strip() and isinstance(source.get(key), str):
                    grouped[locale].append(f"{source[key]}\n{target}")
    return dict(grouped)


def _estimate_judged(cfg: ProjectConfig, req: EstimateCostRequest, locales: list[str]) -> OpResult:
    """Review / rescore: one judge call per translated string on the project provider (M6)."""
    from ..catalog.cloud_cost import CLOUD_KINDS
    from ..catalog.pricing import price_sources

    grouped = _judged_pairs(cfg, req, locales)
    keys = sum(len(v) for v in grouped.values())
    kind = (cfg.provider.kind or "ollama").strip().lower()
    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    remaining = BudgetStore(cfg.budget_root()).remaining(cap) if cap > 0 else 0.0
    if kind not in CLOUD_KINDS or not getattr(cfg, "allow_cloud", False):
        summary = f"{req.purpose}: {keys} translated string(s), local model: no cloud cost"
        return OpResult(True, 0, "estimate-cost", summary, lines=[summary], data={
            "local": True, "allowed": True, "max_usd": 0.0, "batch_usd": 0.0, "keys": keys,
            "remaining_usd": round(remaining, 6), "purpose": req.purpose, "eta_s": None,
        })
    from ..catalog.cloud_cost import CLOUD_DEFAULT_MODEL

    model = (getattr(cfg, "judge_model", None) or getattr(cfg.provider, "model", None)
             or CLOUD_DEFAULT_MODEL.get(kind, CLOUD_DEFAULT_MODEL["anthropic"]))
    try:
        figures = price_sources(
            [text for texts in grouped.values() for text in texts], kind=kind, model=model,
            batch_size=req.batch_size, preamble_chars=0,
            output_expansion=0.25,   # a score and a short reason, not a translation
            thinking_tokens=int(getattr(cfg, "budget_thinking_tokens", 1024) or 0),
            overrides=getattr(cfg, "budget_rates", None) or None,
        )
    except PricingError as exc:
        return OpResult(False, 1, "estimate-cost", str(exc))
    allowed = figures.max_usd <= remaining
    summary = (f"{req.purpose}: max_usd={figures.max_usd:.4f} remaining={remaining:.4f} keys={keys} {kind}/{model}"
               + ("  exceeds remaining budget" if not allowed else ""))
    return OpResult(True, 0, "estimate-cost", summary, lines=[summary], data={
        "local": False, "allowed": allowed, "max_usd": round(figures.max_usd, 6),
        "batch_usd": round(figures.batch_usd, 6), "remaining_usd": round(remaining, 6), "keys": keys,
        "provider": kind, "model": model, "purpose": req.purpose, "eta_s": None,
    })


def op_estimate_cost(cfg: ProjectConfig, req: EstimateCostRequest) -> OpResult:
    locales = list(req.locales) if req.locales else list(cfg.active_targets())
    if req.purpose in ("review", "rescore"):
        return _estimate_judged(cfg, req, locales)
    try:
        grouped = sources_for_estimate(cfg, req)
    except Exception as exc:
        return OpResult(
            ok=False, exit_code=1, command="estimate-cost", summary=str(exc),
        )

    paying = [loc for loc in locales if paying_cloud_kind(cfg, loc)]
    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    remaining = BudgetStore(cfg.budget_root()).remaining(cap) if cap > 0 else 0.0
    mode = getattr(cfg, "budget_mode", "on_request") or "on_request"

    if not paying:
        summary = (
            "local provider: no cloud cost "
            "(cloud stays off until allow_cloud and budget.monthly_usd > 0)"
        )
        data = {
            "local": True,
            "allowed": True,
            "max_usd": 0.0,
            "batch_usd": 0.0,
            "remaining_usd": round(remaining, 6),
            "keys": sum(len(v) for v in grouped.values()),
            "mode": mode,
            "eta_s": _eta_seconds(cfg, sum(len(v) for v in grouped.values())),
        }
        return OpResult(
            ok=True, exit_code=0, command="estimate-cost",
            summary=summary, lines=[summary], data=data,
        )

    max_usd = 0.0
    batch_usd = 0.0
    keys = 0
    provider = ""
    model = ""
    lines = []
    try:
        for locale in paying:
            sources = grouped.get(locale) or []
            if not sources:
                continue
            figures, provider, model = quote_locale(
                cfg, locale, sources, batch_size=req.batch_size,
            )
            max_usd += figures.max_usd
            batch_usd += figures.batch_usd
            keys += len(sources)
            lines.append(
                f"  {locale}: {len(sources)} keys  max_usd={figures.max_usd:.4f} "
                f"batch_usd={figures.batch_usd:.4f}  {provider}/{model}"
            )
    except PricingError as exc:
        return OpResult(ok=False, exit_code=1, command="estimate-cost", summary=str(exc))

    allowed = max_usd <= remaining
    summary = (
        f"max_usd={max_usd:.4f} batch_usd={batch_usd:.4f} "
        f"remaining={remaining:.4f} keys={keys} mode={mode}"
    )
    if not allowed:
        summary += "  exceeds remaining budget"
    lines.insert(0, summary)
    if mode == "on_request" and not req.keys:
        lines.append(
            'on_request will not send until you pass --keys. '
            'mode = "dynamic" sends these due strings when the ceiling fits.'
        )
    return OpResult(
        ok=True,
        exit_code=0,
        command="estimate-cost",
        summary=summary,
        lines=lines,
        data={
            "local": False,
            "allowed": allowed,
            "max_usd": round(max_usd, 6),
            "batch_usd": round(batch_usd, 6),
            "remaining_usd": round(remaining, 6),
            "keys": keys,
            "mode": mode,
            "provider": provider,
            "model": model,
            "eta_s": _eta_seconds(cfg, keys),
        },
    )


def _remote_sources(cfg, name: str, locales: list[str], keys: list[str] | None) -> dict[str, list[str]]:
    from ..content.client import ContentClient, endpoint_from_env
    from ..content.translate import plan_writes
    from ..projects.collections import get_collection

    coll = get_collection(cfg, name)
    if coll.kind != "remote":
        raise ValueError(f"{name} is not a remote collection")
    url, token = endpoint_from_env()
    units = ContentClient(url, token).list_units()
    work = plan_writes(units, locales, force=False)
    wanted = set(keys) if keys else None
    grouped: dict[str, list[str]] = defaultdict(list)
    for unit, cell in work:
        if wanted is not None and unit.id not in wanted:
            continue
        grouped[cell.locale].append(unit.source_text or "")
    return dict(grouped)
