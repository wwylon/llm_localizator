"""Opt-in request timing for the review server (Wave 0).

Enable with ``?profile=1``, JSON body ``"profile": true``, env
``LLM_LOCALIZE_WEB_PROFILE=1``, or ``[web] profile = true``. When off, spans
are no-ops.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

__all__ = [
    "Profiling",
    "enabled_for_request",
    "enabled_from_env_or_cfg",
    "reset",
    "span",
    "spans_dict",
    "server_timing_header",
    "attach_timing",
    "total_ms",
]

_local = threading.local()


def _stack() -> dict[str, Any] | None:
    return getattr(_local, "prof", None)


class Profiling:
    """Active request profiler (thread-local)."""

    __slots__ = ("spans", "started", "enabled")

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.spans: dict[str, float] = {}
        self.started = time.perf_counter()

    def add(self, name: str, ms: float) -> None:
        if not self.enabled:
            return
        self.spans[name] = round(self.spans.get(name, 0.0) + ms, 3)

    def total_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000.0, 3)


def reset(*, enabled: bool = True) -> Profiling:
    prof = Profiling(enabled=enabled)
    _local.prof = prof
    return prof


def clear() -> None:
    _local.prof = None


def enabled_from_env_or_cfg(cfg=None) -> bool:
    env = (os.environ.get("LLM_LOCALIZE_WEB_PROFILE") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if cfg is not None and bool(getattr(cfg, "web_profile", False)):
        return True
    return False


def enabled_for_request(
    *,
    query_profile: str | None = None,
    body: dict | None = None,
    cfg=None,
) -> bool:
    if query_profile and str(query_profile).strip().lower() in ("1", "true", "yes", "on"):
        return True
    if isinstance(body, dict):
        raw = body.get("profile")
        if raw is True or str(raw).strip().lower() in ("1", "true", "yes", "on"):
            return True
    return enabled_from_env_or_cfg(cfg)


@contextmanager
def span(name: str) -> Iterator[None]:
    prof = _stack()
    if prof is None or not prof.enabled:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        prof.add(name, (time.perf_counter() - t0) * 1000.0)


def spans_dict() -> dict[str, float]:
    prof = _stack()
    if prof is None:
        return {}
    return dict(prof.spans)


def total_ms() -> float:
    prof = _stack()
    if prof is None:
        return 0.0
    return prof.total_ms()


def server_timing_header(response_bytes: int | None = None) -> str:
    """RFC 7233-ish Server-Timing value from current spans."""
    prof = _stack()
    if prof is None or not prof.enabled:
        return ""
    parts: list[str] = []
    for name, ms in prof.spans.items():
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)[:64]
        parts.append(f"{safe};dur={ms:.3f}")
    parts.append(f"total;dur={prof.total_ms():.3f}")
    if response_bytes is not None:
        parts.append(f"responseBytes;desc=\"{response_bytes}\"")
    return ", ".join(parts)


def attach_timing(payload: Any, *, response_bytes: int | None = None) -> Any:
    """Inject ``_timing`` into a JSON-serializable dict payload when profiling."""
    prof = _stack()
    if prof is None or not prof.enabled:
        return payload
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    timing = {
        "spans": dict(prof.spans),
        "totalMs": prof.total_ms(),
    }
    if response_bytes is not None:
        timing["responseBytes"] = response_bytes
    out["_timing"] = timing
    return out
