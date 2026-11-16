from dataclasses import dataclass

import pytest

from llm_localizator.pipeline.planning import dry_run_messages, pin_run_model, plan_batches


@dataclass(frozen=True)
class Item:
    text: str
    screen: str | None


def test_plan_batches_keeps_singles_first_and_chunks_by_screen():
    items = [
        Item("one two", "a"),
        Item("long source text here", "a"),
        Item("another long source here", "b"),
        Item("third long source here", "a"),
    ]

    batches = plan_batches(items, 2, source_of=lambda item: item.text, screen_of=lambda item: item.screen)

    assert batches == [[items[0]], [items[1], items[3]], [items[2]]]


def test_plan_batches_rejects_invalid_size():
    with pytest.raises(ValueError, match="batch_size"):
        plan_batches([], 0, source_of=lambda item: item.text, screen_of=lambda item: item.screen)


def test_pin_run_model_uses_single_model():
    items = [Item("a", None), Item("b", None)]
    assert pin_run_model(items, model_for=lambda _: "aya", fallback="default") == ("aya", {"aya"})


def test_pin_run_model_uses_fallback_for_mixed_models():
    items = [Item("a", None), Item("b", None)]
    assert pin_run_model(items, model_for=lambda item: "aya" if item.text == "a" else "qwen", fallback="default") == (
        "default", {"aya", "qwen"}
    )


def test_dry_run_messages_include_progress():
    items = [Item("a", None), Item("b", None)]
    assert dry_run_messages(items, label_of=lambda item: item.text) == [
        "[1/2] a (50.0%)",
        "[2/2] b (100.0%)",
    ]
