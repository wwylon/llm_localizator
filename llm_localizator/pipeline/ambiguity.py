"""Ambiguity notes: the model names source terms with several senses (C-033, ADR-90).

Advisory text for the reviewer. It never feeds scores, state keys or the context
fingerprint (ADR-7), and a heuristic result only informs, never blocks (ADR-8).
"""

from __future__ import annotations

import json
import re

from ..providers import CompletionRequest, Provider, ProviderError, complete_for

__all__ = ["AMBIGUITY_SCHEMA", "MAX_NOTES", "ambiguity_notes", "build_ambiguity_prompt", "parse_ambiguity"]

MAX_NOTES = 3
_FIELD_MAX = 160

AMBIGUITY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "senses": {"type": "array", "items": {"type": "string"}},
                    "chosen": {"type": "string"},
                },
                "required": ["term", "chosen"],
            },
        },
    },
    "required": ["notes"],
}


def build_ambiguity_prompt(source: str, translated: str, language: str, context: str = "") -> str:
    ctx = f"Context: {context}\n" if context else ""
    return (
        f"A UI string was translated into {language}. Find words or phrases in the source that "
        f"could mean more than one thing in {language}, and say which sense the translation uses.\n"
        f"{ctx}"
        f"Source: {source}\n"
        f"Translation: {translated}\n\n"
        f"Reply with JSON only: {{\"notes\": [{{\"term\": \"...\", \"senses\": [\"...\"], "
        f"\"chosen\": \"...\"}}]}}. At most {MAX_NOTES} notes. Use an empty list when nothing is "
        f"genuinely ambiguous; do not invent doubts."
    )


def _clip(value: object) -> str:
    return str(value).strip()[:_FIELD_MAX] if isinstance(value, (str, int, float)) else ""


def parse_ambiguity(raw: str) -> list[dict]:
    """Notes as ``[{term, senses, chosen}]``; anything unparseable gives an empty list."""
    text = (raw or "").strip()
    data = None
    for candidate in (text, (re.search(r"\{.*\}", text, re.DOTALL) or [None])[0]):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    rows = data.get("notes") if isinstance(data, dict) else None
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        term, chosen = _clip(row.get("term")), _clip(row.get("chosen"))
        if not term or not chosen:
            continue
        senses = row.get("senses")
        out.append({
            "term": term, "chosen": chosen,
            "senses": [s for s in (_clip(x) for x in (senses if isinstance(senses, list) else [])) if s][:4],
        })
        if len(out) >= MAX_NOTES:
            break
    return out


def ambiguity_notes(
    provider: Provider, model: str, *, source: str, translated: str, language: str,
    context: str = "", timeout_s: int = 60, cfg=None, locale: str = "",
) -> list[dict]:
    """One extra model call. A failing provider gives no notes rather than an error."""
    try:
        raw = complete_for(cfg, provider, locale, CompletionRequest(
            prompt=build_ambiguity_prompt(source, translated, language, context),
            model=model, schema=AMBIGUITY_SCHEMA, timeout_s=timeout_s,
            options={"temperature": 0.1}, source_texts=[source], target_locale=None,
        ))
    except ProviderError:
        return []
    return parse_ambiguity(raw)
