"""Minimal-edit prompt: update an existing translation after a small source change (C-041, ADR-100).

A separate prompt that only runs for the opt-in ``minimal-edit`` draft job. The normal
translate prompt and its snapshots are untouched. The result is a draft for review; a
heuristic never blocks it (ADR-8) and no state key or context fingerprint is involved (ADR-7).
"""

from __future__ import annotations

import json
import re

from ..providers import CompletionRequest, Provider, complete_for

__all__ = ["MINIMAL_EDIT_SCHEMA", "build_minimal_edit_prompt", "minimal_edit", "parse_minimal_edit"]

MINIMAL_EDIT_SCHEMA: dict = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def build_minimal_edit_prompt(old_source: str, new_source: str, old_translation: str, language: str) -> str:
    return (
        f"A UI string was translated into {language}. The English source then changed a little. "
        f"Edit the existing translation as little as possible so that it matches the new source. "
        f"Keep every word that is still correct; change only what the source change requires. "
        f"Keep placeholders such as {{name}} or %s exactly as in the new source.\n\n"
        f"Old source: {old_source}\n"
        f"New source: {new_source}\n"
        f"Current {language} translation (of the old source): {old_translation}\n\n"
        f"Reply with JSON only: {{\"text\": \"the updated {language} translation\"}}."
    )


def parse_minimal_edit(raw: str) -> str:
    """The updated text, or an empty string when the reply cannot be read."""
    text = (raw or "").strip()
    for candidate in (text, (re.search(r"\{.*\}", text, re.DOTALL) or [None])[0]):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        value = data.get("text") if isinstance(data, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def minimal_edit(
    provider: Provider, model: str, *, old_source: str, new_source: str,
    old_translation: str, language: str, cfg=None, locale: str = "",
) -> str:
    raw = complete_for(cfg, provider, locale, CompletionRequest(
        prompt=build_minimal_edit_prompt(old_source, new_source, old_translation, language),
        model=model, schema=MINIMAL_EDIT_SCHEMA,
    ))
    return parse_minimal_edit(raw)
