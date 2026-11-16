"""LLM backends behind a single interface."""

from __future__ import annotations

import logging

from .anthropic import AnthropicProvider
from .base import CompletionRequest, Provider, ProviderError
from .chaos import ChaosProvider
from .ctranslate2 import CTranslate2Provider
from .deepl import DeepLProvider
from .null import NullProvider
from .ollama import OllamaProvider
from .openai_compat import DEEPSEEK_URL, OPENAI_URL, OpenAICompatibleProvider

from ..catalog.budget import BudgetStore
from ..catalog.pricing import CLOUD_DEFAULT_MODEL, actual_usd

__all__ = [
    "AnthropicProvider",
    "ChaosProvider",
    "CompletionRequest",
    "CTranslate2Provider",
    "DeepLProvider",
    "NullProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderError",
    "build_provider",
    "provider_for_locale",
    "score_provider_for",
    "project_provider",
    "record_provider_spend",
    "metered_complete",
    "complete_for",
]

_CLOUD_KINDS = frozenset({"anthropic", "deepl", "openai", "deepseek"})
_log = logging.getLogger(__name__)
_OLLAMA_DEFAULTS = frozenset({
    "http://localhost:11434",
    "http://127.0.0.1:11434",
})


def _compat_url(configured: str, default: str) -> str:
    """Use a custom OpenAI-compat base URL when it is not the Ollama default."""
    url = (configured or "").strip().rstrip("/")
    if not url or url in _OLLAMA_DEFAULTS:
        return default
    return url


def build_provider(cfg, *, kind: str | None = None, register: str = "informal") -> Provider:
    """Instantiate the provider named by ``kind`` (default: ``cfg.kind``).

    ``cfg`` is a :class:`~llm_localizator.projects.config.ProviderConfig`-like
    object. Cloud providers read API keys from the environment only.
    """
    resolved = kind or getattr(cfg, "kind", "ollama") or "ollama"
    if resolved == "null":
        return NullProvider()
    if resolved == "ollama":
        return OllamaProvider(
            url=getattr(cfg, "url", "http://localhost:11434"),
            options=dict(getattr(cfg, "options", None) or {}),
            keep_alive=getattr(cfg, "keep_alive", "30m"),
        )
    if resolved == "ctranslate2":
        opts = dict(getattr(cfg, "options", None) or {})
        return CTranslate2Provider(
            model_path=getattr(cfg, "model_path", "") or "",
            device=str(opts.get("device", "auto")),
            compute_type=str(opts.get("compute_type", "default")),
            spm_model=opts.get("spm_model"),
            beam_size=int(opts.get("beam_size", 4)),
        )
    if resolved == "anthropic":
        return AnthropicProvider(default_model=CLOUD_DEFAULT_MODEL["anthropic"])
    if resolved == "deepl":
        formality = "prefer_more" if register == "formal" else "prefer_less"
        source = getattr(cfg, "source_locale", None) or "en"
        return DeepLProvider(formality=formality, source_locale=str(source))
    if resolved == "openai":
        url = _compat_url(getattr(cfg, "url", ""), OPENAI_URL)
        return OpenAICompatibleProvider(
            kind="openai",
            env_var="OPENAI_API_KEY",
            url=url,
            default_model=CLOUD_DEFAULT_MODEL["openai"],
            reasoning=True,
        )
    if resolved == "deepseek":
        url = _compat_url(getattr(cfg, "url", ""), DEEPSEEK_URL)
        return OpenAICompatibleProvider(
            kind="deepseek",
            env_var="DEEPSEEK_API_KEY",
            url=url,
            default_model=CLOUD_DEFAULT_MODEL["deepseek"],
            disable_thinking=True,
        )
    known = "anthropic, ctranslate2, deepseek, deepl, null, ollama, openai"
    raise ValueError(f"unknown provider {resolved!r} (known: {known})")


def provider_for_locale(project, locale: str, *, report=None) -> Provider:
    """Resolve the provider for one locale, honouring budget gate for cloud.

    When ``[budget] monthly_usd = 0`` (dogfood default), cloud kinds fall back
    to the project ``[provider]`` so strings stay local unless the operator
    explicitly opens a budget. Named provider URLs come from ADR-47 entries.
    """
    entry_cfg = (
        project.provider_config_for(locale)
        if hasattr(project, "provider_config_for")
        else project.provider
    )
    kind = getattr(entry_cfg, "kind", None) or project.provider_kind_for(locale)
    return _gated_build(project, entry_cfg, kind, label=locale, report=report)


def score_provider_for(project, *, report=None) -> Provider | None:
    """Provider for BT scoring, the judge and improve scoring, from ``[quality] score_provider``.

    ``None`` when unset: callers keep the translator's provider. The value is a named provider id
    (ADR-47) or a bare kind. Cloud kinds pass the same allow_cloud / budget gate as translation.
    """
    ref = (getattr(project, "score_provider", None) or "").strip()
    if not ref:
        return None
    registry = getattr(project, "providers", None) or {}
    if ref in registry:
        entry_cfg = registry[ref].as_provider_config()
        kind = entry_cfg.kind or "ollama"
    else:
        entry_cfg, kind = project.provider, ref
    return _gated_build(project, entry_cfg, kind, label="scoring", report=report)


