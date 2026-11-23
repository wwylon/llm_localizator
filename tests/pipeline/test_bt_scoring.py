"""Back-translation scoring on translate accept."""

from __future__ import annotations

import json

from llm_localizator.catalog import ScoreStore
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import CompletionRequest, NullProvider

from .test_translate import setup_project, tagged


def test_translate_scores_with_backtranslation(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello there"})
    cfg = make_config(project_root, scores_dir=project_root / ".llm-scores")
    catalog = make_catalog(cfg)

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            return "Hello there"
        if "quality judge" in request.prompt:  # risky-key judge (ADR-125) also runs during translate
            return json.dumps({
                "semantic_accuracy": 95, "fluency": 95, "terminology": 95, "ui_appropriateness": 95,
                "missing_information": False, "added_information": False,
                "placeholder_error": False, "html_error": False, "explanation": "ok",
            })
        return tagged(request)

    run_translation(cfg, catalog, NullProvider(handler=handler), report=silent)
    score = ScoreStore(cfg.scores_dir).get("pl", "app", "greet")
    assert score is not None
    assert 0.0 < score["quality_score"] <= 1.0
    assert not any("parse_failed" in s for s in score.get("signals") or [])


def test_rescore_saves_scores_before_a_crash(tmp_path, make_config) -> None:
    from llm_localizator.catalog import ScoreStore
    from llm_localizator.pipeline.scoring import PendingScoreItem, rescore_items
    from llm_localizator.providers import NullProvider

    cfg = make_config(tmp_path, bt_batch_size=1, judge_risky=False)
    scores = ScoreStore(tmp_path / "scores")
    items = [
        PendingScoreItem(locale="pl", namespace="app", key=f"k{i}",
                         source=f"Hello {i}", translated=f"Witaj {i}")
        for i in range(6)
    ]
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] > 4:
            raise RuntimeError("crash")
        return "Hello"

    with __import__("pytest").raises(RuntimeError):
        rescore_items(NullProvider(handler=handler), cfg, scores, {}, items,
                      force_bt=True, save_every=2)
    on_disk = ScoreStore(tmp_path / "scores").load("pl")
    assert len(on_disk) >= 2


def test_rescore_saves_periodically_not_only_at_the_end(tmp_path, make_config) -> None:
    from llm_localizator.catalog import ScoreStore
    from llm_localizator.pipeline.scoring import PendingScoreItem, rescore_items
    from llm_localizator.providers import NullProvider

    cfg = make_config(tmp_path, bt_batch_size=1)
    scores = ScoreStore(tmp_path / "scores")
    saves: list[int] = []
    real = scores.save
    scores.save = lambda loc: (saves.append(len(scores.load(loc))), real(loc))[1]
    items = [
        PendingScoreItem(locale="pl", namespace="app", key=f"k{i}",
                         source=f"Hello {i}", translated=f"Witaj {i}")
        for i in range(6)
    ]
    rescore_items(NullProvider(handler=lambda r: "Hello"), cfg, scores, {}, items,
                  force_bt=True, save_every=2)
    assert len(saves) >= 3 and saves[0] < 6
