"""Validated config write with a per-call temp file (plan-review-7 phase 6).

The old writers shared one ``.llm-localize.toml.probe`` name, so two writers
(or a crashed one) could validate or publish each other's text. Callers hold
``project_mutation_lock`` around this.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..catalog.io import atomic_write_text
from ..projects.config import load_config

__all__ = ["write_config_atomically"]


def write_config_atomically(path: Path, new_text: str) -> str | None:
    """Validate ``new_text`` through ``load_config``, then replace ``path``.

    Returns an error message (config left untouched) or ``None`` on success.
    """
    text = new_text if new_text.endswith("\n") else new_text + "\n"
    probe = path.parent / f".llm-localizator.{uuid.uuid4().hex[:12]}.toml.probe"
    try:
        atomic_write_text(probe, text)
        try:
            load_config(probe)
        except Exception as exc:  # ConfigError and TOML errors alike
            message = str(exc).replace(str(probe.resolve()), str(path))
            return message.replace(str(probe), str(path))
        atomic_write_text(path, text)
    finally:
        probe.unlink(missing_ok=True)
    return None
