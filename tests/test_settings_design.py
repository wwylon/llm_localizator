"""Named providers, ASAP locales, and settings API (ADR-47)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.ops.remove_locale import remove_locale
from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.web.settings import save_settings, settings_view


def _write_toml(root: Path, body: str) -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = """\
[project]
name = "demo"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["de", "pl", "fr"]

[provider]
kind = "ollama"
url = "http://127.0.0.1:11434"
"""


def test_legacy_provider_synthesizes_default(tmp_path: Path) -> None:
    _write_toml(tmp_path, MINIMAL)
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert "default" in cfg.providers
    assert cfg.providers["default"].kind == "ollama"
    assert cfg.provider_entry_for("de").id == "default"


def test_named_providers_and_locale_id(tmp_path: Path) -> None:
    _write_toml(
        tmp_path,
        MINIMAL
        + """
[providers.local]
name = "Local"
kind = "ollama"
url = "http://127.0.0.1:11434"

[providers.gpu]
name = "GPU"
kind = "ollama"
url = "http://192.168.1.42:11434"

[locales.providers]
fr = "gpu"
""",
    )
    cfg = load_config(tmp_path / ".llm-localize.toml")
    assert cfg.provider_entry_for("de").url.endswith("11434")
    assert "192.168.1.42" in cfg.provider_entry_for("fr").url
    assert cfg.provider_kind_for("fr") == "ollama"
    pc = cfg.provider_config_for("fr")
    assert "192.168.1.42" in pc.url


def test_asap_disjoint_from_frozen(tmp_path: Path) -> None:
    _write_toml(
        tmp_path,
        """\
[project]
name = "demo"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["de", "pl", "fr"]
asap = ["pl"]
frozen = ["pl"]

[provider]
kind = "ollama"
""",
    )
    with pytest.raises(ConfigError, match="mutually exclusive"):
        load_config(tmp_path / ".llm-localize.toml")


def test_order_locales_prefers_asap_after_pivots(tmp_path: Path) -> None:
    _write_toml(
        tmp_path,
        """\
[project]
name = "demo"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["de", "pl", "pt-BR", "pt-PT"]
asap = ["pt-BR", "pl"]

[locales.pivots]
"pt-BR" = "pt-PT"

[provider]
kind = "ollama"
""",
    )
    cfg = load_config(tmp_path / ".llm-localize.toml")
    ordered = cfg.order_locales(list(cfg.targets))
    assert ordered.index("pt-PT") < ordered.index("pt-BR")
    assert ordered.index("pl") < ordered.index("de")


def test_settings_view_and_save_asap(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, MINIMAL)
    cfg = load_config(path)
    view = settings_view(cfg, port=8770, coverage={"de": 80.0})
    assert view["ok"]
    assert view["providersDetailed"]
    assert view["web"]["bind"] == "127.0.0.1"
    assert view["coverage"]["de"] == 80.0

    result = save_settings(cfg, asap=["pl"], frozen=["fr"])
    assert result["ok"], result
    cfg2 = load_config(path)
    assert cfg2.asap == ["pl"]
    assert cfg2.frozen == ["fr"]


def test_save_quality_threshold(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, MINIMAL)
    cfg = load_config(path)
    result = save_settings(cfg, quality={"threshold": 0.7})
    assert result["ok"], result
    cfg2 = load_config(path)
    assert cfg2.quality_threshold == 0.7


def test_remove_locale(tmp_path: Path) -> None:
    path = _write_toml(
        tmp_path,
        """\
[project]
name = "demo"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["de", "pl"]
asap = ["pl"]
frozen = []

[locales.models]
pl = "llama3.2"

[provider]
kind = "ollama"
""",
    )
    cfg = load_config(path)
    result = remove_locale(cfg, "pl")
    assert result["ok"], result
    cfg2 = load_config(path)
    assert cfg2.targets == ["de"]
    assert "pl" not in cfg2.asap
    assert "pl" not in cfg2.models


def test_adr12_refuses_model_and_judge_without_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_localizator.web.settings._bakeoff_allows_model_write",
        lambda _cfg: False,
    )
    path = _write_toml(tmp_path, MINIMAL)
    cfg = load_config(path)
    before = path.read_bytes()

    judge = save_settings(cfg, quality={"judgeModel": "aya-expanse:8b"})
    assert judge["ok"] is False
    assert "ADR-12" in (judge.get("error") or "") or "bakeoff" in (judge.get("error") or "").lower()
    assert path.read_bytes() == before

    assign = save_settings(
        cfg,
        locale_assignments=[{
            "locale": "de",
            "providerId": "default",
            "model": "qwen2.5:7b",
            "role": "translator",
        }],
    )
    assert assign["ok"] is False
    assert "ADR-12" in (assign.get("error") or "") or "bakeoff" in (assign.get("error") or "").lower()
    assert path.read_bytes() == before


def test_adr12_allow_model_writes_and_bakeoff_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_toml(tmp_path, MINIMAL)
    cfg = load_config(path)

    allowed = save_settings(
        cfg,
        quality={"judgeModel": "aya-expanse:8b"},
        locale_assignments=[{
            "locale": "de",
            "providerId": "default",
            "model": "qwen2.5:7b",
            "role": "translator",
        }],
        allow_model_writes=True,
    )
    assert allowed["ok"], allowed
    cfg2 = load_config(path)
    assert cfg2.judge_model == "aya-expanse:8b"
    assert cfg2.models.get("de") == "qwen2.5:7b"

    monkeypatch.setattr(
        "llm_localizator.web.settings._bakeoff_allows_model_write",
        lambda _cfg: True,
    )
    unlocked = save_settings(
        cfg2,
        quality={"judgeModel": "llama3.2:latest"},
    )
    assert unlocked["ok"], unlocked
    cfg3 = load_config(path)
    assert cfg3.judge_model == "llama3.2:latest"


def test_named_providers_save_round_trip(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, MINIMAL)
    cfg = load_config(path)
    result = save_settings(
        cfg,
        providers=[
            {
                "id": "default",
                "name": "Local Ollama",
                "kind": "ollama",
                "url": "http://127.0.0.1:11434",
            },
            {
                "id": "gpu",
                "name": "Remote GPU",
                "kind": "ollama",
                "url": "http://192.168.1.42:11434",
            },
        ],
    )
    assert result["ok"], result
    text = path.read_text(encoding="utf-8")
    assert "[providers.gpu]" in text or 'providers.gpu' in text or '"gpu"' in text
    cfg2 = load_config(path)
    assert "gpu" in cfg2.providers
    assert "192.168.1.42" in cfg2.providers["gpu"].url
    assert cfg2.provider.kind == "ollama"
    assert "127.0.0.1" in cfg2.provider.url or "localhost" in cfg2.provider.url


def test_provider_for_locale_uses_named_url(tmp_path: Path) -> None:
    from llm_localizator.providers import provider_for_locale
    from llm_localizator.providers.ollama import OllamaProvider

    _write_toml(
        tmp_path,
        MINIMAL
        + """
