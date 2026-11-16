"""C-038: placeholder rename across source and translations."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog import StateStore, make_entry, needs_translation
from llm_localizator.core.placeholders import rename_placeholder
from llm_localizator.ops.dispatch import dispatch_op

from tests.conftest import setup_project


@pytest.mark.parametrize("text,expected", [
    ("Hi {name}!", "Hi {user}!"),
    ("{name, number} x", "{user, number} x"),
    ("{n, plural, one {{name} has #} other {{name} have #}}",
     "{n, plural, one {{user} has #} other {{user} have #}}"),
    ("{name, plural, one {name} other {names}}", "{user, plural, one {name} other {names}}"),
    ("{other} {{name}} %s", "{other} {{name}} %s"),
])
def test_rename(text, expected):
    assert rename_placeholder(text, "name", "user") == expected


def test_rename_rejects_bad_names():
    with pytest.raises(ValueError):
        rename_placeholder("x", "a b", "c")


def _project(project_root, make_config):
    setup_project(project_root, {"a": "Hello {name}", "b": "Plain"},
                  existing={"a": "Witaj {name}", "b": "Zwykły"})
    cfg = make_config(project_root)
    state = StateStore(cfg.state_root())
    state.record("pl", "app", "a", make_entry("Hello {name}", "m", "human"))
    state.save("pl")
    return cfg


def test_dry_run_changes_nothing(project_root, make_config):
    cfg = _project(project_root, make_config)
    out = dispatch_op(cfg, "rename-placeholder", {"old": "name", "new": "user"}, actor_role="Admin")
    assert out["ok"] and out["data"]["applied"] is False and out["data"]["edits"] == 2
    cat = json.loads((project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8"))
    assert cat["a"] == "Witaj {name}"


def test_apply_keeps_translation_fresh_and_provenance(project_root, make_config):
    cfg = _project(project_root, make_config)
    out = dispatch_op(cfg, "rename-placeholder",
                      {"old": "name", "new": "user", "confirm": True}, actor_role="Admin")
    assert out["ok"] and out["data"]["applied"] is True
    en = json.loads((project_root / "messages" / "en" / "app.json").read_text(encoding="utf-8"))
    pl = json.loads((project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8"))
    assert en["a"] == "Hello {user}" and pl["a"] == "Witaj {user}" and pl["b"] == "Zwykły"
    entry = StateStore(cfg.state_root()).entry("pl", "app", "a")
    assert entry["status"] == "human"  # provenance untouched (ADR-48)
    assert not needs_translation("Hello {user}", entry)


def test_collision_is_skipped(project_root, make_config):
    setup_project(project_root, {"a": "{name} {user}"}, existing={"a": "{name} {user}"})
    cfg = make_config(project_root)
    out = dispatch_op(cfg, "rename-placeholder",
                      {"old": "name", "new": "user", "confirm": True}, actor_role="Admin")
    assert out["data"]["edits"] == 0 and out["data"]["skipped"]


def test_translator_role_is_refused(project_root, make_config):
    cfg = _project(project_root, make_config)
    out = dispatch_op(cfg, "rename-placeholder", {"old": "name", "new": "user"}, actor_role="Translator")
    assert out["ok"] is False
