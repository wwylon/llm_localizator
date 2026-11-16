"""Single-model residency for providers that keep weights in GPU/RAM.

On laptop GPUs (6 GiB) loading a secondary while the primary is still pinned
often kills Ollama. Callers use :func:`switch` so only one model is resident.
"""

from __future__ import annotations

from typing import Any

__all__ = ["switch", "ResidencyTracker"]


class ResidencyTracker:
    """Tracks which model is warm on a provider instance."""

    __slots__ = ("warm",)

    def __init__(self, warm: str | None = None) -> None:
        self.warm = warm


def switch(
    provider: Any,
    *,
    to: str,
    tracker: ResidencyTracker | None = None,
    report=None,
) -> None:
    """Stop any other resident model, then ``ensure_ready(to)``.

    Providers without ``stop`` are still asked to ``ensure_ready``; CT2 implements
    ``stop`` so the previous Translator is dropped before the next load.
    """
    if not to:
        return
    prev = tracker.warm if tracker is not None else None
    if prev and prev != to:
        stop = getattr(provider, "stop", None)
        if callable(stop):
            try:
                stop(prev)
            except Exception:
                pass
    ensure = getattr(provider, "ensure_ready", None)
    if callable(ensure):
        ensure(to, report=report)
    if tracker is not None:
        tracker.warm = to
