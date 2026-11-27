"""Visual findings JSONL schema (ADR-27) — parse/validate consumer capture output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "SCHEMA_VERSION",
    "REASONS",
    "SOURCES",
    "CRAWL_KIND_TO_REASON",
    "VisualFinding",
    "VisualFindingsError",
    "crawl_kind_to_reason",
    "parse_finding",
    "iter_findings",
    "default_findings_path",
]

SCHEMA_VERSION = 1

REASONS = frozenset({
    "layout_overflow",
    "layout_clip",
    "layout_heuristic",
    "layout_overlap",
    "en_leak",
    "icu_leak",
    "glossary",
    "other",
})

SOURCES = frozenset({
    "browse-review",
    "dogfood-harness",
    "tq-smoke",
    "manual",
})

#: ``layout.json`` issue ``kind`` → visual-findings ``reason`` (ADR-119 / TiMi overlap).
CRAWL_KIND_TO_REASON = {
    "clipped": "layout_clip",
    "offscreen": "layout_overflow",
    "overlap": "layout_overlap",
}


def crawl_kind_to_reason(kind: str) -> str | None:
    """Map a QA-crawl layout ``kind`` to a findings reason, or ``None`` if unknown."""
    return CRAWL_KIND_TO_REASON.get(str(kind or "").strip().lower())


class VisualFindingsError(ValueError):
    """Invalid visual findings record or schema version."""


@dataclass(frozen=True)
class VisualFinding:
    schema_version: int
    locale: str
    screen: str
    reason: str
    message: str
    path: str | None = None
    namespace: str | None = None
    key: str | None = None
    screenshot: str | None = None
    selector: str | None = None
    source: str | None = None
    ts: str | None = None

    def ticket_namespace(self) -> str:
        if self.namespace and self.namespace.strip():
            return self.namespace.strip()
        return "_visual"

    def ticket_key(self) -> str:
        if self.key and str(self.key).strip():
            return str(self.key).strip()
        screen = (self.screen or "page").strip() or "page"
        return f"@{screen}"


def default_findings_path(context_dir: Path | None, root: Path) -> Path:
    """Sibling ``.visual_findings.jsonl`` next to ``context_dir``, else project root."""
    if context_dir is not None:
        return Path(context_dir).resolve().parent / ".visual_findings.jsonl"
    return Path(root).resolve() / ".visual_findings.jsonl"


def parse_finding(raw: dict[str, Any]) -> VisualFinding:
    try:
        version = int(raw.get("schema_version", -1))
    except (TypeError, ValueError) as exc:
        raise VisualFindingsError("schema_version must be an integer") from exc
    if version != SCHEMA_VERSION:
        raise VisualFindingsError(
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}"
        )
    locale = str(raw.get("locale") or "").strip()
    screen = str(raw.get("screen") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    message = str(raw.get("message") or "").strip()
    if not locale:
        raise VisualFindingsError("locale is required")
    if not screen:
        raise VisualFindingsError("screen is required")
    if reason not in REASONS:
        raise VisualFindingsError(
            f"unknown reason {reason!r}; expected one of {sorted(REASONS)}"
        )
    if not message:
        raise VisualFindingsError("message is required")
    source = raw.get("source")
    source_s = str(source).strip() if source else None
    if source_s and source_s not in SOURCES:
        raise VisualFindingsError(
            f"unknown source {source_s!r}; expected one of {sorted(SOURCES)}"
        )
    ns = raw.get("namespace")
    key = raw.get("key")
    return VisualFinding(
        schema_version=version,
        locale=locale,
        screen=screen,
        reason=reason,
        message=message,
        path=(str(raw["path"]).strip() or None) if raw.get("path") else None,
        namespace=(str(ns).strip() or None) if ns is not None and str(ns).strip() else None,
        key=(str(key).strip() or None) if key is not None and str(key).strip() else None,
        screenshot=(str(raw["screenshot"]).strip() or None) if raw.get("screenshot") else None,
        selector=(str(raw["selector"]).strip() or None) if raw.get("selector") else None,
        source=source_s,
        ts=(str(raw["ts"]).strip() or None) if raw.get("ts") else None,
    )


def iter_findings(path: Path) -> Iterator[VisualFinding]:
    """Yield findings from a JSONL file; skip blank lines."""
    text = Path(path).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise VisualFindingsError(f"{path}:{line_no}: invalid JSON") from exc
        if not isinstance(raw, dict):
            raise VisualFindingsError(f"{path}:{line_no}: expected a JSON object")
        try:
            yield parse_finding(raw)
        except VisualFindingsError as exc:
            raise VisualFindingsError(f"{path}:{line_no}: {exc}") from exc
