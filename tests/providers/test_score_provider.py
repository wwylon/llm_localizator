"""``[quality] score_provider`` and the model/provider fit check (Slice 1, cloud engine switch)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.pipeline.scoring import score_model_for, score_provider_kind
from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.providers import complete_for, score_provider_for
from llm_localizator.providers.base import CompletionRequest
from llm_localizator.providers.preflight import looks_like_cloud_model, model_fit_errors


def _toml(root: Path, *, provider: str = 'kind = "ollama"', quality: str = "", extra: str = "",
          privacy: str = "allow_cloud = true", budget: str = "monthly_usd = 5") -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(
        '[project]\nname = "demo"\nsource_locale = "en"\n\n'
        '[catalog]\nformat = "json-nested"\npath = "messages/{locale}/{namespace}.json"\n\n'
        '[locales]\ntargets = ["pl"]\n\n'
        f"[provider]\n{provider}\n\n"
        '[providers.anthropic_haiku]\nname = "Haiku"\nkind = "anthropic"\n\n'
        f"[privacy]\n{privacy}\n\n[budget]\n{budget}\n\n[quality]\n{quality}\n{extra}",
        encoding="utf-8",
    )
    return path


def test_unset_score_provider_keeps_the_translator(tmp_path) -> None:
    cfg = load_config(_toml(tmp_path, quality='score_model = "aya-expanse:8b"'))
    assert cfg.score_provider is None
    assert score_provider_for(cfg) is None
    assert score_model_for(cfg) == "aya-expanse:8b"


def test_named_cloud_scorer_defaults_to_its_cloud_model(tmp_path) -> None:
    cfg = load_config(_toml(tmp_path, quality='score_provider = "anthropic_haiku"\nimprove_model = "aya-expanse:8b"'))
    assert score_provider_kind(cfg) == "anthropic"
    # Never inherits the local improve tag.
    assert score_model_for(cfg) == "claude-haiku-5-5"
    assert type(score_provider_for(cfg)).__name__ == "AnthropicProvider"


def test_cloud_scorer_without_allow_cloud_falls_back_locally(tmp_path) -> None:
    cfg = load_config(_toml(tmp_path, quality='score_provider = "anthropic_haiku"', privacy="allow_cloud = false"))
    notes: list[str] = []
    provider = score_provider_for(cfg, report=notes.append)
    assert type(provider).__name__ == "OllamaProvider"
    assert any("allow_cloud" in n for n in notes)


def test_bare_kind_is_accepted(tmp_path) -> None:
    cfg = load_config(_toml(tmp_path, quality='score_provider = "null"'))
    assert type(score_provider_for(cfg)).__name__ == "NullProvider"


@pytest.mark.parametrize("model,cloud", [
    ("claude-haiku-5-5", True), ("gpt-5.6-luna", True), ("deepseek-flash", True),
    ("aya-expanse:8b", False), ("qwen2.5:7b", False), ("llama3.2", False),
])
def test_looks_like_cloud_model(model: str, cloud: bool) -> None:
    assert looks_like_cloud_model(model) is cloud


def test_local_tag_on_cloud_scorer_is_refused(tmp_path) -> None:
    with pytest.raises(ConfigError, match="score_model = 'aya-expanse:8b' cannot run on provider 'anthropic'"):
        load_config(_toml(tmp_path, quality='score_provider = "anthropic_haiku"\nscore_model = "aya-expanse:8b"'))


def test_cloud_id_on_ollama_locale_is_refused(tmp_path) -> None:
    with pytest.raises(ConfigError, match="cannot run on provider 'ollama'"):
        load_config(_toml(tmp_path, extra='\n[locales.models]\npl = "claude-haiku-5-5"\n'))


def test_local_tag_on_cloud_locale_is_refused(tmp_path) -> None:
    extra = '\n[locales.providers]\npl = "anthropic_haiku"\n\n[locales.models]\npl = "aya-expanse:8b"\n'
    with pytest.raises(ConfigError, match=r"\[locales.models\] pl"):
        load_config(_toml(tmp_path, extra=extra))


def test_all_cloud_config_fits(tmp_path) -> None:
    extra = '\n[locales.providers]\npl = "anthropic_haiku"\n\n[locales.models]\npl = "claude-haiku-5-5"\n'
    cfg = load_config(_toml(
        tmp_path, provider='kind = "anthropic"', extra=extra,
        quality='score_provider = "anthropic_haiku"\nimprove_model = "claude-haiku-5-5"',
    ))
    assert model_fit_errors(cfg) == []


class _Spy:
    calls = 0

    def complete(self, request: CompletionRequest) -> str:
        self.calls += 1
        return "{}"


def test_complete_for_without_project_is_a_bare_call() -> None:
    spy = _Spy()
    assert complete_for(None, spy, "pl", CompletionRequest(prompt="x", model="m")) == "{}"
    assert spy.calls == 1


def test_complete_for_with_project_meters(monkeypatch) -> None:
    seen: list[str] = []
    import llm_localizator.providers as providers

    monkeypatch.setattr(providers, "record_provider_spend", lambda project, provider, locale, *, model: seen.append(model))
    complete_for(object(), _Spy(), "pl", CompletionRequest(prompt="x", model="claude-haiku-5-5"))
    assert seen == ["claude-haiku-5-5"]


def test_cloud_translator_scores_locally_without_score_provider(tmp_path) -> None:
    from llm_localizator.pipeline.translate import _bt_provider

    extra = '\n[locales.providers]\npl = "anthropic_haiku"\n\n[locales.models]\npl = "claude-haiku-5-5"\n'
    cfg = load_config(_toml(tmp_path, extra=extra, quality='score_model = "aya-expanse:8b"'))
    notes: list[str] = []
    picked = _bt_provider(cfg, "pl", lambda loc: pytest.fail("cloud provider must not score a local tag"), notes.append)
    assert type(picked).__name__ == "OllamaProvider"
    assert any("BT scores locally" in n for n in notes)


def test_cloud_translator_with_cloud_scorer(tmp_path) -> None:
    from llm_localizator.pipeline.translate import _bt_provider

    extra = '\n[locales.providers]\npl = "anthropic_haiku"\n\n[locales.models]\npl = "claude-haiku-5-5"\n'
    cfg = load_config(_toml(tmp_path, extra=extra, quality='score_provider = "anthropic_haiku"'))
    picked = _bt_provider(cfg, "pl", lambda loc: pytest.fail("score_provider wins"), lambda _m: None)
    assert type(picked).__name__ == "AnthropicProvider"


def test_cloud_translator_defers_scoring_even_with_the_same_model(tmp_path) -> None:
    """Inline scoring is off for cloud locales; without deferral a Haiku-on-Haiku run would never score BT."""
    from llm_localizator.pipeline.scoring import should_defer_scoring_for_translate

    cfg = load_config(_toml(tmp_path, provider='kind = "anthropic"',
                            quality='score_model = "claude-haiku-5-5"\nimprove_model = "claude-haiku-5-5"'))
    assert should_defer_scoring_for_translate(cfg, "claude-haiku-5-5")


def test_score_provider_always_defers(tmp_path) -> None:
    from llm_localizator.pipeline.scoring import should_defer_scoring_for_translate

    cfg = load_config(_toml(tmp_path, quality='score_provider = "null"\nscore_model = "aya-expanse:8b"'))
    assert should_defer_scoring_for_translate(cfg, "aya-expanse:8b")


def test_local_same_model_still_scores_inline(tmp_path) -> None:
    from llm_localizator.pipeline.scoring import should_defer_scoring_for_translate

    cfg = load_config(_toml(tmp_path, quality='score_model = "aya-expanse:8b"'))
    assert not should_defer_scoring_for_translate(cfg, "aya-expanse:8b")
