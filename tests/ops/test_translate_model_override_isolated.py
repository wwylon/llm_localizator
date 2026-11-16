"""``translate --model`` must not change the shared config (web server: one config for every request). M0, ops #3."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.types import TranslateRequest
from llm_localizator.ops.translate import op_translate
from llm_localizator.projects.config import CONFIG_FILENAME, load_config

_TOML = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]

[locales.models]
default = "base-model"
"""


def test_model_override_leaves_shared_config_alone(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(_TOML, encoding="utf-8")
    (tmp_path / "messages" / "en").mkdir(parents=True)
    (tmp_path / "messages" / "en" / "common.json").write_text('{"hi": "Hello"}', encoding="utf-8")
    cfg = load_config(tmp_path / CONFIG_FILENAME)
    before = dict(cfg.models)
    op_translate(cfg, TranslateRequest(locales=["pl"], model="other-model", dry_run=True))
    assert cfg.models == before
