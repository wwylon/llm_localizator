"""Content-unit JSON. No network.

A unit is one translatable field. Its source language is whatever the author
typed, not the project's catalogue ``source_locale``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.hash import src_hash

__all__ = [
    "HUMAN_STATUSES",
    "Cell",
    "ContentUnit",
    "ContractError",
    "TargetState",
    "classify",
    "needs_write",
    "normalize_locale",
    "parse_page",
    "parse_unit",
]

_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
HUMAN_STATUSES = frozenset({"human", "human_verified"})
_API_STATUSES = HUMAN_STATUSES | {"missing", "stale", "machine"}


class ContractError(ValueError):
    """The project API returned a unit this engine will not guess about."""


def normalize_locale(value: object) -> str:
    """``en_us`` and ``en-US`` are the same locale. Does not invent a language."""
    if not isinstance(value, str):
        raise ContractError(f"locale must be a string, got {type(value).__name__}")
    text = value.strip().replace("_", "-")
    if not text:
        raise ContractError("locale is empty")
    parts = text.split("-")
    parts[0] = parts[0].lower()
    if len(parts) > 1 and len(parts[1]) == 2 and parts[1].isalpha():
        parts[1] = parts[1].upper()
    text = "-".join(parts)
    if not _LOCALE.match(text):
        raise ContractError(f"invalid locale {value!r}")
    return text


def _unit_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("unit id is required")
    text = value.strip()
    if "\\" in text or text.startswith("/") or any(part in {"", ".", ".."} for part in text.split("/")):
        raise ContractError(f"invalid unit id {value!r}")
    return text


@dataclass(frozen=True)
class TargetState:
    status: str
    text: str = ""
    src_sha: str = ""


@dataclass(frozen=True)
class ContentUnit:
    id: str
    source_locale: str
    source_text: str
    translate: bool = True
    note: str = ""
    targets: dict[str, TargetState] = field(default_factory=dict)


@dataclass(frozen=True)
class Cell:
    """One target locale after the engine's rules, not the raw API status."""

    locale: str
    status: str
    locked: bool = False


def parse_page(payload: object) -> tuple[list[ContentUnit], str | None]:
    if not isinstance(payload, dict):
        raise ContractError("units response must be an object")
    raw = payload.get("units")
    if not isinstance(raw, list):
        raise ContractError("units response must contain a units array")
    units = [parse_unit(item) for item in raw]
    cursor = payload.get("next_cursor") or None
    if cursor is not None and not isinstance(cursor, str):
        raise ContractError("next_cursor must be a string")
    return units, cursor


def parse_unit(item: object) -> ContentUnit:
    if not isinstance(item, dict):
        raise ContractError("unit must be an object")
    unit_id = _unit_id(item.get("id"))
    if "source_locale" not in item or item.get("source_locale") in (None, ""):
        raise ContractError(f"{unit_id}: source_locale is required")
    source_locale = normalize_locale(item.get("source_locale"))
    source_text = item.get("source_text")
    if not isinstance(source_text, str):
        raise ContractError(f"{unit_id}: source_text must be a string")
    translate = item.get("translate", True)
    if not isinstance(translate, bool):
        raise ContractError(f"{unit_id}: translate must be a boolean")
    note = item.get("note") or ""
    if not isinstance(note, str):
        raise ContractError(f"{unit_id}: note must be a string")
    raw_targets = item.get("targets") or {}
    if not isinstance(raw_targets, dict):
        raise ContractError(f"{unit_id}: targets must be an object")
    targets: dict[str, TargetState] = {}
    for key, raw in raw_targets.items():
        locale = normalize_locale(key)
        targets[locale] = _parse_target(unit_id, locale, raw)
    return ContentUnit(
        id=unit_id,
        source_locale=source_locale,
        source_text=source_text,
        translate=translate,
        note=note,
        targets=targets,
    )


def _parse_target(unit_id: str, locale: str, raw: object) -> TargetState:
    if not isinstance(raw, dict):
        raise ContractError(f"{unit_id}: target {locale} must be an object")
    status = raw.get("status") or "missing"
    if not isinstance(status, str) or status not in _API_STATUSES:
        raise ContractError(f"{unit_id}: target {locale} has unknown status {status!r}")
    text = raw.get("text") or ""
    src = raw.get("src_sha") or ""
    if not isinstance(text, str) or not isinstance(src, str):
        raise ContractError(f"{unit_id}: target {locale} text and src_sha must be strings")
    return TargetState(status=status, text=text, src_sha=src)


def classify(unit: ContentUnit, locales: list[str]) -> list[Cell]:
    """What each configured target is, given this unit's source language."""
    cells: list[Cell] = []
    expected = src_hash(unit.source_text)
    for raw in locales:
        locale = normalize_locale(raw)
        if not unit.translate or not unit.source_text.strip():
            cells.append(Cell(locale, "skipped"))
            continue
        if locale == unit.source_locale:
            cells.append(Cell(locale, "source"))
            continue
        target = unit.targets.get(locale)
        if target is None or target.status == "missing":
            cells.append(Cell(locale, "missing"))
            continue
        locked = target.status in HUMAN_STATUSES
        if target.status == "stale" or target.src_sha != expected:
            cells.append(Cell(locale, "stale", locked=locked))
            continue
        if locked:
            cells.append(Cell(locale, "human", locked=True))
            continue
        cells.append(Cell(locale, "machine"))
    return cells


def needs_write(cell: Cell, *, force: bool = False) -> bool:
    """Human rows stay unless forced. The source locale is never a write."""
    if cell.status in {"skipped", "source"}:
        return False
    if cell.locked or cell.status in {"human", "agent", "imported"}:
        return force
    if cell.status in {"missing", "stale"}:
        return True
    return bool(force and cell.status == "machine")
