import argparse

import pytest

from llm_localizator.cli import cmd_projects
from llm_localizator.projects import ConfigError
from llm_localizator.projects.registry import (
    list_projects, prune_projects, register_project, rename_project, unregister_project,
)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))


def _proj(tmp_path, name, with_config=True):
    d = tmp_path / name
    d.mkdir()
    if with_config:
        (d / ".llm-localize.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    register_project(name, d)
    return d


def test_remove_only_unregisters(tmp_path):
    d = _proj(tmp_path, "a")
    unregister_project("a")
    assert list_projects() == []
    assert (d / ".llm-localize.toml").is_file()
    with pytest.raises(ConfigError):
        unregister_project("a")


def test_rename_refuses_existing_name(tmp_path):
    _proj(tmp_path, "a")
    _proj(tmp_path, "b")
    with pytest.raises(ConfigError):
        rename_project("a", "b")
    rename_project("a", "c")
    assert [p["name"] for p in list_projects()] == ["b", "c"]


def test_prune_drops_only_missing(tmp_path):
    _proj(tmp_path, "ok")
    _proj(tmp_path, "gone", with_config=False)
    assert prune_projects() == ["gone"]
    assert [p["name"] for p in list_projects()] == ["ok"]


def test_cli_list_and_bad_usage(tmp_path, capsys):
    _proj(tmp_path, "a")
    ns = lambda **k: argparse.Namespace(fmt="text", names=[], **k)  # noqa: E731
    assert cmd_projects.run(ns(action="list")) == 0
    assert "a" in capsys.readouterr().out
    assert cmd_projects.run(ns(action="rename")) == 1


def test_register_rejects_name_reuse_and_duplicate_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    register_project("a", a)
    register_project("a", a)  # same name, same root: idempotent
    with pytest.raises(ConfigError):
        register_project("a", b)
    with pytest.raises(ConfigError):
        register_project("a2", a)
    register_project("a", b, force=True)
