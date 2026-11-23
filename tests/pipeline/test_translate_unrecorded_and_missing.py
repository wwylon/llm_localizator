"""Existing translations without state records are not overwritten; --only-missing; --keys-file."""

from __future__ import annotations

import argparse
import json

from llm_localizator.catalog import StateStore
from llm_localizator.cli.cmd_translate import keys_from_args, read_keys_file
from llm_localizator.pipeline.translate import collect_work, missing_keys, run_translation
from llm_localizator.providers import NullProvider

from ..conftest import setup_project, tagged


def _project(project_root, make_config, make_catalog):
    setup_project(
        project_root,
        {"a": "Alpha", "b": "Beta", "c": "Gamma", "d": "Delta"},
        # a: a real translation without a record, b: empty, c: copy of source, d: absent
        existing={"a": "Alfa", "b": "", "c": "Gamma"},
    )
    cfg = make_config(project_root)
    return cfg, make_catalog(cfg)


def _keys(work) -> list[str]:
    return sorted(w.key for w in work)


def test_existing_unrecorded_translation_is_not_work(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    state = StateStore(cfg.state_dir)
    unrecorded: list = []
    work = collect_work(
        cfg, catalog, state, locales=["pl"], namespaces=["app"], unrecorded=unrecorded,
    )
    assert _keys(work) == ["b", "c", "d"]  # "a" keeps its translation
    assert _keys(unrecorded) == ["a"]


def test_force_and_opt_out_still_retranslate_unrecorded(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    state = StateStore(cfg.state_dir)
    forced = collect_work(cfg, catalog, state, locales=["pl"], namespaces=["app"], force=True)
    assert "a" in _keys(forced)
    opted = collect_work(
        cfg, catalog, state, locales=["pl"], namespaces=["app"], skip_unrecorded=False,
    )
    assert "a" in _keys(opted)


def test_naming_the_key_retranslates_it(project_root, make_config, make_catalog, silent) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    result = run_translation(
        cfg, catalog, NullProvider(handler=tagged), locales=["pl"], named_keys=["app.a"], report=silent,
    )
    assert result.written == 1


def test_broad_run_keeps_existing_translation(project_root, make_config, make_catalog, silent) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    lines: list[str] = []
    run_translation(
        cfg, catalog, NullProvider(handler=tagged), locales=["pl"], report=lines.append,
    )
    target = json.loads((project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8"))
    assert target["a"] == "Alfa"
    assert target["d"].startswith("[xx]")
    assert any("left as is" in line for line in lines)


def test_missing_keys_are_absent_or_empty_only(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    gaps = missing_keys(cfg, catalog, locales=["pl"], namespaces=["app"])
    assert {k.split(".")[-1] for k in gaps["pl"]} == {"b", "d"}


def test_only_missing_run_touches_only_gaps(project_root, make_config, make_catalog, silent) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    result = run_translation(
        cfg, catalog, NullProvider(handler=tagged), locales=["pl"], only_missing=True, report=silent,
    )
    assert result.written == 2
    target = json.loads((project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8"))
    assert target["a"] == "Alfa"
    assert target["c"] == "Gamma"  # same as source, but present: not a gap


def test_only_missing_with_nothing_missing_is_a_no_op(
    project_root, make_config, make_catalog, silent,
) -> None:
    setup_project(project_root, {"a": "Alpha"}, existing={"a": "Alfa"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    lines: list[str] = []
    result = run_translation(
        cfg, catalog, NullProvider(handler=tagged), locales=["pl"], only_missing=True, report=lines.append,
    )
    assert result.written == 0
    assert any("nothing to do" in line for line in lines)


def test_keys_file_reads_lines_commas_and_comments(tmp_path) -> None:
    path = tmp_path / "keys.txt"
    path.write_text("# header\napp.a, app.b\n\napp.c\n", encoding="utf-8")
    assert read_keys_file(str(path)) == ["app.a", "app.b", "app.c"]


def test_keys_file_merges_with_keys_and_dedupes(tmp_path) -> None:
    path = tmp_path / "keys.txt"
    path.write_text("app.b\napp.c\n", encoding="utf-8")
    args = argparse.Namespace(keys=["app.a,app.b"], keys_file=str(path))
    assert keys_from_args(args) == ["app.a", "app.b", "app.c"]


def test_keys_from_args_without_any_keys_is_none() -> None:
    assert keys_from_args(argparse.Namespace(keys=None, keys_file=None)) is None
