"""Placeholder masking before LLM translation."""

from __future__ import annotations

from llm_localizator.pipeline.placeholder_mask import mask_bare_placeholders, restore_placeholders
from llm_localizator.pipeline.prompts import BatchItem, build_single_prompt
from llm_localizator.pipeline.candidates import validate_candidate


def test_mask_replaces_bare_placeholders_with_numbers() -> None:
    masked, mapping = mask_bare_placeholders("{players} players · {tables} tables")
    assert "{players}" not in masked
    assert "{tables}" not in masked
    assert "players" in masked
    assert "tables" in masked
    assert len(mapping) == 2
    assert set(mapping.values()) == {"{players}", "{tables}"}


def test_restore_swaps_numbers_back() -> None:
    source = "{players} players · {tables} tables"
    masked, mapping = mask_bare_placeholders(source)
    tokens = list(mapping.keys())
    restored = restore_placeholders(
        f"{tokens[0]} graczy · {tokens[1]} stoły", mapping,
    )
    assert restored == "{players} graczy · {tables} stoły"


def test_plural_clause_is_not_masked() -> None:
    source = "{n, plural, one {# player} other {# players}}"
    masked, mapping = mask_bare_placeholders(source)
    assert masked == source
    assert mapping == {}


def test_tokens_avoid_existing_digits() -> None:
    source = "Version 900000001: {players} players"
    masked, mapping = mask_bare_placeholders(source)
    token = next(iter(mapping))
    assert token != "900000001"
    assert token in masked


def test_validate_candidate_restores_masked_output() -> None:
    source = "{players} players"
    masked, mapping = mask_bare_placeholders(source)
    token = next(iter(mapping))
    accepted, reason = validate_candidate(
        source, f"{token} graczy", "pl", {},
        placeholder_mask=mapping,
    )
    assert reason is None
    assert accepted == "{players} graczy"


def test_masked_source_in_prompt() -> None:
    masked, mapping = mask_bare_placeholders("{players} players · {tables} tables")
    item = BatchItem(
        source="{players} players · {tables} tables",
        prompt_source=masked,
        placeholder_mask=mapping,
    )
    prompt = build_single_prompt(item, "Polish", "a bridge card-game web application", "")
    assert masked in prompt
    assert "{players}" not in prompt.split("String to translate:")[1]
    assert "numeric stand-ins" in prompt
    token = sorted(mapping)[0]
    assert token in prompt
