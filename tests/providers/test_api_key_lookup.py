"""API key lookup: configured variable, then LLM_LOCALIZATOR_<VENDOR VAR>, then the vendor variable."""

from __future__ import annotations

import pytest

from llm_localizator.projects.config import NamedProvider, ProviderConfig
from llm_localizator.providers import build_provider
from llm_localizator.providers.base import CompletionRequest, ProviderError
from llm_localizator.providers.keys import candidate_vars, key_source, resolve_api_key
from llm_localizator.providers.openai_compat import chat_completions_url

_ALL = (
    "ANTHROPIC_API_KEY", "LLM_LOCALIZATOR_ANTHROPIC_API_KEY",
    "OPENAI_API_KEY", "LLM_LOCALIZATOR_OPENAI_API_KEY",
    "DEEPSEEK_API_KEY", "LLM_LOCALIZATOR_DEEPSEEK_API_KEY",
    "DEEPL_AUTH_KEY", "LLM_LOCALIZATOR_DEEPL_AUTH_KEY",
    "OPENAI_COMPAT_API_KEY", "LLM_LOCALIZATOR_OPENAI_COMPAT_API_KEY", "MY_GEMINI_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)


def test_candidate_order_and_dedupe() -> None:
    assert candidate_vars("ANTHROPIC_API_KEY") == [
        "LLM_LOCALIZATOR_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY",
    ]
    assert candidate_vars("ANTHROPIC_API_KEY", "MY_KEY")[0] == "MY_KEY"
    assert candidate_vars("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY") == [
        "ANTHROPIC_API_KEY", "LLM_LOCALIZATOR_ANTHROPIC_API_KEY",
    ]


def test_vendor_variable_still_works(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vendor")
    assert resolve_api_key("ANTHROPIC_API_KEY") == "vendor"
    assert key_source("ANTHROPIC_API_KEY") == "ANTHROPIC_API_KEY"


def test_prefixed_variable_wins_over_vendor(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vendor")
    monkeypatch.setenv("LLM_LOCALIZATOR_ANTHROPIC_API_KEY", "prefixed")
    assert resolve_api_key("ANTHROPIC_API_KEY") == "prefixed"
    assert key_source("ANTHROPIC_API_KEY") == "LLM_LOCALIZATOR_ANTHROPIC_API_KEY"


def test_configured_variable_wins_over_both(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vendor")
    monkeypatch.setenv("LLM_LOCALIZATOR_ANTHROPIC_API_KEY", "prefixed")
    monkeypatch.setenv("MY_GEMINI_KEY", "mine")
    assert resolve_api_key("ANTHROPIC_API_KEY", "MY_GEMINI_KEY") == "mine"


def test_blank_values_are_skipped(monkeypatch) -> None:
    monkeypatch.setenv("LLM_LOCALIZATOR_OPENAI_API_KEY", "   ")
    monkeypatch.setenv("OPENAI_API_KEY", "vendor")
    assert resolve_api_key("OPENAI_API_KEY") == "vendor"
    assert key_source("DEEPL_AUTH_KEY") is None


def test_providers_use_the_prefixed_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_LOCALIZATOR_ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("LLM_LOCALIZATOR_OPENAI_API_KEY", "o")
    monkeypatch.setenv("LLM_LOCALIZATOR_DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("LLM_LOCALIZATOR_DEEPL_AUTH_KEY", "l")
    cfg = ProviderConfig()
    assert build_provider(cfg, kind="anthropic").api_key == "a"
    assert build_provider(cfg, kind="openai").api_key == "o"
    assert build_provider(cfg, kind="deepseek").api_key == "d"
    assert build_provider(cfg, kind="deepl").auth_key == "l"


def test_missing_key_message_names_every_variable_but_no_secret(monkeypatch) -> None:
    provider = build_provider(ProviderConfig(api_key_env="MY_KEY"), kind="anthropic")
    with pytest.raises(ProviderError) as err:
        provider.complete(CompletionRequest(prompt="hi", model="claude-haiku-5-5"))
    text = str(err.value)
    assert "MY_KEY" in text and "LLM_LOCALIZATOR_ANTHROPIC_API_KEY" in text and "ANTHROPIC_API_KEY" in text


def test_api_key_env_round_trips_through_named_provider() -> None:
    named = NamedProvider(id="g", kind="openai_compat", url="https://h/v1", api_key_env="MY_GEMINI_KEY")
    assert named.as_provider_config().api_key_env == "MY_GEMINI_KEY"


def test_chat_completions_url() -> None:
    assert chat_completions_url("https://h/v1") == "https://h/v1/chat/completions"
    assert chat_completions_url("https://h/v1/") == "https://h/v1/chat/completions"
    assert chat_completions_url("https://h/v1/chat/completions") == "https://h/v1/chat/completions"


def test_openai_compat_needs_an_endpoint() -> None:
    with pytest.raises(ValueError, match="url"):
        build_provider(ProviderConfig(), kind="openai_compat")
    with pytest.raises(ValueError, match="url"):
        build_provider(ProviderConfig(url="http://localhost:11434"), kind="openai_compat")


def test_openai_compat_builds_with_configured_key_variable(monkeypatch) -> None:
    monkeypatch.setenv("MY_GEMINI_KEY", "secret-value")
    provider = build_provider(
        ProviderConfig(url="https://example.test/v1", api_key_env="MY_GEMINI_KEY"), kind="openai_compat",
    )
    assert provider.kind == "openai_compat"
    assert provider.url == "https://example.test/v1/chat/completions"
    assert provider.api_key == "secret-value"
    assert "secret-value" not in repr(provider)


def test_openai_compat_default_key_variable_names(monkeypatch) -> None:
    monkeypatch.setenv("LLM_LOCALIZATOR_OPENAI_COMPAT_API_KEY", "k")
    provider = build_provider(ProviderConfig(url="https://example.test/v1"), kind="openai_compat")
    assert provider.api_key == "k"


def test_sync_turns_off_async_batches() -> None:
    import dataclasses
    from types import SimpleNamespace

    from llm_localizator.pipeline.translate_items import cloud_async_batch_enabled

    provider = SimpleNamespace(kind="anthropic")
    cfg = SimpleNamespace(budget_cloud_batch=True)
    assert cloud_async_batch_enabled(cfg, provider) is True
    assert cloud_async_batch_enabled(SimpleNamespace(budget_cloud_batch=False), provider) is False
    assert dataclasses.is_dataclass(__import__("llm_localizator.projects", fromlist=["ProjectConfig"]).ProjectConfig)
