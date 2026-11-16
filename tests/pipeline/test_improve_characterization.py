"""Pins observable behaviour of run_improve before it is split (Wave 4)."""

from __future__ import annotations

from llm_localizator.catalog import ScoreStore
from llm_localizator.catalog.history import HistoryStore
from llm_localizator.pipeline.improve import run_improve
from llm_localizator.providers import CompletionRequest, NullProvider

from ..conftest import setup_project

BAD = {"a": "Zly a", "b": "Zly b", "c": "Zly c"}
SRC = {"a": "Save one", "b": "Save two", "c": "Save three"}
GOOD = {"Save one": "Zapisz jeden", "Save two": "Zapisz dwa", "Save three": "Zapisz trzy"}


def _handler(request: CompletionRequest) -> str:
    prompt = request.prompt
    if "back to English" in prompt:
        for src, tgt in GOOD.items():
            if tgt in prompt:
                return src
        return "Delete everything"
    for src, tgt in GOOD.items():
        if src in prompt:
            return tgt
    return "Zapisz"


def _setup(root, make_config, make_catalog):
    setup_project(root, SRC, existing=BAD)
    cfg = make_config(
        root,
        scores_dir=root / ".llm-scores",
        history_dir=root / ".llm-history",
        quality_threshold=0.5,
        improve_model="testmodel",
    )
    scores = ScoreStore(cfg.scores_dir)
    for k, v in BAD.items():
        scores.record("pl", "app", k, score=0.2, signals=[], text=v)
    scores.save("pl")
    return cfg, make_catalog(cfg)


def test_dry_run_changes_nothing(project_root, make_config, make_catalog, silent) -> None:
    cfg, cat = _setup(project_root, make_config, make_catalog)
    result = run_improve(cfg, cat, NullProvider(handler=_handler), dry_run=True, report=silent)
    assert result.dry_run is True and result.improved == 0
    assert cat.load("pl", "app") == BAD


def test_improves_every_weak_key_and_records_history(project_root, make_config, make_catalog, silent) -> None:
    cfg, cat = _setup(project_root, make_config, make_catalog)
    result = run_improve(cfg, cat, NullProvider(handler=_handler), report=silent)
    assert result.improved == 3 and result.failed == 0
    assert cat.load("pl", "app") == {"a": "Zapisz jeden", "b": "Zapisz dwa", "c": "Zapisz trzy"}
    hist = HistoryStore(cfg.history_root())
    assert all(hist.latest("pl", "app", k) is not None for k in "abc")


def test_limit_caps_the_number_of_keys(project_root, make_config, make_catalog, silent) -> None:
    cfg, cat = _setup(project_root, make_config, make_catalog)
    result = run_improve(cfg, cat, NullProvider(handler=_handler), limit=1, report=silent)
    assert result.considered == 1 and result.improved == 1
    after = cat.load("pl", "app")
    assert sum(1 for k in "abc" if after[k] != BAD[k]) == 1


def test_keys_filter_touches_only_named_keys(project_root, make_config, make_catalog, silent) -> None:
    cfg, cat = _setup(project_root, make_config, make_catalog)
    run_improve(cfg, cat, NullProvider(handler=_handler), keys=["app.b"], report=silent)
    after = cat.load("pl", "app")
    assert after["b"] == "Zapisz dwa"
    assert after["a"] == BAD["a"] and after["c"] == BAD["c"]


def test_target_edited_mid_run_is_kept_and_counted(project_root, make_config, make_catalog, silent) -> None:
    cfg, cat = _setup(project_root, make_config, make_catalog)
    fired = []

    def handler(request: CompletionRequest) -> str:
        if not fired:  # a human edits the target while the model is "thinking"
            fired.append(1)
            cat.save("pl", "app", {**cat.load("pl", "app"), "a": "Reczna wersja"})
        return _handler(request)

    result = run_improve(cfg, cat, NullProvider(handler=handler), keys=["app.a"], report=silent)
    assert result.skipped_external_edit == 1 and result.improved == 0
    assert result.skipped_external_keys == [("pl", "app", "a")]   # M6: the web shows editor links for these
    assert cat.load("pl", "app")["a"] == "Reczna wersja"


def test_second_run_has_nothing_left_to_improve(project_root, make_config, make_catalog, silent) -> None:
    cfg, cat = _setup(project_root, make_config, make_catalog)
    run_improve(cfg, cat, NullProvider(handler=_handler), report=silent)
    again = run_improve(cfg, cat, NullProvider(handler=_handler), report=silent)
    assert again.improved == 0


def test_improve_prompt_uses_the_namespace_domain_glossary(
    project_root, make_config, make_catalog, silent,
) -> None:
    import json

    gdir = project_root / "glossary"
    gdir.mkdir()
    (gdir / "global.json").write_text(json.dumps({"terms": {}}), encoding="utf-8")
    (gdir / "billing.json").write_text(
        json.dumps({"terms": {"Save": {"pl": "Zachowaj"}}}), encoding="utf-8",
    )
    (gdir / "games.json").write_text(
        json.dumps({"terms": {"one": {"pl": "Pulajeden"}}}), encoding="utf-8",
    )
    setup_project(project_root, SRC, existing=BAD)
    cfg = make_config(
        project_root, scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history", quality_threshold=0.5,
        improve_model="testmodel", glossary_path=gdir,
        glossary_domains={"app": ["billing"]},
    )
    scores = ScoreStore(cfg.scores_dir)
    for k, v in BAD.items():
        scores.record("pl", "app", k, score=0.2, signals=[], text=v)
    scores.save("pl")
    prompts: list[str] = []

    def spy(request: CompletionRequest) -> str:
        prompts.append(request.prompt)
        return _handler(request)

    run_improve(cfg, make_catalog(cfg), NullProvider(handler=spy), limit=1, report=silent)
    assert any("Zachowaj" in p for p in prompts)
    assert not any("Pulajeden" in p for p in prompts)  # other domain stays out
