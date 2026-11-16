"""Hermetic snapshots of prompt shape (context knobs + families)."""

from __future__ import annotations

from llm_localizator.pipeline.prompts import BatchItem, build_batch_prompt, build_single_prompt


def test_single_prompt_includes_key_and_context() -> None:
    item = BatchItem(
        source="Board",
        message_key="play.board",
        context="bridge card game — one deal",
    )
    prompt = build_single_prompt(item, "Polish", "a bridge card-game web application", "")
    assert "Message key: play.board" in prompt
    assert "Context: bridge card game — one deal" in prompt
    assert "String to translate:\nBoard" in prompt


def test_single_prompt_mt_chat_emphasizes_one_sense() -> None:
    item = BatchItem(source="Board", message_key="play.board", context="card game")
    chat = build_single_prompt(item, "Polish", "demo", "", family="chat")
    mt = build_single_prompt(item, "Polish", "demo", "", family="mt_chat")
    assert "Pick ONE sense" in mt
    assert "Pick ONE sense" not in chat
    assert "Preserve punctuation style" in chat
    assert "Preserve punctuation style" not in mt


def test_batch_prompt_mt_chat_keeps_json_and_sense_rule() -> None:
    items = [BatchItem(source="Board", message_key="play.board")]
    prompt = build_batch_prompt(
        items, "Polish", "pl", "demo", "", family="mt_chat",
    )
    assert "JSON array" in prompt
    assert "ONE sense" in prompt
    assert "[key: play.board]" in prompt


def test_glossary_block_appears_in_preamble() -> None:
    item = BatchItem(source="Board")
    gloss = "Glossary: translate 'board' as 'rozdanie'.\n"
    prompt = build_single_prompt(item, "Polish", "demo", gloss)
    assert gloss.strip() in prompt
    assert "professional translator for demo" in prompt


def test_unknown_family_falls_back_to_chat() -> None:
    item = BatchItem(source="Save")
    prompt = build_single_prompt(item, "Polish", "demo", "", family="nope")
    assert "Preserve punctuation style" in prompt


def test_batch_prompt_allows_identical_sources_to_match() -> None:
    items = [BatchItem(source="Save"), BatchItem(source="Save"), BatchItem(source="Cancel")]
    for family in ("chat", "mt_chat"):
        prompt = build_batch_prompt(items, "Polish", "pl", "demo", "", family=family)
        assert "DISTINCT" not in prompt
        assert "Identical source strings" in prompt
