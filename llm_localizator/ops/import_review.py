"""``import-review``: apply the decisions of a ``review-risk --format csv`` sheet (A6, ADR-135).

A reviewer fills the ``decision`` column:

* empty or ``keep`` — nothing to do;
* ``suggestion`` (or ``accept``) — write the judge's suggestion;
* anything else — that text is the translation.

Every write goes through ``set --by human`` (the candidate gate, ADR-19/48 stamps), so
an import cannot write what ``set`` would reject. ``dry_run`` reports without writing.
The written corrections then feed ``glossary-learn``.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..projects import ProjectConfig
from .set_translation import op_set
from .types import OpResult

__all__ = ["op_import_review", "decision_text"]

_KEEP = frozenset({"", "keep", "ok", "-"})
_ACCEPT = frozenset({"suggestion", "accept", "suggested"})


def decision_text(row: dict) -> str | None:
    """The translation a row asks for, or None to leave the key alone."""
    decision = (row.get("decision") or "").strip()
    if decision.casefold() in _KEEP:
        return None
    if decision.casefold() in _ACCEPT:
        return (row.get("suggestion") or "").strip() or None
    return decision


def op_import_review(cfg: ProjectConfig, *, locale: str, path: str | Path,
                     dry_run: bool = False) -> OpResult:
    command = "import-review"
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        return OpResult(ok=False, exit_code=2, command=command, summary=f"cannot read {path}: {exc}")
    if rows and not {"key", "decision"} <= set(rows[0]):
        return OpResult(ok=False, exit_code=2, command=command,
                        summary="not a review-risk CSV: needs key and decision columns")
    written, rejected, skipped = [], [], 0
    lines: list[str] = []
    for row in rows:
        text = decision_text(row)
        key = (row.get("key") or "").strip()
        if text is None or not key:
            skipped += 1
            continue
        if text == (row.get("current") or "").strip():
            skipped += 1
            continue
        if dry_run:
            lines.append(f"would set {key}: {row.get('current')!r} -> {text!r}")
            written.append(key)
            continue
        result = op_set(cfg, locale=locale, key=key, text=text, by="human")
        if result.ok:
            written.append(key)
            lines.append(f"set {key}: {text!r}")
        else:
            rejected.append({"key": key, "text": text, "reason": result.summary})
            lines.append(f"REJECTED {key}: {result.summary}")
    verb = "would write" if dry_run else "wrote"
    return OpResult(
        ok=not rejected, exit_code=0 if not rejected else 1, command=command,
        summary=f"{verb} {len(written)}, rejected {len(rejected)}, unchanged {skipped}",
        lines=lines, data={"written": written, "rejected": rejected, "skipped": skipped},
    )
