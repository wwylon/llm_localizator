"""Sync gather and improve loop (hermetic, null provider)."""

from __future__ import annotations

import json
from unittest.mock import patch

from llm_localizator.catalog import ScoreStore, StateStore, make_entry
from llm_localizator.pipeline.improve import collect_improve_keys, run_improve
from llm_localizator.pipeline.sync import run_sync
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import CompletionRequest, NullProvider

from .test_translate import setup_project, tagged


def test_sync_reports_backlog_without_scan(project_root, make_config, make_catalog, silent) -> None:
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)

    result = run_sync(cfg, catalog, dry_run=True, submit_translate=False, report=silent)

    assert result.missing_or_stale == 1
    assert result.translate_submitted is False


def test_improve_rebases_inflated_score_with_backtranslate(
    project_root, make_config, make_catalog, silent
) -> None:
    """Stored 1.0 scores without BT must not block a better BT-scored candidate."""
    setup_project(
        project_root,
        {"greet": "Hello there friend from the app"},
        existing={"greet": "Zaszyfruj wszystko natychmiast"},
    )
    cfg = make_config(
        project_root,
        flags_path=project_root / "flags.jsonl",
        scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history",
        quality_threshold=0.5,
        improve_model="testmodel",
    )
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "greet", make_entry("Hello there friend from the app", "testmodel"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "greet", score=1.0, signals=[], text="Zaszyfruj wszystko natychmiast")
    scores.save("pl")
    (project_root / "flags.jsonl").write_text(
        json.dumps({"locale": "pl", "namespace": "app", "key": "greet"}) + "\n",
        encoding="utf-8",
    )

    good = "Cześć drogi przyjacielu z aplikacji"

    def handler(request: CompletionRequest) -> str:
        prompt = request.prompt
        if "back to English" in prompt:
            if "Zaszyfruj" in prompt:
                return "Encrypt everything immediately"
            if good in prompt or "Cześć" in prompt:
                return "Hello there friend from the app"
            return "something else"
        return good

    provider = NullProvider(handler=handler)
    from llm_localizator.pipeline import checkpoint as checkpoint_mod

    seen = {}
    real_flush = checkpoint_mod.flush_pending

    def wrapped(*args, **kwargs):
        seen["use_journal"] = kwargs.get("use_journal", True)
        return real_flush(*args, **kwargs)

    with patch.object(checkpoint_mod, "flush_pending", wrapped):
        result = run_improve(cfg, catalog, provider, back_translate=True, report=silent)
    assert seen.get("use_journal") is True
    assert result.improved == 1
    assert catalog.load("pl", "app")["greet"] == good


def test_improve_best_of_n_picks_highest_scoring_candidate(
    project_root, make_config, make_catalog, silent
) -> None:
    """With improve_multi_sample > 1, a later-sampled candidate that scores
    better than the first must win -- not just whichever came first."""
    setup_project(
        project_root,
        {"greet": "Save changes"},
        existing={"greet": "Zly tekst"},
    )
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history",
        quality_threshold=0.5,
        improve_model="testmodel",
        improve_multi_sample=3,
    )
    catalog = make_catalog(cfg)
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "greet", score=0.2, signals=[], text="Zly tekst")
    scores.save("pl")

    gen_calls = {"n": 0}

    def handler(request: CompletionRequest) -> str:
        prompt = request.prompt
        if "back to English" in prompt:
            return "Save changes" if "Zapisz zmiany" in prompt else "Delete everything"
        gen_calls["n"] += 1
        return "Usun wszystko" if gen_calls["n"] == 1 else "Zapisz zmiany"

    provider = NullProvider(handler=handler)
    result = run_improve(cfg, catalog, provider, back_translate=True, report=silent)

    assert result.improved == 1
    assert catalog.load("pl", "app")["greet"] == "Zapisz zmiany"
    assert gen_calls["n"] == 3  # all three samples were actually generated


