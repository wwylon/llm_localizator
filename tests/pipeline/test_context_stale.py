"""A changed translator context (note / screen / maxChars) queues the key again."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog import StateStore
from llm_localizator.catalog.state import make_entry
from llm_localizator.ops.status import collect, collect_missing
from llm_localizator.pipeline.translate import collect_work, run_translation
from llm_localizator.providers import NullProvider

from ..conftest import setup_project, tagged


def _write_note(root, note) -> None:
    ctx = root / "context"
    ctx.mkdir(exist_ok=True)
    (ctx / "app.json").write_text(json.dumps({"greet": {"note": note}}), encoding="utf-8")


def _translate_with_note(project_root, make_config, make_catalog, silent, note):
    setup_project(project_root, {"greet": "Hello"})
    if note is not None:
        _write_note(project_root, note)
    cfg = make_config(project_root, context_dir=project_root / "context")
    catalog = make_catalog(cfg)
    run_translation(cfg, catalog, NullProvider(handler=tagged), report=silent)
    return cfg, catalog


def _work(cfg, catalog):
    return collect_work(
        cfg, catalog, StateStore(cfg.state_dir), locales=["pl"], namespaces=["app"],
    )


def test_unchanged_context_is_not_queued(project_root, make_config, make_catalog, silent) -> None:
    cfg, catalog = _translate_with_note(project_root, make_config, make_catalog, silent, "button")
    assert _work(cfg, catalog) == []


def test_changed_note_is_queued(project_root, make_config, make_catalog, silent) -> None:
    cfg, catalog = _translate_with_note(project_root, make_config, make_catalog, silent, "button")
    _write_note(project_root, "error message")
    assert [w.key for w in _work(cfg, catalog)] == ["greet"]


def test_added_note_is_queued(project_root, make_config, make_catalog, silent) -> None:
    cfg, catalog = _translate_with_note(project_root, make_config, make_catalog, silent, None)
    _write_note(project_root, "button")
    assert [w.key for w in _work(cfg, catalog)] == ["greet"]


def test_removed_note_is_queued(project_root, make_config, make_catalog, silent) -> None:
    cfg, catalog = _translate_with_note(project_root, make_config, make_catalog, silent, "button")
    _write_note(project_root, "")
    assert [w.key for w in _work(cfg, catalog)] == ["greet"]


def test_context_change_is_retranslated_and_settles(
    project_root, make_config, make_catalog, silent,
) -> None:
    cfg, catalog = _translate_with_note(project_root, make_config, make_catalog, silent, "button")
    _write_note(project_root, "error message")
    result = run_translation(cfg, catalog, NullProvider(handler=tagged), report=silent)
    assert result.written == 1
    assert _work(cfg, catalog) == []


def test_status_counts_a_context_change_as_stale(
    project_root, make_config, make_catalog, silent,
) -> None:
    cfg, catalog = _translate_with_note(project_root, make_config, make_catalog, silent, "button")
    assert collect(cfg, catalog)[0].stale == 0
    _write_note(project_root, "error message")
    assert collect(cfg, catalog)[0].stale == 1
    assert collect_missing(cfg, catalog)["pl"] == [("app", "greet", "stale")]


def test_records_without_a_context_hash_never_look_stale(
    project_root, make_config, make_catalog, silent,
) -> None:
    cfg, catalog = _translate_with_note(project_root, make_config, make_catalog, silent, None)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "greet", make_entry("Hello", "m"))
    state.save("pl")
    _write_note(project_root, "button")
    assert _work(cfg, catalog) == []


@pytest.mark.parametrize(
    "first, second, stale",
    [("a", "a", False), ("a", "b", True), ("", "a", True), ("a", "", True)],
)
def test_context_fingerprint_table(first, second, stale) -> None:
    from llm_localizator.catalog.state import needs_translation

    entry = make_entry("Save", "m", note=first)
    assert needs_translation("Save", entry, note=second) is stale
