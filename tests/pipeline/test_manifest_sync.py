"""``sync --diff`` writes a work manifest; ``translate --manifest`` reads it; branch warning."""

from __future__ import annotations

import argparse
import json

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.pipeline import sync as sync_module
from llm_localizator.pipeline.manifest import manifest_path, only_keys_from
from llm_localizator.pipeline.sync import run_sync

from ..conftest import setup_project


def _project(project_root, make_config):
    setup_project(
        project_root,
        {"a": "Save changes", "b": "Cancel", "c": "Hello"},
        existing={"a": "Zapisz", "b": "Anuluj", "z": "Stare"},
    )
    cfg = make_config(project_root)
    state = StateStore(cfg.state_root())
    state.record("pl", "app", "a", make_entry("Save", "testmodel"))  # source has changed since
    state.record("pl", "app", "b", make_entry("Cancel", "testmodel"))
    state.save("pl")
    return cfg


def test_diff_lists_added_changed_and_removed(project_root, make_config, make_catalog) -> None:
    cfg = _project(project_root, make_config)
    result = run_sync(cfg, make_catalog(cfg), diff=True, report=lambda _m: None)

    data = json.loads(manifest_path(cfg).read_text(encoding="utf-8"))
    assert [r["key"] for r in data["added"]] == ["c"]
    assert data["added"][0]["locales"] == ["pl"]
    assert [(r["key"], r["old"], r["new"]) for r in data["changed"]] == [
        ("a", "Save", "Save changes")
    ]
    assert [r["key"] for r in data["removed"]] == ["z"]
    assert data["unchanged_count"] == 1
    assert (result.manifest_added, result.manifest_changed) == (1, 1)


def test_exit_nonzero_only_when_there_is_work(project_root, make_config, make_catalog) -> None:
    cfg = _project(project_root, make_config)
    quiet = lambda _m: None  # noqa: E731
    assert run_sync(cfg, make_catalog(cfg), diff=True, exit_nonzero=True, report=quiet).exit_code == 1
    assert run_sync(cfg, make_catalog(cfg), diff=True, report=quiet).exit_code == 0

    setup_project(project_root, {"b": "Cancel"}, existing={"b": "Anuluj"})
    assert run_sync(cfg, make_catalog(cfg), diff=True, exit_nonzero=True, report=quiet).exit_code == 0


def test_dry_run_does_not_write_the_manifest(project_root, make_config, make_catalog) -> None:
    cfg = _project(project_root, make_config)
    run_sync(cfg, make_catalog(cfg), diff=True, dry_run=True, report=lambda _m: None)
    assert not manifest_path(cfg).exists()


def test_the_manifest_selects_only_its_keys(project_root, make_config, make_catalog) -> None:
    cfg = _project(project_root, make_config)
    run_sync(cfg, make_catalog(cfg), diff=True, report=lambda _m: None)
    assert only_keys_from(manifest_path(cfg)) == {"pl": {"app.a", "app.c"}}


def test_translate_reads_the_manifest(project_root, make_config, make_catalog, monkeypatch) -> None:
    from llm_localizator.cli import cmd_translate

    cfg = _project(project_root, make_config)
    run_sync(cfg, make_catalog(cfg), diff=True, report=lambda _m: None)
    seen: dict = {}

    class Done:
        exit_code = 0
        rejected: list = []

    def fake_run(_cfg, _catalog, _provider, **kwargs):
        seen.update(kwargs)
        return Done()

    monkeypatch.setattr(cmd_translate, "resolve", lambda *_a: cfg)
    monkeypatch.setattr(cmd_translate, "project_provider", lambda _cfg: object())
    monkeypatch.setattr(cmd_translate, "run_translation", fake_run)
    args = argparse.Namespace(
        project=None, config=None, collection=None, model=None, flagged=False,
        locales=None, namespace=None, batch_size=10, force=False, dry_run=False,
        manifest=str(manifest_path(cfg)),
    )
    assert cmd_translate.run_execute(args) == 0
    assert seen["only_keys"] == {"pl": {"app.a", "app.c"}}

    args.manifest = str(project_root / "missing.json")
    assert cmd_translate.run_execute(args) == 1


def test_a_foreign_branch_warns_and_strict_fails(project_root, make_config, make_catalog, monkeypatch) -> None:
    cfg = _project(project_root, make_config)
    lines: list[str] = []
    monkeypatch.setattr(sync_module, "current_branch", lambda _root: "feature/x")

    warned = run_sync(cfg, make_catalog(cfg), report=lines.append)
    assert warned.exit_code == 0 and "feature/x" in warned.branch_warning
    assert any(line.startswith("warn:") for line in lines)
    assert run_sync(cfg, make_catalog(cfg), strict_branch=True, report=lines.append).exit_code == 1

    monkeypatch.setattr(sync_module, "current_branch", lambda _root: "main")
    assert run_sync(cfg, make_catalog(cfg), strict_branch=True, report=lines.append).exit_code == 0
    monkeypatch.setattr(sync_module, "current_branch", lambda _root: None)  # not a repo
    assert run_sync(cfg, make_catalog(cfg), strict_branch=True, report=lines.append).branch_warning == ""


def test_source_branch_is_configurable(project_root, make_config) -> None:
    assert make_config(project_root).source_branch == "main"
    assert make_config(project_root, source_branch="develop").source_branch == "develop"


def test_sync_diff_collects_the_work_list_once(project_root, make_config, make_catalog, monkeypatch) -> None:
    from llm_localizator.pipeline import manifest as manifest_module

    cfg = _project(project_root, make_config)
    calls: list[int] = []
    real = sync_module.collect_work

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(sync_module, "collect_work", counting)
    monkeypatch.setattr(manifest_module, "collect_work", counting)
    run_sync(cfg, make_catalog(cfg), diff=True, report=lambda _m: None)
    assert len(calls) == 1
    data = json.loads(manifest_path(cfg).read_text(encoding="utf-8"))
    assert [r["key"] for r in data["added"]] == ["c"]