def test_improve_keeps_previous_when_score_not_better(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(
        project_root,
        {"greet": "Hello there friend from the app"},
        existing={"greet": "Cześć drogi przyjacielu z aplikacji"},
    )
    cfg = make_config(
        project_root,
        flags_path=project_root / "flags.jsonl",
        scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history",
        quality_threshold=0.9,
        improve_model="testmodel",
    )
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "greet", make_entry("Hello there friend from the app", "testmodel"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record(
        "pl", "app", "greet",
        score=0.8, signals=["seed"], text="Cześć drogi przyjacielu z aplikacji",
    )
    scores.save("pl")
    (project_root / "flags.jsonl").write_text(
        json.dumps({"locale": "pl", "namespace": "app", "key": "greet"}) + "\n",
        encoding="utf-8",
    )

    # Echo English source — identical-to-source penalty keeps score below 0.8.
    def echo_en(request: CompletionRequest) -> str:
        return "Hello there friend from the app"

    provider = NullProvider(handler=echo_en)
    result = run_improve(
        cfg, catalog, provider, back_translate=False, report=silent,
    )
    assert result.considered == 1
    assert catalog.load("pl", "app")["greet"] == "Cześć drogi przyjacielu z aplikacji"
    assert result.kept_previous == 1
    hist = (project_root / ".llm-history" / "pl.jsonl").read_text(encoding="utf-8")
    assert "improve-reject" in hist


def test_collect_improve_keys_skips_recent_reject(
    project_root, make_config, make_catalog
) -> None:
    """KEEP/FAIL keys cool down so the next --limit batch rotates."""
    from llm_localizator.catalog.history import HistoryStore, make_history_event
    from llm_localizator.core.hash import src_hash

    setup_project(
        project_root,
        {"stuck": "Stuck source", "fresh": "Fresh source"},
        existing={"stuck": "Zly", "fresh": "Tez zly"},
    )
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history",
        quality_threshold=0.7,
        improve_skip_rejected=True,
        improve_reject_cooldown_hours=168,
    )
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    for key in ("stuck", "fresh"):
        state.record("pl", "app", key, make_entry(key, "testmodel"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "stuck", score=0.1, signals=["bad"], text="Zly")
    scores.record("pl", "app", "fresh", score=0.1, signals=["bad"], text="Tez zly")
    scores.save("pl")

    history = HistoryStore(cfg.history_dir)
    history.append("pl", make_history_event(
        namespace="app", key="stuck", prev="Zly", next_text="Zly",
        model="testmodel", status="machine",
        src_sha=src_hash("Stuck source"), trigger="improve-reject",
        quality_score=0.1,
    ))

    keys = collect_improve_keys(
        cfg, catalog, state, scores,
        locales=["pl"], namespaces=["app"], limit=10, history=history,
    )
    assert [k[2] for k in keys] == ["fresh"]

    forced = collect_improve_keys(
        cfg, catalog, state, scores,
        locales=["pl"], namespaces=["app"], limit=10,
        history=history, include_rejected=True,
    )
    assert {k[2] for k in forced} == {"stuck", "fresh"}


def test_collect_improve_keys_includes_low_scores(
    project_root, make_config, make_catalog
) -> None:
    setup_project(project_root, {"a": "Alpha", "b": "Beta"}, existing={"a": "A", "b": "B"})
    cfg = make_config(project_root, scores_dir=project_root / ".llm-scores", quality_threshold=0.7)
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    for key in ("a", "b"):
        state.record("pl", "app", key, make_entry(key, "testmodel"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "a", score=0.2, signals=["bad"], text="A")
    scores.record("pl", "app", "b", score=0.95, signals=[], text="B")
    scores.save("pl")

    keys = collect_improve_keys(
        cfg, catalog, state, scores, locales=["pl"], namespaces=["app"], limit=10,
    )
    assert len(keys) == 1
    assert keys[0][2] == "a"


def test_collect_improve_keys_prefers_flagged_over_low_score(
    project_root, make_config, make_catalog
) -> None:
    setup_project(
        project_root,
        {"low": "Low score", "flag": "Flagged board"},
        existing={"low": "Niski", "flag": "Flaga"},
    )
    flags = project_root / "flags.jsonl"
    flags.write_text(
        '{"locale":"pl","namespace":"app","key":"flag","reason":"V13: board"}\n',
        encoding="utf-8",
    )
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        flags_path=flags,
        quality_threshold=0.7,
    )
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    for key in ("low", "flag"):
        state.record("pl", "app", key, make_entry(key, "testmodel"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "low", score=0.1, signals=["bad"], text="Niski")
    scores.record("pl", "app", "flag", score=0.9, signals=[], text="Flaga")
    scores.save("pl")

    keys = collect_improve_keys(
        cfg, catalog, state, scores, locales=["pl"], namespaces=["app"], limit=1,
    )
    assert len(keys) == 1
    assert keys[0][2] == "flag"


def test_translate_records_score_and_history(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello there friend"})
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history",
        flags_path=project_root / "flags.jsonl",
    )
    catalog = make_catalog(cfg)
    provider = NullProvider(handler=tagged)
    run_translation(cfg, catalog, provider, report=silent)

    scores = ScoreStore(cfg.scores_dir).get("pl", "app", "greet")
    assert scores is not None
    assert "quality_score" in scores
    hist = (project_root / ".llm-history" / "pl.jsonl").read_text(encoding="utf-8")
    assert "greet" in hist


def test_improve_exit_code_fails_when_all_failed() -> None:
    from llm_localizator.pipeline.improve import ImproveResult

    ok = ImproveResult(considered=2, improved=1, failed=1)
    assert ok.exit_code == 0
    bad = ImproveResult(considered=3, failed=3)
    assert bad.exit_code == 1
    empty = ImproveResult(considered=0)
    assert empty.exit_code == 0
    # Nothing written and some failures: exit 1 so the job can retry.
    nothing_written = ImproveResult(considered=3, kept_previous=1, failed=2)
    assert nothing_written.exit_code == 1
    # A key was written: exit 0 so taskqueue does not redo it.
    wrote = ImproveResult(considered=3, improved=1, failed=2)
    assert wrote.exit_code == 0


def test_improve_error_does_not_start_cooldown() -> None:
    from llm_localizator.catalog.history import HistoryEvent
    from llm_localizator.pipeline.improve import _stuck_still_cooling

    event = HistoryEvent(
        ts="2026-09-18T00:00:00+00:00",
        namespace="app",
        key="greet",
        prev=None,
        next="x",
        model="m",
        status="machine",
        src_sha="abc",
        trigger="improve-error",
    )
    assert _stuck_still_cooling(event, source="Hello", cooldown_hours=168) is False


def test_per_locale_threshold_decides_which_keys_improve_selects(
    project_root, make_config, make_catalog
) -> None:
    setup_project(project_root, {"a": "Alpha source"}, existing={"a": "Alfa"})
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        quality_threshold=0.55,
        quality_thresholds={"pl": 0.45},
    )
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "a", make_entry("a", "testmodel"))
    state.save("pl")
    scores = ScoreStore(cfg.scores_dir)
    scores.record("pl", "app", "a", score=0.48, signals=[], text="Alfa")
    scores.save("pl")

    def picked(config) -> list[str]:
        return [k[2] for k in collect_improve_keys(
            config, catalog, state, scores, locales=["pl"], namespaces=["app"], limit=10,
        )]

    assert picked(cfg) == []  # 0.48 clears the pl override of 0.45
    cfg.quality_thresholds = {}
    assert picked(cfg) == ["a"]  # and misses the global 0.55


def test_improve_skips_key_verified_after_collection(
    project_root, make_config, make_catalog, silent
) -> None:
    """A key a human verified between collection and the lock must not be rewritten."""
    from llm_localizator.pipeline import improve as improve_mod

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Czesc"})
    cfg = make_config(
        project_root,
        scores_dir=project_root / ".llm-scores",
        history_dir=project_root / ".llm-history",
        quality_threshold=0.9,
        improve_model="testmodel",
    )
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    entry = make_entry("Hello", "testmodel")
    entry["verified_at"] = "2026-01-01T00:00:00Z"
    state.record("pl", "app", "greet", entry)
    state.save("pl")

    calls = []

    def handler(request: CompletionRequest) -> str:
        calls.append(request.prompt)
        return "Nowe"

    stale_work = [("pl", "app", "greet", "Hello", 0.1)]
    with patch.object(
        improve_mod, "collect_improve_keys", lambda *a, **k: (stale_work, 0)
    ):
        run_improve(cfg, catalog, NullProvider(handler=handler), report=silent)

    assert calls == []
    assert catalog.load("pl", "app")["greet"] == "Czesc"
