"""Preflight checks for configured Ollama model pins."""

from __future__ import annotations

from .ollama import (
    OllamaProvider,
    missing_model_message,
    model_installed,
    ollama_unreachable_message,
)

__all__ = [
    "looks_like_cloud_model",
    "model_fit_errors",
    "configured_model_pins",
    "check_ollama_model",
    "missing_configured_models",
]


def configured_model_pins(cfg) -> list[str]:
    """Unique model tags referenced by project config."""
    pins: set[str] = set()
    for value in (getattr(cfg, "models", None) or {}).values():
        if value:
            pins.add(str(value))
    for attr in (
        "documents_model",
        "improve_model",
        "score_model",
        "judge_model",
        "vision_model",
    ):
        value = getattr(cfg, attr, None)
        if value:
            pins.add(str(value))
    for role in (getattr(cfg, "roles", None) or {}).values():
        for attr in ("primary", "secondary", "judge"):
            value = getattr(role, attr, None)
            if value:
                pins.add(str(value))
    return sorted(pins)


def missing_configured_models(cfg, installed: list[str]) -> list[str]:
    """Pins that are absent from an Ollama ``/api/tags`` listing."""
    if not installed:
        return []
    return [
        pin for pin in configured_model_pins(cfg)
        if not model_installed(pin, installed)
    ]


def check_ollama_model(cfg, model: str) -> str | None:
    """Return an error string if ``model`` is missing from local Ollama.

    Non-Ollama providers return None (no local tag list to check).
    """
    kind = (getattr(cfg.provider, "kind", None) or "ollama").lower()
    if kind != "ollama":
        return None
    provider = OllamaProvider(
        url=getattr(cfg.provider, "url", "http://localhost:11434"),
        options=dict(getattr(cfg.provider, "options", None) or {}),
        keep_alive=getattr(cfg.provider, "keep_alive", "30m"),
    )
    if not provider.health_check():
        return ollama_unreachable_message(provider.base_url)
    installed = provider.available_models()
    if installed and not model_installed(model, installed):
        return missing_model_message(model, installed)
    return None


_CLOUD = frozenset({"anthropic", "openai", "deepseek", "deepl"})
_CLOUD_PREFIXES = ("claude-", "gpt-", "deepseek-", "o1", "o3", "o4")


def looks_like_cloud_model(model: str) -> bool:
    """True for a hosted model id (``claude-...``, ``gpt-...``, ``deepseek-...``), False for local tags."""
    name = (model or "").strip().lower()
    return ":" not in name and name.startswith(_CLOUD_PREFIXES)


def _misfit(kind: str, model: str | None) -> bool:
    """A local tag sent to a cloud API, or a hosted id sent to Ollama. Unknown shapes pass."""
    if not model or kind in ("ctranslate2", "null", "chaos", "deepl"):
        return False
    if kind in _CLOUD:
        return ":" in model
    return looks_like_cloud_model(model)


def model_fit_errors(cfg) -> list[str]:
    """Model pins whose shape cannot work on the provider they are routed to (checked at config load)."""
    errors: list[str] = []
    models = getattr(cfg, "models", None) or {}
    roles = getattr(cfg, "roles", None) or {}
    for locale in sorted(set(getattr(cfg, "targets", None) or [])):
        kind = cfg.provider_kind_for(locale)
        role = roles.get(locale)
        for label, model in (
            (f"[locales.models] {locale}", models.get(locale)),
            (f"[locales.roles.{locale}] primary", getattr(role, "primary", None)),
        ):
            if _misfit(kind, model):
                errors.append(f"{label} = {model!r} cannot run on provider {kind!r} (locale {locale})")
    from ..pipeline.scoring import score_provider_kind

    project_kind = (getattr(cfg.provider, "kind", None) or "ollama").lower()
    score_kind = score_provider_kind(cfg) or project_kind
    for label, model, kind in (
        ("[quality] score_model", getattr(cfg, "score_model", None), score_kind),
        ("[quality] improve_model", getattr(cfg, "improve_model", None), project_kind),
    ):
        if _misfit(kind, model):
            errors.append(f"{label} = {model!r} cannot run on provider {kind!r}; "
                          "set [quality] score_provider or a matching model")
    return errors
