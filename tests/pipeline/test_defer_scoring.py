"""Deferred two-phase scoring (translate phase A + BT phase B)."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog import ScoreStore, StateStore, make_entry
from llm_localizator.pipeline.scoring import (
    should_defer_scoring_for_translate,
)
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import CompletionRequest, NullProvider

from ..conftest import write_json
from .test_translate import setup_project, tagged


def test_should_defer_when_score_model_differs_from_pin() -> None:
    from llm_localizator.projects.config import ProjectConfig
    from pathlib import Path

    cfg = ProjectConfig(
        root=Path("/p"),
        name="x",
        targets=["ar"],
        models={"default": "translategemma:4b"},
        score_model="aya-expanse:8b",
    )
    assert should_defer_scoring_for_translate(cfg, "translategemma:4b", n_samples=1)


def test_should_not_defer_when_explicit_false() -> None:
    from llm_localizator.projects.config import ProjectConfig
    from pathlib import Path

    cfg = ProjectConfig(
        root=Path("/p"),
        name="x",
        targets=["ar"],
        models={"default": "translategemma:4b"},
        score_model="aya-expanse:8b",
        defer_scoring=False,
    )
    assert not should_defer_scoring_for_translate(cfg, "translategemma:4b", n_samples=1)


def test_should_not_defer_with_multi_sample(project_root, make_config) -> None:
    cfg = make_config(
        project_root,
        models={"default": "translategemma:4b"},
        score_model="aya-expanse:8b",
        multi_sample=2,
    )
    assert not should_defer_scoring_for_translate(cfg, "translategemma:4b", n_samples=2)


def test_deferred_translate_skips_bt_until_phase_b(
    project_root, make_config, make_catalog, silent,
) -> None:
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        models={"default": "translategemma:4b"},
        score_model="scoremodel", judge_risky=False,
        bt_batch_size=2,
    )
    catalog = make_catalog(cfg)
    bt_calls: list[str] = []

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            bt_calls.append(request.model)
            if request.schema is not None:
                from llm_localizator.providers.null import _numbered_lines

                lines = _numbered_lines(request.prompt)
                return json.dumps(lines, ensure_ascii=False)
            line = request.prompt.strip().splitlines()[-1]
            return line[5:].strip() if line.startswith("[xx] ") else line.strip()
        assert request.model == "translategemma:4b", "translate must use pin model"
        return tagged(request)

    run_translation(
        cfg, catalog,
        NullProvider(handler=handler),
        report=silent,
    )

    assert len(bt_calls) == 1
    assert bt_calls[0] == "scoremodel"
    scores = ScoreStore(cfg.scores_dir)
    for key in ("greet", "bye"):
        row = scores.get("pl", "app", key)
        assert row is not None
        assert row.get("scorer") == "bt"


def test_deferred_scoring_restart_after_partial_run(
    project_root, make_config, make_catalog, silent,
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        models={"default": "translategemma:4b"},
        score_model="scoremodel", judge_risky=False,
    )
    catalog = make_catalog(cfg)
    scores = ScoreStore(cfg.scores_dir)
    state = StateStore(cfg.state_dir)

    # Simulate phase A complete: catalogue written, heuristic score only.
    write_json(project_root / "messages" / "pl" / "app.json", {"greet": "[xx] Hello"})
    state.record("pl", "app", "greet", make_entry("Hello", "translategemma:4b"))
    state.save("pl")
    scores.record("pl", "app", "greet", score=0.9, signals=[], text="[xx] Hello", scorer="heuristic")
    scores.save("pl")

    bt_calls: list[str] = []

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            bt_calls.append(request.model)
            return "Hello"
        pytest.fail("translate should not run when only scoring is pending")

    result = run_translation(
        cfg, catalog,
        NullProvider(handler=handler),
        report=silent,
    )

    assert result.total == 1
    assert result.written == 0
    assert len(bt_calls) == 1
    row = ScoreStore(cfg.scores_dir).get("pl", "app", "greet")
    assert row.get("scorer") == "bt"


def test_phase_b_receives_run_glossary_not_last_item_domain(
    project_root, make_config, make_catalog, silent, monkeypatch,
) -> None:
    """Phase B must not inherit the last item's domain glossary (Wave 0.2)."""
    gdir = project_root / "glossary"
    gdir.mkdir()
    (gdir / "global.json").write_text(
        json.dumps({"terms": {"save": {"pl": "zapisz"}}}), encoding="utf-8",
    )
    (gdir / "billing.json").write_text(
        json.dumps({"terms": {"invoice": {"pl": "faktura"}}}), encoding="utf-8",
    )
    (gdir / "game.json").write_text(
        json.dumps({"terms": {"pot": {"pl": "pula"}}}), encoding="utf-8",
    )
    setup_project(project_root, {"greet": "Hello", "invoice": "Invoice"})
    notes = project_root / "messages" / ".context"
    notes.mkdir(parents=True, exist_ok=True)
    write_json(notes / "app.json", {
        "greet": {"domain": "game"},
        "invoice": {"domain": "billing"},
    })
    cfg = make_config(
        project_root,
        glossary_path=gdir,
        glossary_domains={"app": ["game"]},
        scores_dir=project_root / ".llm-scores",
        models={"default": "translategemma:4b"},
        score_model="scoremodel", judge_risky=False,
        context_dir=notes,
    )
    captured: dict = {}

    def fake_phase(cfg, provider, scores, glossary, items, **kwargs):
        captured["glossary"] = glossary
        captured["n"] = len(items)
        return len(items)

    monkeypatch.setattr(
        "llm_localizator.pipeline.translate.run_deferred_scoring_phase",
        fake_phase,
    )
    run_translation(
        cfg, make_catalog(cfg), NullProvider(handler=tagged), report=silent,
    )
    assert captured.get("n", 0) >= 1
    terms = captured["glossary"].get("terms") or {}
    # load_glossary(dir) merges all domains — must not be last-item billing-only.
    assert "save" in terms
    assert "pot" in terms
    assert "invoice" in terms
