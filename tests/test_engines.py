"""Engines (ADR-156): format checks, layering under the project config, --engine overlay, apply."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.engines import EngineError, all_engines, get_engine, layer, parse_engine, shadowing_keys
from llm_localizator.ops.engines import op_engine, recommend_engine
from llm_localizator.projects.config import ConfigError, load_config

BASE = (
    '[project]\nname = "demo"\nsource_locale = "en"\n\n'
    '[catalog]\nformat = "json-flat"\npath = "{locale}.json"\n\n'
    '[locales]\ntargets = ["pl", "de"]\nfrozen = ["de"]\n\n'
)


def _cfg(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / ".llm-localize.toml"
    path.write_text(BASE + extra, encoding="utf-8")
    return path


def test_every_builtin_engine_parses_and_loads(tmp_path: Path) -> None:
    engines = all_engines()
    assert {"claude-haiku", "deepseek", "openai", "local-4gb", "local-8gb"} <= set(engines)
    for engine_id in engines:
        cfg = load_config(_cfg(tmp_path, f'[engine]\nid = "{engine_id}"\n'))
        assert cfg.engine_id == engine_id


def test_engine_sets_every_role(tmp_path: Path) -> None:
    cfg = load_config(_cfg(tmp_path, '[engine]\nid = "claude-haiku"\n'))
    assert cfg.provider.kind == "anthropic"
    assert cfg.model_for("pl") == "claude-haiku-5-5"
    assert cfg.improve_model == cfg.score_model == "claude-haiku-5-5"
    assert cfg.score_provider == "anthropic"
    assert cfg.quality_threshold == pytest.approx(0.63)
    assert cfg.translate_cloud_batch_size == 50


def test_project_keys_win_over_the_engine(tmp_path: Path) -> None:
    """A frozen locale kept on its local Winner survives an engine switch."""
    extra = ('[engine]\nid = "claude-haiku"\n\n[locales.models]\nde = "aya-expanse:8b"\n\n'
             '[providers.local]\nname = "Local"\nkind = "ollama"\n\n[locales.providers]\nde = "local"\n\n'
             '[quality]\nthreshold = 0.7\n')
    cfg = load_config(_cfg(tmp_path, extra))
    assert cfg.model_for("de") == "aya-expanse:8b" and cfg.provider_kind_for("de") == "ollama"
    assert cfg.model_for("pl") == "claude-haiku-5-5"
    assert cfg.quality_threshold == pytest.approx(0.7)


def test_unknown_engine_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown engine"):
        load_config(_cfg(tmp_path, '[engine]\nid = "nope"\n'))


@pytest.mark.parametrize("bad", [
    '[config.privacy]\nallow_cloud = true\n',
    '[config.budget]\nmonthly_usd = 500\n',
    '[config.provider]\nurl = "https://evil.example"\n',
    '[config.provider]\nkind = "mystery"\n',
    '[config.notify]\nwebhook = "x"\n',
])
def test_engines_cannot_touch_privacy_budget_urls(bad: str) -> None:
    with pytest.raises(EngineError):
        parse_engine(f'id = "x"\nstatus = "smoke"\n{bad}', source="fetched")


def test_layer_and_shadowing() -> None:
    engine = get_engine("local-8gb")
    raw = {"quality": {"score_model": "qwen2.5:7b"}, "provider": {"url": "http://localhost:11434"}}
    merged = layer(raw, engine)
    assert merged["quality"]["score_model"] == "qwen2.5:7b"
    assert merged["provider"] == {"kind": "ollama", "url": "http://localhost:11434"}
    assert shadowing_keys(raw, engine) == [("quality", "score_model", "qwen2.5:7b")]


def test_engine_override_env_wins_for_one_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _cfg(tmp_path, '[quality]\nscore_model = "aya-expanse:8b"\nimprove_model = "aya-expanse:8b"\n')
    monkeypatch.setenv("LLM_LOCALIZE_ENGINE", "claude-haiku")
    cfg = load_config(path)
    assert cfg.engine_id == "claude-haiku" and cfg.score_model == "claude-haiku-5-5"
    monkeypatch.delenv("LLM_LOCALIZE_ENGINE")
    assert load_config(path).score_model == "aya-expanse:8b"


def test_recommend_prefers_evidence_and_respects_a_busy_gpu() -> None:
    no_keys = {"ANTHROPIC_API_KEY": False, "OPENAI_API_KEY": False, "DEEPSEEK_API_KEY": False}
    assert recommend_engine(None, {**no_keys, "ANTHROPIC_API_KEY": True})[0] == "claude-haiku"
    assert recommend_engine(8.0, no_keys)[0] == "local-8gb"
    assert recommend_engine(4.0, no_keys)[0] == "local-4gb"
    assert recommend_engine(8.0, no_keys, gpu_busy=True)[0] is None


def test_apply_writes_engine_and_removes_shadowing_keys(tmp_path: Path) -> None:
    path = _cfg(tmp_path, '[provider]\nkind = "ollama"\nurl = "http://localhost:11434"\n\n'
                          '[locales.models]\ndefault = "aya-expanse:8b"\nde = "aya-expanse:8b"\n\n'
                          '[quality]\nscore_model = "aya-expanse:8b"\n')
    result = op_engine(load_config(path), "apply", "local-4gb", vram=8.0)
    assert result.ok, result.summary
    cfg = load_config(path)
    assert cfg.engine_id == "local-4gb"
    assert cfg.model_for("pl") == "translategemma:4b" and cfg.score_model == "translategemma:4b"
    assert cfg.model_for("de") == "aya-expanse:8b"  # per-locale pin kept
    assert 'url = "http://localhost:11434"' in path.read_text(encoding="utf-8")


def test_apply_refuses_unbenchmarked_without_accept(tmp_path: Path) -> None:
    path = _cfg(tmp_path, "")
    before = path.read_text(encoding="utf-8")
    result = op_engine(load_config(path), "apply", "local-16gb", vram=16.0)
    assert not result.ok and "ADR-12" in result.summary
    assert path.read_text(encoding="utf-8") == before
    assert op_engine(load_config(path), "apply", "local-16gb", vram=16.0, accept_unbenchmarked=True).ok


def test_apply_cloud_engine_never_turns_cloud_on(tmp_path: Path) -> None:
    path = _cfg(tmp_path, "")
    result = op_engine(load_config(path), "apply", "claude-haiku", vram=None)
    assert result.ok
    text = path.read_text(encoding="utf-8")
    assert "allow_cloud" not in text and "monthly_usd" not in text
    assert any("allow_cloud = true" in line for line in result.lines)


def test_web_engine_field_reloads_the_config_for_that_run(tmp_path: Path) -> None:
    from llm_localizator.ops.dispatch import dispatch_op

    path = _cfg(tmp_path, '[quality]\nscore_model = "aya-expanse:8b"\n')
    seen = {}

    import llm_localizator.ops.dispatch_cmds as cmds

    def fake(cfg, body, report):
        seen["engine"], seen["score"] = cfg.engine_override, cfg.score_model
        return {"ok": True, "exit_code": 0, "summary": "ok"}

    original = cmds._REGISTRY["rescore"]
    cmds._REGISTRY["rescore"] = fake
    try:
        dispatch_op(load_config(path), "rescore", {"engine": "claude-haiku", "dry_run": True}, actor_role="Admin")
    finally:
        cmds._REGISTRY["rescore"] = original
    assert seen == {"engine": "claude-haiku", "score": "claude-haiku-5-5"}


def test_queued_submit_carries_the_one_run_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import llm_localizator.projects.taskqueue as tq

    seen = {}
    monkeypatch.setattr(tq, "submit_one_off", lambda cfg, job, overrides, **kw: seen.update(overrides) or "queued")
    cfg = load_config(_cfg(tmp_path, ""), engine_override="claude-haiku")
    tq.submit(cfg, "improve")
    assert seen == {"--engine": "claude-haiku"}