[providers.default]
name = "Local"
kind = "ollama"
url = "http://127.0.0.1:11434"

[providers.gpu]
name = "GPU"
kind = "ollama"
url = "http://192.168.1.42:11434"

[locales.providers]
fr = "gpu"
""",
    )
    cfg = load_config(tmp_path / ".llm-localize.toml")
    fr = provider_for_locale(cfg, "fr")
    de = provider_for_locale(cfg, "de")
    assert isinstance(fr, OllamaProvider)
    assert isinstance(de, OllamaProvider)
    assert "192.168.1.42" in fr.base_url
    assert "192.168.1.42" not in de.base_url
    assert "11434" in de.base_url


def test_project_patch_round_trip_and_source_reject(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, MINIMAL)
    cfg = load_config(path)
    ok = save_settings(
        cfg,
        project={
            "name": "demo-renamed",
            "sourceLocale": "en",
            "catalogFormat": "json-flat",
            "catalogPath": "i18n/{locale}.json",
            "skipKeys": ["brandName", "companyUrl"],
        },
    )
    assert ok["ok"], ok
    cfg2 = load_config(path)
    assert cfg2.name == "demo-renamed"
    assert cfg2.catalog_format == "json-flat"
    assert cfg2.catalog_path == "i18n/{locale}.json"
    assert cfg2.skip_keys == {"brandName", "companyUrl"}

    before = path.read_bytes()
    bad = save_settings(cfg2, project={"sourceLocale": "de"})
    assert bad["ok"] is False
    assert path.read_bytes() == before


def test_reset_permissions_restores_defaults(tmp_path: Path) -> None:
    from llm_localizator.ops.permissions import DEFAULT_MATRIX, OPERATIONS

    path = _write_toml(
        tmp_path,
        MINIMAL
        + """
[permissions]
validate = [true, false, false, false]
translate = [true, false, false, true]
""",
    )
    cfg = load_config(path)
    assert cfg.permission_matrix["validate"][1] is False
    result = save_settings(cfg, reset_permissions=True)
    assert result["ok"], result
    cfg2 = load_config(path)
    for op in OPERATIONS:
        assert cfg2.permission_matrix.get(op) == list(DEFAULT_MATRIX[op]), op
    assert cfg2.permission_matrix["translate"][0] is True
    assert cfg2.permission_matrix["translate"][2] is False


def test_remove_last_locale_fails(tmp_path: Path) -> None:
    path = _write_toml(
        tmp_path,
        """\
[project]
name = "demo"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["de"]

[provider]
kind = "ollama"
""",
    )
    cfg = load_config(path)
    before = path.read_bytes()
    result = remove_locale(cfg, "de")
    assert result["ok"] is False
    assert "last" in (result.get("error") or "").lower()
    assert path.read_bytes() == before
    assert load_config(path).targets == ["de"]


def test_judge_only_row_round_trips_as_judge(tmp_path: Path) -> None:
    """W1: a judge row also wrote [locales.models] <loc>, so it reloaded as 'both'."""
    from llm_localizator.web.settings import _role_for_locale

    path = _write_toml(tmp_path, MINIMAL)
    cfg = load_config(path)
    out = save_settings(cfg, locale_assignments=[
        {"locale": "de", "providerId": "default", "model": "qwen2.5:7b", "role": "judge"},
        {"locale": "default", "providerId": "default", "model": "aya-expanse:8b", "role": "translator"},
    ], allow_model_writes=True)
    assert out["ok"], out
    cfg2 = load_config(path)
    assert _role_for_locale(cfg2, "de") == "judge"
    assert "de" not in cfg2.models
    assert "default" not in cfg2.roles
    assert cfg2.models.get("default") == "aya-expanse:8b"


def test_cloud_provider_status_says_why_it_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_localizator.projects.config import NamedProvider
    from llm_localizator.web.settings import _probe_provider

    entry = NamedProvider(id="h", name="Haiku", kind="anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _probe_provider(entry, allow_cloud=False)["reason"] == "cloud_off"
    off = _probe_provider(entry, allow_cloud=True)
    assert off["reason"] == "no_key" and off["envVar"] == "ANTHROPIC_API_KEY"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert _probe_provider(entry, allow_cloud=True)["status"] == "online"
