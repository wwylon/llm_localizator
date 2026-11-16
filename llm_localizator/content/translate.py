"""Translate one content unit from its own source language. No English pivot."""

from __future__ import annotations

from ..core.cldr import language_name
from ..core.hash import src_hash
from ..providers.base import CompletionRequest, ProviderError
from .contract import Cell, ContentUnit, classify, needs_write

__all__ = ["content_prompt", "plan_writes"]


def content_prompt(unit: ContentUnit, target_locale: str, *, domain: str) -> str:
    source = language_name(unit.source_locale)
    target = language_name(target_locale)
    note = f"Content type: {unit.note}\n" if unit.note else ""
    return (
        f"Translate the following {domain} text from {source} to {target}.\n"
        f"{note}"
        "Output ONLY the translation. Do not explain. Do not add quotes.\n"
        "Do not translate through any other language.\n"
        "\n"
        f"{unit.source_text}"
    )


def plan_writes(
    units: list[ContentUnit],
    locales: list[str],
    *,
    force: bool = False,
) -> list[tuple[ContentUnit, Cell]]:
    work: list[tuple[ContentUnit, Cell]] = []
    for unit in units:
        for cell in classify(unit, locales):
            if needs_write(cell, force=force):
                work.append((unit, cell))
    return work


def translation_body(unit: ContentUnit, text: str, *, provider: str, model: str) -> dict:
    return {
        "text": text,
        "src_sha": src_hash(unit.source_text),
        "source_locale": unit.source_locale,
        "provider": provider,
        "model": model,
        "status": "machine",
    }


def complete_unit(provider, unit: ContentUnit, target_locale: str, *, model: str, domain: str) -> str:
    prompt = content_prompt(unit, target_locale, domain=domain)
    text = provider.complete(CompletionRequest(
        prompt=prompt,
        model=model,
        source_texts=[unit.source_text],
        target_locale=target_locale,
    ))
    cleaned = (text or "").strip()
    if not cleaned:
        raise ProviderError(f"empty translation for {unit.id} -> {target_locale}")
    from ..pipeline.candidates import validate_candidate

    accepted, reason = validate_candidate(
        unit.source_text, cleaned, target_locale, {},
    )
    if accepted is None:
        raise ProviderError(
            f"rejected translation for {unit.id} -> {target_locale}: {reason}"
        )
    return accepted
