"""Shared helpers for cloud async batch APIs (Anthropic Message Batches, OpenAI Batch).

Both providers create a batch, poll it, download a JSONL result file and match
rows back by ``custom_id``. The pieces that must behave the same everywhere live
here: the retried JSONL download, ``custom_id`` normalisation, best-effort
cancel on timeout, and :class:`PartialBatchError`, which lets callers keep the
items that succeeded (already paid for) when some items failed.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import ProviderError
from .http_retry import is_retryable_http

__all__ = ["PartialBatchError", "batch_custom_ids", "fetch_jsonl", "best_effort_cancel"]


class PartialBatchError(ProviderError):
    """Some batch items failed. ``results[i]`` is the text, or ``None`` on failure.

    The provider has already set ``last_usage`` for the whole batch, so the
    caller can bill it and retry only the failed items.
    """

    def __init__(self, message: str, results: list[str | None], errors: dict[int, str]) -> None:
        super().__init__(message)
        self.results = results
        self.errors = errors


def batch_custom_ids(raw_ids: list[str | None]) -> list[str]:
    """API-safe, unique ``custom_id`` values (<= 64 chars, no ``:``).

    Truncation can make two ids equal; a numeric suffix keeps them distinct so
    results never overwrite each other when matched back.
    """
    out: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_ids):
        cid = (raw or f"req-{i}").replace(":", "_")[:64]
        if cid in seen:
            suffix = f"-{i}"
            cid = cid[: 64 - len(suffix)] + suffix
        seen.add(cid)
        out.append(cid)
    return out


def fetch_jsonl(
    req: urllib.request.Request,
    label: str,
    *,
    timeout: float = 120,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Download and parse a JSONL result file, retrying transient failures.

    Every failure surfaces as :class:`ProviderError` (never a bare URLError or
    JSONDecodeError), so a run reports skipped keys instead of crashing.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
            rows: list[dict[str, Any]] = []
            for line in payload.decode("utf-8").splitlines():
                line = line.strip()
                if line:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
            return rows
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            if not is_retryable_http(exc.code):
                raise ProviderError(f"{label} batch results HTTP {exc.code}: {detail}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            # ValueError covers JSONDecodeError / UnicodeDecodeError (cut-off body).
            last = exc
        if attempt + 1 < attempts:
            sleep(min(30.0, 2.0 * (2 ** attempt)))
    raise ProviderError(f"{label} batch results download failed: {last}") from last


def best_effort_cancel(req: urllib.request.Request) -> None:
    """Ask the API to cancel a batch we stopped waiting for; never raises."""
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except Exception:  # cancel is advisory; the timeout error is what matters
        pass
