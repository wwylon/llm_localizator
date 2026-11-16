"""Rescore collection filters."""

from __future__ import annotations

from llm_localizator.catalog import ScoreStore, StateStore, make_entry
from llm_localizator.ops.rescore import collect_rescore_items, execute_rescore
from tests.pipeline.test_translate import setup_project


def test_collect_rescore_below_score(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root, scores_dir=project_root / ".llm-scores")
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "greet", make_entry("Hello", "m"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "greet", score=0.4, signals=[], text="Cześć")
    scores.record("pl", "app", "other", score=0.95, signals=[], text="Inne")
    scores.save("pl")
    catalog.save("pl", "app", {"greet": "Cześć", "other": "Inne"})

    work = collect_rescore_items(
        cfg, catalog, state, scores,
        locales=["pl"], namespaces=["app"],
        below_score=0.7,
    )
    keys = {item.key for item in work}
    assert keys == {"greet"}


def test_stale_only_requires_below_score(project_root, make_config) -> None:
    cfg = make_config(project_root)
    result = execute_rescore(cfg, locales=["pl"], stale_only=True, dry_run=True)
    assert not result.ok
    assert "below-score" in result.summary.lower()
