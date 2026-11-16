"""Web ops with no locales: LLM ops skip frozen locales, read-only ops keep them (M0, audit ops #2)."""

from __future__ import annotations

from llm_localizator.projects.config import ProjectConfig
from llm_localizator.web.server import default_op_targets


def _cfg(tmp_path) -> ProjectConfig:
    cfg = ProjectConfig(name="demo", root=tmp_path)
    cfg.targets = ["pl", "zh", "ar"]
    cfg.frozen = ["zh", "ar"]
    return cfg


def test_llm_ops_leave_frozen_locales_out(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    for cmd in ("translate", "improve", "review", "rescore"):
        assert default_op_targets(cmd, cfg) == ["pl"], cmd


def test_read_only_ops_keep_every_target(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    assert sorted(default_op_targets("validate", cfg)) == ["ar", "pl", "zh"]
