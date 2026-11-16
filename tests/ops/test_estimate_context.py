"""The cost estimate counts per-key notes as input (C-050)."""

from __future__ import annotations

import json

from llm_localizator.ops.estimate_cost import op_estimate_cost, sources_for_estimate
from llm_localizator.ops.types import EstimateCostRequest
from llm_localizator.projects.config import ProviderConfig

from tests.conftest import setup_project


def test_notes_raise_the_estimate(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"hello": "Hello"})
    cfg = make_config(
        tmp_path, allow_cloud=True, budget_monthly_usd=25.0, budget_mode="on_request",
        provider=ProviderConfig(kind="anthropic"),
    )
    req = EstimateCostRequest(locales=["pl"])
    plain = op_estimate_cost(cfg, req).data["max_usd"]
    assert sources_for_estimate(cfg, req)["pl"] == ["Hello"]

    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "app.json").write_text(json.dumps({"hello": "A button label. " * 40}), encoding="utf-8")
    cfg = make_config(
        tmp_path, allow_cloud=True, budget_monthly_usd=25.0, budget_mode="on_request",
        provider=ProviderConfig(kind="anthropic"), context_dir=ctx,
    )
    assert "button label" in sources_for_estimate(cfg, req)["pl"][0]
    assert op_estimate_cost(cfg, req).data["max_usd"] > plain


def test_glossary_matches_raise_the_estimate(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"hello": "Hello cart"})
    kw = dict(
        allow_cloud=True, budget_monthly_usd=25.0, budget_mode="on_request",
        provider=ProviderConfig(kind="anthropic"),
    )
    req = EstimateCostRequest(locales=["pl"])
    plain = sources_for_estimate(make_config(tmp_path, **kw), req)["pl"][0]
    gloss = tmp_path / "glossary.json"
    gloss.write_text(json.dumps({"terms": {"cart": {"pl": "koszyk"}}}), encoding="utf-8")
    cfg = make_config(tmp_path, glossary_path=gloss, **kw)
    with_gloss = sources_for_estimate(cfg, req)["pl"][0]
    assert plain == "Hello cart" and "koszyk" in with_gloss


def test_review_estimate_prices_translated_strings(tmp_path, make_config) -> None:
    """M6: review/rescore quote one judge call per translated string; local provider means no cost."""
    setup_project(tmp_path, {"hello": "Hello", "bye": "Goodbye"}, existing={"hello": "Cześć"})
    local = make_config(tmp_path)
    res = op_estimate_cost(local, EstimateCostRequest(locales=["pl"], purpose="review"))
    data = res.data
    assert res.ok, res.summary
    assert data["local"] is True and data["keys"] == 1 and data["purpose"] == "review"
    cloud = make_config(
        tmp_path, allow_cloud=True, budget_monthly_usd=25.0, budget_mode="on_request",
        provider=ProviderConfig(kind="anthropic"),
    )
    res = op_estimate_cost(cloud, EstimateCostRequest(locales=["pl"], purpose="rescore"))
    assert res.ok, res.summary
    priced = res.data
    assert priced["local"] is False and priced["keys"] == 1 and priced["max_usd"] > 0
