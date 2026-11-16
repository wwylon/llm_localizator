"""C-036: organisation-level TM and glossary (ADR-99)."""

from __future__ import annotations

import pytest

from llm_localizator.ops.org import op_org
from llm_localizator.projects.config import ConfigError, load_config


def _cfg(tmp_path, monkeypatch, org: str = "", extra: str = "", home=None, name: str = "demo"):
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(home or tmp_path / "home"))
    toml = "\n".join([
        "[project]", f'name = "{name}"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "m/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "", extra, org,
    ])
    (tmp_path / ".llm-localize.toml").write_text(toml, encoding="utf-8")
    return load_config(tmp_path / ".llm-localize.toml")


def test_default_is_off(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    assert not cfg.org_use and cfg.tm_shared_all() == [] and cfg.glossary_shared == []
    assert cfg.tm_write is None
    assert op_org(cfg).data["use"] is False


def test_use_appends_org_paths_after_project_ones(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, "[org]\nuse = true\n",
               '[prompt]\ntm_shared = "mine"\nglossary_shared = ["g.yaml"]\n')
    org_tm = tmp_path / "home" / "org" / "tm"
    assert cfg.tm_shared_all() == [tmp_path / "mine", org_tm]
    assert cfg.glossary_shared[-1] == tmp_path / "home" / "org" / "glossary.yaml"
    assert cfg.tm_write is None  # reading never writes


def test_contribute_sets_write_target_unless_project_names_one(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, "[org]\nuse = true\ncontribute = true\n")
    assert cfg.tm_write == tmp_path / "home" / "org" / "tm"
    cfg = _cfg(tmp_path, monkeypatch, "[org]\nuse = true\ncontribute = true\n",
               '[prompt]\ntm_write = "own"\n')
    assert cfg.tm_write == tmp_path / "own"


def test_registry_block_overrides_locations(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    shared = tmp_path / "team-tm"
    (home / "projects.yaml").write_text(f"org:\n  tm: {shared.as_posix()}\n", encoding="utf-8")
    cfg = _cfg(tmp_path, monkeypatch, "[org]\nuse = true\n")
    assert cfg.tm_shared_all() == [shared]


def test_contribute_needs_use(tmp_path, monkeypatch):
    with pytest.raises(ConfigError, match="contribute needs use"):
        _cfg(tmp_path, monkeypatch, "[org]\ncontribute = true\n")


def test_approved_text_reaches_org_tm_and_is_found_by_another_project(tmp_path, monkeypatch):
    a_root = tmp_path / "a"
    a_root.mkdir()
    # Distinct names: since ADR-112 a project's own TM lives in <home>/data/<name>/, so same-named projects share it.
    a = _cfg(a_root, monkeypatch, "[org]\nuse = true\ncontribute = true\n", home=tmp_path / "home", name="a")
    a.open_tm().approve(locale="de", source="Hello", text="Hallo")
    b_root = tmp_path / "b"
    b_root.mkdir()
    b = _cfg(b_root, monkeypatch, "[org]\nuse = true\n", home=tmp_path / "home", name="b")
    hit = b.open_tm().exact("de", "Hello")
    assert hit is not None and hit.text == "Hallo"
    off = _cfg(tmp_path, monkeypatch, home=tmp_path / "home", name="off")
    assert off.open_tm().exact("de", "Hello") is None
