"""C-023 / ADR-69: ``[privacy] local_only`` hard-blocks anything that leaves the machine."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.providers import project_provider, provider_for_locale
from llm_localizator.providers.base import ProviderError


def _toml(root: Path, *, provider: str = 'kind = "null"', privacy: str = "local_only = true",
          extra: str = "") -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(
        '[project]\nname = "demo"\nsource_locale = "en"\n\n'
        '[catalog]\nformat = "json-nested"\npath = "messages/{locale}/{namespace}.json"\n\n'
        '[locales]\ntargets = ["pl"]\n\n'
        f"[provider]\n{provider}\n\n[privacy]\n{privacy}\n{extra}",
        encoding="utf-8",
    )
    return path


def test_local_only_loads_with_local_provider(tmp_path) -> None:
    assert load_config(_toml(tmp_path)).local_only is True


def test_default_is_off(tmp_path) -> None:
    assert load_config(_toml(tmp_path, privacy="")).local_only is False


def test_conflicts_with_allow_cloud(tmp_path) -> None:
    with pytest.raises(ConfigError, match="contradicts"):
        load_config(_toml(tmp_path, privacy="local_only = true\nallow_cloud = true"))


def test_cloud_provider_kind_is_refused(tmp_path) -> None:
    with pytest.raises(ConfigError, match="cloud provider"):
        load_config(_toml(tmp_path, provider='kind = "openai"'))


def test_named_cloud_provider_is_refused(tmp_path) -> None:
    extra = '\n[providers.fast]\nkind = "deepseek"\n'
    with pytest.raises(ConfigError, match="providers.fast"):
        load_config(_toml(tmp_path, extra=extra))


def test_remote_ollama_url_is_refused(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not on this machine"):
        load_config(_toml(tmp_path, provider='kind = "ollama"\nurl = "http://gpu.example.com:11434"'))


def test_loopback_ollama_url_is_allowed(tmp_path) -> None:
    load_config(_toml(tmp_path, provider='kind = "ollama"\nurl = "http://127.0.0.1:11434"'))


def test_remote_webhook_is_refused(tmp_path) -> None:
    with pytest.raises(ConfigError, match="webhook"):
        load_config(_toml(tmp_path, extra='\n[notify]\nwebhook = "https://hooks.example.com/x"\n'))


def test_provider_builders_raise_when_config_mutated(tmp_path) -> None:
    cfg = load_config(_toml(tmp_path))
    cfg.provider.kind = "openai"
    cfg.providers["default"].kind = "openai"
    with pytest.raises(ProviderError, match="local_only"):
        project_provider(cfg)
    with pytest.raises(ProviderError, match="local_only"):
        provider_for_locale(cfg, "pl")