def _gated_build(project, entry_cfg, kind: str, *, label: str, report=None) -> Provider:
    """Build ``kind``; a cloud kind falls back to the project provider without allow_cloud or budget."""
    locale = label
    allow_cloud = bool(getattr(project, "allow_cloud", False))
    if kind in _CLOUD_KINDS and getattr(project, "local_only", False):
        raise ProviderError(f"{kind} is blocked by [privacy] local_only = true")
    fallback_cfg = project.provider
    if kind in _CLOUD_KINDS and not allow_cloud:
        if report:
            report(
                f"note: {kind} stays off until [privacy] allow_cloud = true "
                f"— staying on ollama"
            )
        kind = "ollama"
        budget = 0.0
        entry_cfg = fallback_cfg
    else:
        budget = float(getattr(project, "budget_monthly_usd", 0) or 0)
    if kind in _CLOUD_KINDS and budget <= 0:
        if report:
            report(
                f"note: locale {locale} requests provider {kind!r} but "
                f"budget.monthly_usd=0 — staying on {project.provider.kind!r}"
            )
        kind = project.provider.kind or "ollama"
        entry_cfg = fallback_cfg
    elif kind in _CLOUD_KINDS and budget > 0:
        remaining = BudgetStore(project.budget_root()).remaining(budget)
        if remaining <= 0:
            if report:
                report(
                    f"note: monthly budget exhausted for {locale} — "
                    f"staying on {project.provider.kind!r}"
                )
            kind = project.provider.kind or "ollama"
            entry_cfg = fallback_cfg
        elif report:
            report(
                f"note: using external provider {kind!r} for {locale} "
                f"(budget.monthly_usd={budget}, remaining={remaining:.4f})"
            )
    return build_provider(
        entry_cfg,
        kind=kind,
        register=getattr(project, "register", "informal"),
    )


def project_provider(project) -> Provider:
    """Project default provider. Cloud kinds need ``[privacy] allow_cloud``."""
    kind = (project.provider.kind or "ollama").strip().lower()
    if kind in _CLOUD_KINDS and getattr(project, "local_only", False):
        raise ProviderError(f"{kind} is blocked by [privacy] local_only = true")
    if kind in _CLOUD_KINDS and not getattr(project, "allow_cloud", False):
        raise ProviderError(
            f"{kind} requires [privacy] allow_cloud = true"
        )
    return build_provider(
        project.provider,
        kind=kind,
        register=getattr(project, "register", "informal"),
    )


def record_provider_spend(project, provider: Provider, locale: str, *, model: str) -> None:
    """Meter spend after a cloud completion. The one guard for every caller.

    Local providers and projects without ``allow_cloud`` are never metered.
    A model with no known price is counted at the highest published rate and
    reported, so it can only over-count against the cap, never record 0.
    """
    budget = float(getattr(project, "budget_monthly_usd", 0) or 0)
    if budget <= 0 or not getattr(project, "allow_cloud", False):
        return
    kind = (getattr(provider, "kind", "") or "").strip().lower()
    if kind not in _CLOUD_KINDS:
        return
    usage = provider.usage()
    if not isinstance(usage, dict):
        return
    from ..catalog.pricing import PricingError, fallback_usd

    note = type(provider).__name__
    try:
        amount = actual_usd(
            kind, model, usage,
            overrides=getattr(project, "budget_rates", None) or None,
        )
    except PricingError as exc:
        amount = fallback_usd(kind, usage)
        note += " (fallback rate)"
        _log.warning(
            "no price for %s/%s; counting %.6f USD at the highest known rate (%s)",
            kind, model, amount, exc,
        )
    if amount <= 0:
        return
    def _count(name: str) -> int | None:
        value = usage.get(name)
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    BudgetStore(project.budget_root()).record(
        amount, locale=locale, model=model, note=note, kind=kind,
        input_tokens=_count("input_tokens"), output_tokens=_count("output_tokens"),
        characters=_count("billed_characters"),
    )


def complete_for(project, provider: Provider, locale: str, request: CompletionRequest) -> str:
    """``metered_complete`` when the caller has a project, else a bare call (tests, ad-hoc tools)."""
    if project is None:
        return provider.complete(request)
    return metered_complete(project, provider, locale, request)


def metered_complete(project, provider: Provider, locale: str, request: CompletionRequest) -> str:
    """Call ``provider.complete`` and record cloud spend when applicable."""
    try:
        text = provider.complete(request)
    except Exception:
        # A call can fail after the provider billed it (e.g. cut off at the
        # token limit); usage is only set once a response arrived.
        record_provider_spend(project, provider, locale, model=request.model)
        raise
    record_provider_spend(project, provider, locale, model=request.model)
    return text
