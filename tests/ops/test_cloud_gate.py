"""Cloud translate gate. No network."""

from __future__ import annotations

from llm_localizator.ops.agent_mcp import dispatch_mcp_tool
from llm_localizator.ops.estimate_cost import op_estimate_cost
from llm_localizator.ops.types import EstimateCostRequest
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.projects.config import ProviderConfig
from llm_localizator.providers import NullProvider

from tests.conftest import setup_project


def _cloud(tmp_path, make_config, **overrides):
    setup_project(tmp_path, {"hello": "Hello"})
    defaults = dict(
        allow_cloud=True,
        budget_monthly_usd=25.0,
        budget_mode="on_request",
        provider=ProviderConfig(kind="anthropic"),
    )
    defaults.update(overrides)
    return make_config(tmp_path, **defaults)


def test_on_request_without_keys_does_not_call_provider(tmp_path, make_config, make_catalog) -> None:
    cfg = _cloud(tmp_path, make_config)
    calls: list = []
    provider = NullProvider(handler=lambda request: calls.append(request) or "Cześć")
    result = run_translation(
        cfg, make_catalog(cfg), provider, locales=["pl"], ignore_min_keys=True,
    )
    assert result.aborted
    assert calls == []


def test_over_budget_refuses_dynamic_and_on_request(tmp_path, make_config, make_catalog) -> None:
    for mode, keys in (("dynamic", None), ("on_request", ["app.hello"])):
        root = tmp_path / mode
        root.mkdir()
        cfg = _cloud(
            root, make_config,
            budget_monthly_usd=1e-9,
            budget_mode=mode,
        )
        calls: list = []
        provider = NullProvider(handler=lambda request: calls.append(request) or "Cześć")
        result = run_translation(
            cfg, make_catalog(cfg), provider,
            locales=["pl"], ignore_min_keys=True, named_keys=keys,
        )
        assert result.aborted
        assert calls == []


def test_fitting_on_request_reaches_the_provider(tmp_path, make_config, make_catalog) -> None:
    cfg = _cloud(tmp_path, make_config, budget_monthly_usd=50)
    calls: list = []
    provider = NullProvider(handler=lambda request: calls.append(request) or "Cześć")
    result = run_translation(
        cfg, make_catalog(cfg), provider,
        locales=["pl"], ignore_min_keys=True, named_keys=["app.hello"],
    )
    assert not result.aborted
    assert result.written == 1
    assert calls


def test_estimate_cost_is_local_when_cloud_is_off(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"hello": "Hello"})
    cfg = make_config(tmp_path)
    result = op_estimate_cost(cfg, EstimateCostRequest(locales=["pl"]))
    assert result.ok
    assert result.data["local"] is True
    assert result.data["max_usd"] == 0.0


def test_estimate_cost_returns_op_result_on_unexpected_error(
    tmp_path, make_config, monkeypatch,
) -> None:
    setup_project(tmp_path, {"hello": "Hello"})
    cfg = make_config(tmp_path)

    def boom(*_a, **_k):
        raise KeyError("missing config field")

    monkeypatch.setattr(
        "llm_localizator.ops.estimate_cost.sources_for_estimate", boom,
    )
    result = op_estimate_cost(cfg, EstimateCostRequest(locales=["pl"]))
    assert result.ok is False
    assert result.exit_code == 1
    assert "missing config field" in result.summary


def test_mcp_request_refuses_dynamic_mode(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path, budget_mode="dynamic")
    payload = dispatch_mcp_tool(cfg, "request_localization", {"keys": "app.hello"})
    assert payload["ok"] is False
    assert "on_request" in payload["summary"]


def test_mcp_estimate_returns_the_op_result(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"hello": "Hello"})
    cfg = make_config(tmp_path)
    payload = dispatch_mcp_tool(cfg, "estimate_localization_cost", {"locales": "pl"})
    assert payload["ok"] is True
    assert payload["command"] == "estimate-cost"
    assert payload["data"]["max_usd"] == 0.0


def test_mcp_rejects_api_key_argument(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    payload = dispatch_mcp_tool(cfg, "estimate_localization_cost", {"api_key": "secret"})
    assert payload["ok"] is False
