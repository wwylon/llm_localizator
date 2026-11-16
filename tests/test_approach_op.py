"""W6: the approach choice is a web op (Admin) so the dashboard can record it with a button."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.projects.config import load_config

BASE = (
    '[project]\nname = "demo"\nsource_locale = "en"\n\n'
    '[catalog]\nformat = "json-flat"\npath = "{locale}.json"\n\n'
    '[locales]\ntargets = ["pl"]\n'
)


def _cfg(tmp_path: Path):
    path = tmp_path / ".llm-localize.toml"
    path.write_text(BASE, encoding="utf-8")
    return path


def test_admin_records_the_approach(tmp_path: Path) -> None:
    path = _cfg(tmp_path)
    listed = dispatch_op(load_config(path), "approach", {}, actor_role="Admin")
    assert listed["ok"] and listed["data"]["current"] is None and listed["data"]["recommended"]
    res = dispatch_op(load_config(path), "approach", {"set_to": "agent"}, actor_role="Admin")
    assert res["ok"], res
    assert load_config(path).translate_approach == "agent"


def test_unknown_approach_is_refused(tmp_path: Path) -> None:
    path = _cfg(tmp_path)
    res = dispatch_op(load_config(path), "approach", {"set_to": "magic"}, actor_role="Admin")
    assert not res["ok"]
    assert "[translate]" not in path.read_text(encoding="utf-8")


def test_only_admin_may_record(tmp_path: Path) -> None:
    path = _cfg(tmp_path)
    res = dispatch_op(load_config(path), "approach", {"set_to": "agent"}, actor_role="Translator")
    assert not res["ok"] and res["exit_code"] == 77
    assert "[translate]" not in path.read_text(encoding="utf-8")
