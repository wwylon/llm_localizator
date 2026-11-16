"""Translation channel provenance (ADR-19).

``model`` names the concrete producer; ``provider`` names the channel.
Both are written on accept; readers infer ``provider`` when legacy rows omit it.
"""

from __future__ import annotations

__all__ = [
    "PROVIDERS",
    "PROVIDER_LOCAL",
    "PROVIDER_CLOUD",
    "normalize_provider",
    "infer_provider",
    "provider_of",
    "SOURCE_CLASSES",
    "source_class",
]

PROVIDERS = frozenset({
    "ollama",
    "ctranslate2",
    "anthropic",
    "openai",
    "deepseek",
    "deepl",
    "human",
    "agent",
    "import",
})

PROVIDER_LOCAL = frozenset({"ollama", "ctranslate2"})
PROVIDER_CLOUD = frozenset({"anthropic", "deepl", "openai", "deepseek"})


def normalize_provider(kind: str | None) -> str:
    """Map a pipeline/config kind onto the frozen vocabulary."""
    if kind in PROVIDERS:
        return kind  # type: ignore[return-value]
    if not kind or kind in {"null", "local"}:
        return "ollama"
    lowered = str(kind).strip().lower()
    if lowered in PROVIDERS:
        return lowered
    if "anthropic" in lowered or "claude" in lowered:
        return "anthropic"
    if "openai" in lowered or lowered.startswith("gpt"):
        return "openai"
    if "deepseek" in lowered:
        return "deepseek"
    if "deepl" in lowered:
        return "deepl"
    if "ctranslate" in lowered or "madlad" in lowered:
        return "ctranslate2"
    return "ollama"


def infer_provider(
    entry: dict | None = None,
    *,
    model: str | None = None,
    verified_by: str | None = None,
    status: str | None = None,
) -> str:
    """Best-effort channel for a legacy row (never invents ``agent`` blindly)."""
    model_s = (model if model is not None else (entry or {}).get("model") or "")
    model_s = str(model_s).strip()
    verified = (
        verified_by if verified_by is not None
        else (entry or {}).get("verified_by")
    )
    status_s = (
        status if status is not None else (entry or {}).get("status")
    )
    verified_s = str(verified or "").strip().lower()

    if verified_s and any(tok in verified_s for tok in ("cursor", "agent")):
        return "agent"
    if model_s == "import" or str(status_s or "") == "import":
        return "import"
    if model_s == "human":
        return "human"
    lower_model = model_s.lower()
    if lower_model.startswith("deepl") or "deepl" in lower_model:
        return "deepl"
    if lower_model.startswith("deepseek"):
        return "deepseek"
    if lower_model.startswith(("gpt-", "gpt4", "o1-", "o3-")):
        return "openai"
    if lower_model.startswith("claude"):
        return "anthropic"
    if model_s in {"", "human"} and status_s == "human":
        return "human"
    return "ollama"


def provider_of(entry: dict | None) -> str:
    """Return the stamped or inferred provider for a state entry."""
    if not entry:
        return "ollama"
    raw = entry.get("provider")
    if raw in PROVIDERS:
        return raw  # type: ignore[return-value]
    return infer_provider(entry)


SOURCE_CLASSES = ("human", "tm", "mt", "ai", "imported")
_MT_PROVIDERS = frozenset({"deepl", "ctranslate2"})


def source_class(provider: str | None, trigger: str | None = None) -> str:
    """Throughput class of one translated key: human, tm, mt, ai or imported.

    ``trigger`` is the latest history event; a TM hit is machine output only in
    the sense that no person and no model wrote it. A missing provider stamp is
    read through :func:`infer_provider` upstream, never guessed here.
    """
    if provider == "human":
        return "human"
    if provider == "import":
        return "imported"
    if trigger == "tm-hit":
        return "tm"
    if provider in _MT_PROVIDERS:
        return "mt"
    return "ai"
