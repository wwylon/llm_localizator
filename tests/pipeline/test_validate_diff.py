"""--diff-only clean-key cache, translator-context staleness, source-change history."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.state import StateStore, make_entry
from llm_localizator.pipeline.recording import record_candidate
from llm_localizator.pipeline.validate import run_validation

from ..conftest import write_json
from ..pipeline.test_translate import setup_project


def _project(project_root, make_config, make_catalog):
    setup_project(project_root, {"a": "Hello there", "b": "Goodbye now"}, existing={})
    cfg = make_config(project_root)
    write_json(project_root / "messages" / "pl" / "app.json", {
        "a": "Witaj tam", "b": "Do widzenia",
    })
    return cfg, make_catalog(cfg)


def test_diff_only_skips_clean_keys_on_second_run(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    first = run_validation(cfg, catalog, locales=["pl"], diff_only=True)
    assert first.skipped_unchanged == 0
    second = run_validation(cfg, catalog, locales=["pl"], diff_only=True)
    assert second.skipped_unchanged == 2
    assert second.findings == first.findings


def test_diff_only_rechecks_a_changed_translation(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    run_validation(cfg, catalog, locales=["pl"], diff_only=True)
    write_json(project_root / "messages" / "pl" / "app.json", {
        "a": "Witaj tam", "b": "",
    })
    report = run_validation(cfg, catalog, locales=["pl"], diff_only=True)
    assert report.skipped_unchanged == 1
    assert any(f.key == "b" and f.severity == "error" for f in report.findings)


def test_diff_only_never_hides_a_key_with_findings(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    write_json(project_root / "messages" / "pl" / "app.json", {"a": "Witaj tam", "b": ""})
    first = run_validation(cfg, catalog, locales=["pl"], diff_only=True)
    second = run_validation(cfg, catalog, locales=["pl"], diff_only=True)
    assert [f for f in first.findings if f.key == "b"]
    assert [f for f in second.findings if f.key == "b"]


def test_v34_runs_without_semantic_flag_but_v33_does_not(
    project_root, make_config, make_catalog,
) -> None:
    setup_project(project_root, {"a": "Error:", "b": "Save the file"}, existing={})
    cfg = make_config(project_root)
    write_json(project_root / "messages" / "fr" / "app.json", {
        "a": "Erreur:", "b": "Enregistrez the file and the rest",
    })
    catalog = make_catalog(cfg)
    default = run_validation(cfg, catalog, locales=["fr"])
    assert any(f.check == "V34" and f.key == "a" for f in default.findings)
    assert not any(f.check == "V33" for f in default.findings)
    semantic = run_validation(cfg, catalog, locales=["fr"], check_semantic=True)
    assert any(f.check == "V33" and f.key == "b" for f in semantic.findings)
    assert sum(1 for f in semantic.findings if f.check == "V34") == 1


def test_default_run_writes_no_cache(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    run_validation(cfg, catalog, locales=["pl"])
    assert not (Path(cfg.state_dir) / ".validate-cache").exists()


def test_context_change_reports_v07(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "a", make_entry("Hello there", "m", note="button label"))
    state.save("pl")
    ctx = project_root / "context"
    ctx.mkdir()
    (ctx / "app.json").write_text('{"a": {"note": "error message"}}', encoding="utf-8")
    cfg = make_config(project_root, context_dir=ctx)
    report = run_validation(cfg, make_catalog(cfg), locales=["pl"])
    assert any(f.check == "V07" and f.key == "a" for f in report.findings)


def test_source_change_recorded_in_history(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state")
    scores = ScoreStore(tmp_path / "scores")
    history = HistoryStore(tmp_path / "history")
    common = dict(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="save",
        model="m", quality_score=0.9, quality_signals=[], trigger="translate",
    )
    record_candidate(source="Save", previous=None, text="Zapisz", **common)
    state.record("pl", "app", "save", make_entry("Save", "m"))
    record_candidate(source="Save changes", previous="Zapisz", text="Zapisz zmiany", **common)
    first, second = history.events_for("pl", "app", "save")
    assert first.prev_src is None
    assert (second.prev_src, second.next_src) == ("Save", "Save changes")


def test_unchanged_source_records_no_source_diff(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state")
    scores = ScoreStore(tmp_path / "scores")
    history = HistoryStore(tmp_path / "history")
    common = dict(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="save", source="Save",
        model="m", quality_score=0.9, quality_signals=[], trigger="translate",
    )
    record_candidate(previous=None, text="Zapisz", **common)
    record_candidate(previous="Zapisz", text="Zapisz", **common)
    assert all(e.prev_src is None for e in history.events_for("pl", "app", "save"))
