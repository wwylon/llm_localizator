"""The quality signals reach the pipeline stages that use them (ADR-51)."""

from __future__ import annotations

import json

from llm_localizator.catalog import ScoreStore, StateStore, make_entry
from llm_localizator.catalog.export_formats import _threshold
from llm_localizator.pipeline import improve as improve_module
from llm_localizator.pipeline.improve import run_improve
from llm_localizator.pipeline.scoring import improve_score_cut
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import CompletionRequest, NullProvider

from ..conftest import write_json
from .test_translate import setup_project

SOURCE = "Hello there friend from the app"
OLD = SOURCE  # an untranslated echo: the weakest possible baseline
TAG = "[previous attempt rejected:"


def _improve_project(project_root, make_config, **overrides):
    setup_project(project_root, {"greet": SOURCE}, existing={"greet": OLD})
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history",
        quality_threshold=0.9,
        improve_model="testmodel",
        **overrides,
    )
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "greet", make_entry(SOURCE, "testmodel"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "greet", score=0.1, signals=["seed"], text=OLD)
    scores.save("pl")
    return cfg


def test_improve_passes_both_sides_dimensions_to_the_decision(
    project_root, make_config, make_catalog, silent, monkeypatch,
) -> None:
    cfg = _improve_project(project_root, make_config)
    calls: list[tuple] = []
    real = improve_module.is_improvement

    def spy(new_score, new_dims, old_score, old_dims, *args, **kwargs):
        calls.append((new_dims, old_dims))
        return real(new_score, new_dims, old_score, old_dims, *args, **kwargs)

    monkeypatch.setattr(improve_module, "is_improvement", spy)
    provider = NullProvider(handler=lambda request: "Witaj drogi przyjacielu z aplikacji")
    run_improve(cfg, make_catalog(cfg), provider, back_translate=False, report=silent)

    assert len(calls) == 1
    new_dims, old_dims = calls[0]
    assert {"placeholder_ok", "glossary_ok", "script_ok"} <= set(new_dims)
    assert {"placeholder_ok", "glossary_ok", "script_ok"} <= set(old_dims)


def test_improve_accepts_when_the_composite_decision_says_so(
    project_root, make_config, make_catalog, silent, monkeypatch,
) -> None:
    cfg = _improve_project(project_root, make_config)
    catalog = make_catalog(cfg)
    monkeypatch.setattr(improve_module, "is_improvement", lambda *a, **k: True)
    provider = NullProvider(handler=lambda request: "Witaj drogi przyjacielu z aplikacji")
    result = run_improve(cfg, catalog, provider, back_translate=False, report=silent)
    assert result.kept_previous == 0
    assert catalog.load("pl", "app")["greet"] == "Witaj drogi przyjacielu z aplikacji"


def test_improve_records_consistency_for_multi_sample(
    project_root, make_config, make_catalog, silent,
) -> None:
    cfg = _improve_project(project_root, make_config, improve_multi_sample=2)
    samples = iter(["Witaj drogi przyjacielu z aplikacji", "Dobry wieczor"])
    provider = NullProvider(handler=lambda request: next(samples, "Witaj"))
    run_improve(cfg, make_catalog(cfg), provider, back_translate=False, report=silent)
    entry = ScoreStore(cfg.scores_dir).get("pl", "app", "greet")
    assert entry["dimensions"]["consistency"] < 0.8
    assert any(sig.startswith("low-consistency") for sig in entry["signals"])


def test_the_per_locale_cut_reaches_every_reader(project_root, make_config) -> None:
    cfg = make_config(project_root, quality_threshold=0.55, quality_thresholds={"pl": 0.7})
    assert improve_score_cut(cfg, scorer="bt", locale="pl") == 0.7
    assert improve_score_cut(cfg, scorer="bt", locale="de") == 0.55
    assert improve_score_cut(cfg, scorer="bt") == 0.55
    assert improve_score_cut(cfg, scorer="lqs", locale="pl") == cfg.band_retranslate
    assert _threshold(cfg, None, "pl") == 0.7
    assert _threshold(cfg, None, "de") == 0.55
    assert _threshold(cfg, 0.9, "pl") == 0.9  # an explicit value still wins


def test_translate_flags_against_the_locales_own_cut(
    project_root, make_config, make_catalog, silent,
) -> None:
    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            if "JSON array" in request.prompt:
                return json.dumps(["Something unrelated entirely"])
            return "Something unrelated entirely"
        return "Witaj drogi przyjacielu z aplikacji"

    def flagged(threshold: float) -> int:
        write_json(project_root / "messages" / "en" / "app.json", {"greet": SOURCE})
        (project_root / "messages" / "pl" / "app.json").unlink(missing_ok=True)
        cfg = make_config(
            project_root,
            flags_path=project_root / f"flags-{threshold}.jsonl",
            scores_dir=project_root / f".scores-{threshold}",
            state_dir=project_root / f".state-{threshold}",
            quality_thresholds={"pl": threshold},
        )
        result = run_translation(
            cfg, make_catalog(cfg), NullProvider(handler=handler), force=True, report=silent,
        )  # force: the translation memory would otherwise answer the second run
        return len(result.flagged_low_score)

    assert flagged(0.05) == 0
    assert flagged(0.99) == 1


def test_a_rejected_key_is_retried_alone_with_the_reason(
    project_root, make_config, make_catalog, silent,
) -> None:
    from llm_localizator.providers.null import _numbered_lines

    setup_project(project_root, {"a": "Save", "b": "Hello {name}", "c": "Cancel"})
    cfg = make_config(project_root)

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            return request.prompt.strip().splitlines()[-1]
        if request.schema is not None:  # the batch: key b loses its placeholder
            lines = _numbered_lines(request.prompt)
            return json.dumps(
                [("Czesc" if "{name}" in line else f"[pl] {line}") for line in lines],
                ensure_ascii=False,
            )
        last = request.prompt.strip().splitlines()[-1]
        if TAG in request.prompt:
            return "Czesc {name}"
        return "Czesc" if last.startswith("Hello") else "[pl] " + last

    provider = NullProvider(handler=handler)
    result = run_translation(cfg, make_catalog(cfg), provider, report=silent)
    assert result.rejected == []
    assert result.written == 3
    retries = [c for c in provider.calls if TAG in c.prompt]
    assert len(retries) == 1 and retries[0].source_texts == ["Hello {name}"]
    assert make_catalog(cfg).load("pl", "app")["b"] == "Czesc {name}"
