"""LLM backend interface.

One method, ``complete``. Everything above this layer receives a provider
*instance* and never reaches for a module-level function -- which is what makes
the pipeline testable without a GPU, and what makes a signature change a loud
error instead of a silently-inert test double (ADR-5).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

__all__ = ["Provider", "ProviderError", "CompletionRequest"]


class ProviderError(RuntimeError):
    """The backend could not produce a completion. Callers treat this as a skip."""


@dataclass
class CompletionRequest:
    prompt: str
    model: str
    schema: dict | None = None
    timeout_s: int = 300
    options: dict = field(default_factory=dict)
    # Structured metadata lets non-LLM providers avoid scraping rendered
    # prompts. Existing callers may continue to use prompt/options only.
    source_texts: list[str] | None = None
    target_locale: str | None = None
    # Base64-encoded images for a multimodal request (Ollama's native
    # ``images`` field). Only meaningful when ``model`` is vision-capable.
    images: list[str] | None = None
    # Stable prefix for prompt caching (Anthropic cache_control; OpenAI /
    # DeepSeek auto prefix cache). When set, ``prompt`` is the volatile user
    # payload only. When empty, ``prompt`` remains the full monolith.
    system: str = ""
    # Opaque id for async Message/Batch APIs (maps custom_id → result).
    custom_id: str = ""


class Provider(abc.ABC):
    """A source of text completions."""

    @abc.abstractmethod
    def complete(self, request: CompletionRequest) -> str:
        """Return the model's text response.

        Raises :class:`ProviderError` on any failure. Implementations must not
        return ``None`` -- an empty completion is an error, not a value.
        """

    def complete_many(self, requests: list[CompletionRequest]) -> list[str]:
        """Complete several requests. Default: sequential ``complete``.

        Cloud backends that expose an async Batch API (Anthropic Message
        Batches, OpenAI Batch) override this for ~50% list-price savings when
        latency can wait (TQ cloud translate / improve / rescore).
        """
        return [self.complete(r) for r in requests]

    def health_check(self) -> bool:
        """Whether the backend is reachable. Never raises."""
        return True

    def ensure_ready(self, model: str, *, report=None) -> None:
        """Block until ``model`` can serve, or raise :class:`ProviderError`.

        Default is a cheap reachability probe. Backends that stay "up" while a
        model is still unloading/reloading (Ollama after teardown) override this
        with a real generate warmup.
        """
        if not self.health_check():
            raise ProviderError(
                f"{self.name} is not reachable. Start the model server and retry."
            )

    def usage(self) -> dict | None:
        """Token counts from the last :meth:`complete` call, or ``None``.

        Returns a dict with ``input_tokens`` and ``output_tokens`` when the
        backend exposes billing data; ``None`` otherwise. Concrete providers
        set ``self.last_usage`` as an instance attribute after each call and
        this default picks it up without requiring overrides.
        """
        return getattr(self, "last_usage", None)

    @property
    def name(self) -> str:
        return type(self).__name__
