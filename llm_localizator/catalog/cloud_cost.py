"""Decide whether a cloud translation run may spend.

Ollama and CTranslate2 ignore this. A paying cloud locale is one whose
provider is cloud, ``[privacy] allow_cloud`` is set, and the monthly budget
still has money left. A zero or exhausted budget keeps today's fallback to
the local provider; this module does not also refuse that path.
"""

from __future__ import annotations

from dataclasses import dataclass

from .budget import BudgetStore
from .pricing import (
    CLOUD_DEFAULT_MODEL,
    CostFigures,
    PricingError,
    price_sources,
)

CLOUD_KINDS = frozenset({"anthropic", "deepl", "openai", "deepseek"})

__all__ = [
    "CLOUD_KINDS",
    "CloudDecision",
    "paying_cloud_kind",
    "resolve_translation_model",
    "preamble_chars",
    "quote_locale",
    "cloud_run_decision",
]


@dataclass(frozen=True)
class CloudDecision:
    """``refuse`` stops the run. ``message`` is empty when nothing is cloud.

    When ``hold_id`` is set the caller must ``BudgetStore.release`` it in a
    ``finally`` (unused ceiling after the run, or on abort).
    """

    refuse: bool
    message: str
    max_usd: float = 0.0
    batch_usd: float = 0.0
    remaining_usd: float = 0.0
    model: str = ""
    provider: str = ""
    keys: int = 0
    hold_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "refuse": self.refuse,
            "allowed": not self.refuse and bool(self.provider or self.keys or self.message),
            "max_usd": round(self.max_usd, 6),
            "batch_usd": round(self.batch_usd, 6),
            "remaining_usd": round(self.remaining_usd, 6),
            "model": self.model,
            "provider": self.provider,
            "keys": self.keys,
            "message": self.message,
            "hold_id": self.hold_id,
        }


def paying_cloud_kind(cfg, locale: str) -> str | None:
    """Kind that will actually be called, or None when the run stays local."""
    kind = (cfg.provider_kind_for(locale) or "").strip().lower()
    if kind not in CLOUD_KINDS:
        return None
    if not getattr(cfg, "allow_cloud", False):
        return None
    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    if cap <= 0:
        return None
    if BudgetStore(cfg.budget_root()).remaining(cap) <= 0:
        return None
    return kind


def resolve_translation_model(cfg, locale: str, kind: str) -> str:
    """Locale model if set, otherwise the cheapest listed model for ``kind``."""
    role = cfg.role_for(locale)
    if role.primary:
        return role.primary
    explicit = (getattr(cfg, "models", None) or {}).get(locale)
    if explicit:
        return str(explicit)
    if kind == "deepl":
        return "deepl"
    return CLOUD_DEFAULT_MODEL.get(kind, CLOUD_DEFAULT_MODEL["anthropic"])


def preamble_chars(cfg, locale: str) -> int:
    """Length of a single-string prompt minus the source itself."""
    from ..core.cldr import language_name
    from ..pipeline.prompts import BatchItem, build_single_prompt

    marker = "\uE000"
    item = BatchItem(source=marker)
    register, style_notes = cfg.style_for(locale)
    prompt = build_single_prompt(
        item,
        language_name(locale),
        cfg.domain,
        "",
        locale=locale,
        register=register,
        family=cfg.prompt_family_for(locale),
        style_notes=style_notes,
    )
    return max(0, len(prompt) - prompt.count(marker) * len(marker))


def quote_locale(
    cfg,
    locale: str,
    sources: list[str],
    *,
    batch_size: int,
    kind: str | None = None,
) -> tuple[CostFigures, str, str]:
    """Return figures, provider kind, and model. Raises :class:`PricingError`."""
    resolved = kind or paying_cloud_kind(cfg, locale) or cfg.provider_kind_for(locale)
    model = resolve_translation_model(cfg, locale, resolved)
    figures = price_sources(
        sources,
        kind=resolved,
        model=model,
        batch_size=batch_size,
        preamble_chars=0 if resolved == "deepl" else preamble_chars(cfg, locale),
        output_expansion=float(getattr(cfg, "budget_output_expansion", 2.0) or 2.0),
        thinking_tokens=int(getattr(cfg, "budget_thinking_tokens", 1024) or 0),
        overrides=getattr(cfg, "budget_rates", None) or None,
        locale=locale,
    )
    return figures, resolved, model


def cloud_run_decision(
    cfg,
    locales: list[str],
    sources_by_locale: dict[str, list[str]],
    *,
    named_keys: list[str] | None,
    batch_size: int,
    enforce_keys: bool = True,
    take_hold: bool = True,
) -> CloudDecision:
    """Pre-flight for one translate run.

    ``on_request`` without ``named_keys`` refuses before any price check.
    ``dynamic`` may send every due string whose ceiling fits the remaining budget.
    When allowing a paying run with ``take_hold``, reserves ``max_usd`` so a
    concurrent process cannot spend the same remainder (caller must release).
    """
    paying = [loc for loc in locales if paying_cloud_kind(cfg, loc)]
    if not paying:
        return CloudDecision(refuse=False, message="")

    mode = getattr(cfg, "budget_mode", "on_request") or "on_request"
    if enforce_keys and mode == "on_request" and not named_keys:
        return CloudDecision(
            refuse=True,
            message=(
                "cloud mode is on_request: pass --keys namespace.key "
                'or set [budget] mode = "dynamic"'
            ),
            provider=paying_cloud_kind(cfg, paying[0]) or "",
        )

    store = BudgetStore(cfg.budget_root())
    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    remaining = store.remaining(cap)
    max_usd = 0.0
    batch_usd = 0.0
    keys = 0
    provider = ""
    model = ""
    try:
        for locale in paying:
            sources = list(sources_by_locale.get(locale) or [])
            if not sources:
                continue
            figures, provider, model = quote_locale(
                cfg, locale, sources, batch_size=batch_size,
            )
            max_usd += figures.max_usd
            batch_usd += figures.batch_usd
            keys += len(sources)
    except PricingError as exc:
        return CloudDecision(refuse=True, message=str(exc), remaining_usd=remaining)

    if keys == 0:
        return CloudDecision(
            refuse=False,
            message="",
            remaining_usd=remaining,
            provider=provider,
        )

    message = (
        f"cloud quote: max_usd={max_usd:.4f} batch_usd={batch_usd:.4f} "
        f"remaining={remaining:.4f} provider={provider} model={model} keys={keys}"
    )
    if max_usd > remaining:
        return CloudDecision(
            refuse=True,
            message=(
                f"cloud budget: max_usd {max_usd:.4f} exceeds remaining "
                f"{remaining:.4f} ({provider}/{model}, {keys} keys). Not sending."
            ),
            max_usd=max_usd,
            batch_usd=batch_usd,
            remaining_usd=remaining,
            model=model,
            provider=provider,
            keys=keys,
        )
    hold_id = None
    if take_hold and max_usd > 0 and cap > 0:
        hold_id = store.reserve(max_usd, cap_usd=cap)
        if hold_id is None:
            return CloudDecision(
                refuse=True,
                message=(
                    f"cloud budget: could not reserve {max_usd:.4f} "
                    f"(remaining raced to below the ceiling). Not sending."
                ),
                max_usd=max_usd,
                batch_usd=batch_usd,
                remaining_usd=store.remaining(cap),
                model=model,
                provider=provider,
                keys=keys,
            )
    return CloudDecision(
        refuse=False,
        message=message,
        max_usd=max_usd,
        batch_usd=batch_usd,
        remaining_usd=remaining,
        model=model,
        provider=provider,
        keys=keys,
        hold_id=hold_id,
    )
