"""Shared HTTP retry for cloud providers (W-12 / F.7).

Retries only 429 and 5xx with capped exponential backoff. Other 4xx fail
once. Honours a sane Retry-After header. Ollama does not use this helper.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import ProviderError

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_DELAY_S",
    "is_retryable_http",
    "retry_after_delay",
    "urlopen_json",
]

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY_S = 1.0
DEFAULT_MAX_DELAY_S = 8.0

SleepFn = Callable[[float], None]
UrlOpenFn = Callable[..., Any]


def is_retryable_http(code: int) -> bool:
    """True for 429 and 5xx only."""
    return code == 429 or 500 <= code <= 599


def retry_after_delay(headers: Any, fallback: float, *, max_delay: float = DEFAULT_MAX_DELAY_S) -> float:
    """Parse Retry-After (seconds). Invalid or missing → *fallback*, capped."""
    raw = None
    if headers is not None:
        try:
            raw = headers.get("Retry-After")
        except Exception:
            raw = None
    if raw is None or raw == "":
        return min(max(fallback, 0.0), max_delay)
    try:
        seconds = float(str(raw).strip())
    except (TypeError, ValueError):
        return min(max(fallback, 0.0), max_delay)
    if seconds < 0:
        return min(max(fallback, 0.0), max_delay)
    return min(seconds, max_delay)


def urlopen_json(
    req: urllib.request.Request,
    timeout_s: float | int,
    kind: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
    sleep: SleepFn = time.sleep,
    urlopen: UrlOpenFn | None = None,
) -> dict:
    """POST/GET *req* and return parsed JSON, with cloud retry policy."""
    opener = urlopen or urllib.request.urlopen
    attempts = max(1, int(max_attempts))
    delay = float(base_delay_s)
    last_error: ProviderError | None = None
    for attempt in range(attempts):
        try:
            with opener(req, timeout=timeout_s) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            last_error = ProviderError(f"{kind} HTTP {exc.code}: {detail}")
            # Attach code for callers that special-case 400 (DeepL formality).
            last_error.http_code = exc.code  # type: ignore[attr-defined]
            last_error.http_detail = detail  # type: ignore[attr-defined]
            if not is_retryable_http(exc.code) or attempt >= attempts - 1:
                raise last_error from exc
            wait = retry_after_delay(exc.headers, delay, max_delay=max_delay_s)
            sleep(wait)
            delay = min(delay * 2, max_delay_s)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            # Transient network failure: retried like a 5xx, then reported.
            if isinstance(exc, urllib.error.URLError):
                last_error = ProviderError(f"{kind} unreachable: {exc}")
            else:
                last_error = ProviderError(f"{kind} request failed: {exc}")
            if attempt >= attempts - 1:
                raise last_error from exc
            sleep(min(delay, max_delay_s))
            delay = min(delay * 2, max_delay_s)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{kind} request failed: {exc}") from exc
    if last_error is not None:
        raise last_error
    raise ProviderError(f"{kind} request failed")
