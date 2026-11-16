"""Whole-message ICU translation and placeholder frames with sample values (ADR-124)."""

from __future__ import annotations

from llm_localizator.pipeline.candidates import validate_candidate
from llm_localizator.pipeline.frame_samples import (
    fill_frame,
    frame_sample_values,
    frame_words,
    has_icu_choice,
    is_placeholder_frame,
    restore_frame_values,
)
from llm_localizator.pipeline.placeholder_mask import mask_bare_placeholders
from llm_localizator.pipeline.prompts import (
    BatchItem,
    build_batch_prompt_parts,
    build_icu_message_prompt_parts,
    build_single_prompt_parts,
)
from llm_localizator.providers._prompt_utils import numbered_lines


def _frame_item(source: str, preview=None) -> BatchItem:
    masked, mask = mask_bare_placeholders(source)
    return BatchItem(
        source=source, prompt_source=masked, placeholder_mask=mask,
        frame_samples=frame_sample_values(source, preview),
    )


# --- frame detection and samples -------------------------------------------------

def test_short_frames_are_detected() -> None:
    assert is_placeholder_frame("{rank} of {suit}")
    assert is_placeholder_frame("{count} of {total}")
    assert is_placeholder_frame("Deal {n} of {total}")
    assert frame_words("{from}–{to} of {matched} matching · {total} total") == 3
    assert not is_placeholder_frame("{from}–{to} of {matched} matching · {total} total")
    assert not is_placeholder_frame("Save changes")  # no placeholder
    assert not is_placeholder_frame("{from}–{to}")  # nothing to translate
    assert not is_placeholder_frame("{n, plural, one {# file} other {# files}}")
    assert has_icu_choice("{who, select, you {You won} other {They won}}")
    assert not has_icu_choice("{rank} of {suit}")


def test_samples_are_plausible_and_distinct() -> None:
    samples = frame_sample_values("{rank} of {suit}")
    assert samples == {"{rank}": "Ace", "{suit}": "Spades"}
    assert fill_frame("{rank} of {suit}", samples) == "Ace of Spades"
    nums = frame_sample_values("{from}–{to} of {matched}")
    assert len(set(nums.values())) == 3, nums


def test_preview_values_win_over_synthesised_samples() -> None:
    samples = frame_sample_values("{rank} of {suit}", {"rank": "Queen", "suit": "Hearts"})
    assert samples == {"{rank}": "Queen", "{suit}": "Hearts"}


# --- prompts ---------------------------------------------------------------------

def test_single_prompt_shows_the_filled_frame_and_asks_for_stand_ins() -> None:
    item = _frame_item("{rank} of {suit}")
    _system, user = build_single_prompt_parts(item, "Polish", "a card game", "", locale="pl")
    assert '"Ace of Spades"' in user
    for token in item.placeholder_mask:
        assert f"{token} = " in user
    # The string to translate is still the last line, so MT providers and parsers find it.
    assert user.splitlines()[-1] == item.prompt_source


def test_batch_annotation_carries_the_frame_without_breaking_the_payload() -> None:
    items = [_frame_item("{count} items"), BatchItem(source="Save changes")]
    _system, user = build_batch_prompt_parts(items, "Polish", "pl", "an app", "")
    assert "[frame:" in user and '"135 items"' in user
    assert numbered_lines(user) == [items[0].prompt_source, "Save changes"]


def test_icu_message_prompt_names_categories_example_and_select_keys() -> None:
    plural = BatchItem(source="{n, plural, one {# file} other {# files}}")
    system, user = build_icu_message_prompt_parts(plural, "Polish", "pl", "an app", "")
    assert "few, many, one, other" in system
    assert "# punktów" in system  # pl plural_example
    assert "{n, plural}" in system
    assert user.splitlines()[-1] == plural.source

    select = BatchItem(source="{who, select, you {You won} other {They won}}")
    system, _user = build_icu_message_prompt_parts(select, "Polish", "pl", "an app", "")
    assert "who: other, you" in system
    assert "plural must have" not in system


# --- restoring placeholders ------------------------------------------------------

def test_masked_frame_answer_is_restored_to_the_original_placeholders() -> None:
    item = _frame_item("{rank} of {suit}")
    t1, t2 = sorted(item.placeholder_mask)
    text, why = validate_candidate(
        item.source, f"{t1} {t2}", "pl", {},
        placeholder_mask=item.placeholder_mask, frame_samples=item.frame_samples,
    )
    assert why is None and text == "{rank} {suit}"


def test_a_sample_value_echoed_back_becomes_its_placeholder_again() -> None:
    samples = {"{count}": "135", "{total}": "48"}
    assert restore_frame_values("135 z 48", samples) == "{count} z {total}"
    # An ambiguous echo (value twice) is left for validation to reject.
    assert restore_frame_values("135 z 135", {"{count}": "135"}) == "135 z 135"
    # A placeholder already present is never touched.
    assert restore_frame_values("{count} z 135", {"{count}": "135"}) == "{count} z 135"
