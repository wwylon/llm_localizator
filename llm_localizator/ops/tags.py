"""Resolve ``--tag`` to an explicit key list (C-035, ADR-75)."""
from __future__ import annotations

from dataclasses import replace

from ..projects.config import ProjectConfig
from ..projects.context import ContextNotes, normalize_tags
from .types import OpResult

__all__ = ["apply_tags"]


def apply_tags(cfg: ProjectConfig, req, command: str):
    """Return ``(request, early_result)``.

    ``tags`` becomes ``keys`` (intersected with explicit ``keys`` when both are
    given), so every downstream path - queue overrides, cloud gate, inline run -
    sees one plain key list. No match is a clean no-op.
    """
    tags = normalize_tags(getattr(req, "tags", None))
    if not tags:
        return req, None
    found = ContextNotes(cfg.context_dir).keys_with_tags(tags)
    if req.keys:
        wanted = {k.strip() for k in req.keys}
        found = [k for k in found if k in wanted]
    if not found:
        label = ", ".join(tags)
        return req, OpResult(
            ok=True, exit_code=0, command=command,
            summary=f"no keys tagged {label}",
            lines=[f"(100%) No keys tagged {label} - nothing to do."],
        )
    return replace(req, keys=found, tags=None), None
