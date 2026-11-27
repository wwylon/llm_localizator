"""Shared CLI printers for :class:`~llm_localizator.ops.types.OpResult`."""

from __future__ import annotations

import json
from typing import Any


def print_result(result: Any, *, as_json: bool = False) -> int:
    """Print an op result and return its exit code.

    When ``as_json`` is true, emit ``result.data`` (or ``to_dict()``) as JSON.
    """
    if as_json:
        payload = result.data if getattr(result, "data", None) is not None else None
        if payload is None and hasattr(result, "to_dict"):
            payload = result.to_dict()
        print(json.dumps(payload if payload is not None else {}, indent=2, ensure_ascii=False, default=str))
        return int(getattr(result, "exit_code", 0) or 0)
    if getattr(result, "summary", None):
        print(result.summary)
    for line in getattr(result, "lines", None) or []:
        print(line)
    if not getattr(result, "ok", True) and not getattr(result, "summary", None):
        print("error: failed")
    return int(getattr(result, "exit_code", 0) or 0)
