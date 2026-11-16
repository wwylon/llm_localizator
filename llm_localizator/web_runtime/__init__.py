"""The browser i18n runtime consumers ship (plan Part C, C5; ADR-118).

``i18n.js`` is copied into a consumer by ``llm-localizator runtime install``;
``i18n.config.js`` is the per-project template written next to it once.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["RUNTIME_DIR", "RUNTIME_FILE", "CONFIG_TEMPLATE", "runtime_version", "shipped_version"]

RUNTIME_DIR = Path(__file__).resolve().parent
RUNTIME_FILE = RUNTIME_DIR / "i18n.js"
CONFIG_TEMPLATE = RUNTIME_DIR / "i18n.config.js"

_VERSION_RE = re.compile(r"llm-localizator web runtime v(\d+\.\d+\.\d+)")


def runtime_version(text: str) -> str | None:
    """The version in a runtime header, or ``None`` for a file that is not ours."""
    m = _VERSION_RE.search(text[:400])
    return m.group(1) if m else None


def shipped_version() -> str:
    version = runtime_version(RUNTIME_FILE.read_text(encoding="utf-8"))
    if version is None:  # pragma: no cover - guarded by tests
        raise RuntimeError("shipped i18n.js has no version header")
    return version
