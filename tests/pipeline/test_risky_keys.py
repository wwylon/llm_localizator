"""C3: errors the score cannot see on one-word keys (ADR-125)."""

from __future__ import annotations

import json

from llm_localizator.core.quality import QualityResult
from llm_localizator.pipeline.judge import SUGGESTION_PREFIX, lqs_from_judgment, suggestion_of
from llm_localizator.pipeline.scoring import (
    CONTRADICTION_CAP, apply_contradiction_cap, is_risky_key, risky_judge_model, score_candidate,
)
from llm_localizator.providers import NullProvider


def test_risky_keys_are_one_or_two_words_outside_placeholders() -> None:
    assert is_risky_key("Discard {card}")
    assert is_risky_key("Save")
    assert is_risky_key("{rank} of {suit}")
    assert not is_risky_key("Make a small image big.")
    assert not is_risky_key("{n}")


def test_contradiction_cap_only_for_short_sources_with_no_shared_word() -> None:
    capped = apply_contradiction_cap(QualityResult(0.97, []), "Discard", "Collection")
    assert capped.score == CONTRADICTION_CAP and "contradiction" in capped.signals[-1]
    kept = apply_contradiction_cap(QualityResult(0.97, []), "Discard", "Discard")
    assert kept.score == 0.97
    long = apply_contradiction_cap(QualityResult(0.97, []), "Make a small image big.", "Shrink it")
    assert long.score == 0.97
    no_bt = apply_contradiction_cap(QualityResult(0.97, []), "Discard", None)
    assert no_bt.score == 0.97


def test_risky_keys_get_a_judge_without_judge_model(make_config, tmp_path) -> None:
    cfg = make_config(tmp_path)
    assert cfg.judge_model_for("pl") is None
    assert risky_judge_model(cfg, "pl", "Discard") is not None
    assert risky_judge_model(cfg, "pl", "Make a small image big.") is None
    cfg.judge_risky = False
    assert risky_judge_model(cfg, "pl", "Discard") is None


def test_judge_suggestion_is_kept_as_a_signal() -> None:
    judgment = {"semantic_accuracy": 20, "fluency": 90, "terminology": 90, "ui_appropriateness": 50,
                "suggested_translation": "Odrzuć"}
    _score, _dims, signals = lqs_from_judgment(judgment, source="Discard", translated="Zrzutka")
    assert f"{SUGGESTION_PREFIX}Odrzuć" in signals
    assert suggestion_of(signals) == "Odrzuć"
    _s, _d, same = lqs_from_judgment({**judgment, "suggested_translation": "Zrzutka"},
                                     source="Discard", translated="Zrzutka")
    assert suggestion_of(same) is None


def test_score_candidate_judges_a_risky_key(make_config, tmp_path) -> None:
    cfg = make_config(tmp_path)
    judgment = {"semantic_accuracy": 10, "fluency": 90, "terminology": 80, "ui_appropriateness": 30,
                "missing_information": False, "added_information": False,
                "placeholder_error": False, "html_error": False, "wrong_language": False,
                "explanation": "means a whip-round, not discard", "suggested_translation": "Odrzuć"}
    seen = []

    def handler(request):
        seen.append(request.prompt)
        if "back to English" in request.prompt or "into English" in request.prompt:
            return "Collection"
        return json.dumps(judgment)

    quality = score_candidate(NullProvider(handler=handler), source="Discard", translated="Zrzutka",
                              locale="pl", language="Polish", glossary={}, cfg=cfg)
    assert quality.scorer == "lqs"
    assert quality.score < 0.8
    assert suggestion_of(quality.signals) == "Odrzuć"
