"""Why a score is low (C-005)."""

from __future__ import annotations

from llm_localizator.pipeline.score_causes import explain_score, top_causes


def test_explain_picks_worst_dimension() -> None:
    row = {"dimensions": {"fluency": 0.7, "terminology": 0.3, "ui": 0.95}, "signals": ["judge: odd term"]}
    why = explain_score(row)
    assert why["cause"] == "terminology"
    assert [n for n, _ in why["weak"]] == ["terminology", "fluency"]
    assert why["signal"] == "judge: odd term"


def test_explain_without_dimensions_is_not_guessed() -> None:
    assert explain_score({"signals": []})["cause"] == "no-dimensions"
    assert explain_score({"dimensions": {"ui": 1.0}})["cause"] == "none-below-threshold"


def test_explain_prefers_typed_issue_over_weak_dimension() -> None:
    row = {
        "dimensions": {"fluency": 0.7, "terminology": 0.3},
        "signals": ["judge issue: major/accuracy: wrong polarity"],
        "issues": [{
            "category": "accuracy",
            "severity": "major",
            "description": "wrong polarity",
        }],
    }
    why = explain_score(row)
    assert why["cause"] == "issue:major/accuracy"
    assert why["issues"][0]["severity"] == "major"
    assert why["signal"].startswith("judge issue:")


def test_top_causes_orders_by_count_then_name() -> None:
    rows = [{"cause": "b"}, {"cause": "a"}, {"cause": "b"}]
    assert top_causes(rows) == [("b", 2), ("a", 1)]


def test_op_groups_low_keys_by_weakest_dimension(project_root, make_config) -> None:
    from llm_localizator.catalog import ScoreStore
    from llm_localizator.ops.metrics import op_metrics
    from llm_localizator.ops.types import MetricsRequest
    from tests.conftest import setup_project

    setup_project(project_root, {"a": "Hi", "b": "Bye", "c": "Yes"}, existing={"a": "x", "b": "y", "c": "z"})
    cfg = make_config(project_root)
    store = ScoreStore(cfg.scores_root())
    ns = "app"
    store.record("pl", ns, "a", score=0.3, signals=[], text="x", dimensions={"terminology": 0.2, "ui": 1.0})
    store.record("pl", ns, "b", score=0.4, signals=[], text="y")
    store.record("pl", ns, "c", score=0.9, signals=[], text="z")
    store.save("pl")
    res = op_metrics(cfg, MetricsRequest(why_low=True, locale="pl"))
    assert res.ok
    row = res.data["locales"][0]
    assert row["low"] == 2
    assert dict(row["causes"]) == {"terminology": 1, "no-dimensions": 1}
