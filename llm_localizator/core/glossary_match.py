"""Source-aware glossary matching for prompts (aligned with V04/V13).

Validation already only fires when a term appears in the English source.
Prompts historically dumped every locale term into the preamble; these helpers
inject only hits that match the string being translated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .validate import source_term_pattern, term_pattern

__all__ = [
    "GlossaryHit",
    "glossary_hits",
    "format_glossary_annotation",
    "dnt_terms_in_sources",
]


@lru_cache(maxsize=8192)
def _dnt_re(term: str) -> re.Pattern:
    return re.compile(term_pattern(term))


@lru_cache(maxsize=8192)
def _term_re(term: str) -> re.Pattern:
    return re.compile(source_term_pattern(term), re.IGNORECASE)


@dataclass(frozen=True)
class GlossaryHit:
    term: str
    kind: str  # "term" | "dnt"
    target: str | None = None
    forbidden: tuple[str, ...] = ()
    note: str = ""
    forms: tuple[str, ...] = ()


def glossary_hits(
    source: str, glossary: dict, locale: str,
) -> list[GlossaryHit]:
    """Return glossary entries present in *source* for *locale*."""
    glossary = glossary or {}
    hits: list[GlossaryHit] = []
    en = source or ""

    for term in glossary.get("doNotTranslate", []):
        if not term:
            continue
        if _dnt_re(term).search(en) is not None:
            hits.append(GlossaryHit(term=term, kind="dnt"))

    for term, data in glossary.get("terms", {}).items():
        if not term or not isinstance(data, dict):
            continue
        if _term_re(term).search(en) is None:
            continue
        target = data.get(locale)
        forbidden_raw = data.get(f"{locale}_forbidden") or []
        forbidden = tuple(str(x) for x in forbidden_raw if x)
        forms = tuple(str(x) for x in (data.get(f"{locale}_forms") or []) if x)
        note = str(
            data.get(f"{locale}_note") or data.get("note") or ""
        ).strip()
        hits.append(GlossaryHit(
            term=term,
            kind="term",
            target=str(target) if target else None,
            forbidden=forbidden,
            note=note,
            forms=forms,
        ))
    return hits


def format_glossary_annotation(hits: list[GlossaryHit]) -> str:
    """Compact ``[glossary: …]`` fragment for batch/single item annotations."""
    if not hits:
        return ""
    parts: list[str] = []
    for hit in hits:
        if hit.kind == "dnt":
            parts.append(f"keep '{hit.term}'")
            continue
        bit = f"use '{hit.term}'"
        if hit.target:
            bit += f"→'{hit.target}'"
            if hit.forms:
                bit += f" (also: {', '.join(hit.forms)})"
        if hit.forbidden:
            bit += f"; never: {', '.join(hit.forbidden)}"
        if hit.note:
            # Keep notes short in the annotation line.
            note = hit.note if len(hit.note) <= 80 else hit.note[:77] + "…"
            bit += f" ({note})"
        parts.append(bit)
    return "[glossary: " + "; ".join(parts) + "]"


def dnt_terms_in_sources(glossary: dict, sources: list[str]) -> list[str]:
    """DNT terms that appear in at least one of *sources*."""
    dnt = glossary.get("doNotTranslate", []) if glossary else []
    if not dnt or not sources:
        return []
    joined = "\n".join(sources)
    return [
        term for term in dnt
        if term and _dnt_re(term).search(joined) is not None
    ]
