"""ADR-35 pre-flight for improve, review, rescore submit paths. No network."""

from __future__ import annotations

import pytest

from llm_localizator.ops import improve as improve_mod
from llm_localizator.ops import rescore as rescore_mod
from llm_localizator.ops import review as review_mod
from llm_localizator.ops.improve import op_improve
from llm_localizator.ops.rescore import op_rescore
from llm_localizator.ops.review import op_review
from llm_localizator.ops.types import ImproveRequest, RescoreRequest, ReviewRequest
from llm_localizator.projects.config import ProviderConfig

from tests.conftest import setup_project


def _cfg(tmp_path, make_config, **overrides):
    setup_project(tmp_path, {"hello": "Hello"}, existing={"hello": "Czesc"})
    base = dict(
        allow_cloud=True, budget_monthly_usd=25.0, budget_mode="on_request",
        provider=ProviderConfig(kind="anthropic"),
    )
    base.update(overrides)
    return make_config(tmp_path, **base)


def _requests():
    return [
        ("improve", op_improve, ImproveRequest(locales=["pl"])),
        ("review", op_review, ReviewRequest(locales=["pl"])),
        ("rescore", op_rescore, RescoreRequest(locales=["pl"])),
    ]


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    """Any op that passes the gate must not reach a real queue or model."""
    hit: list[str] = []
    for mod in (improve_mod, review_mod, rescore_mod):
        monkeypatch.setattr(mod, "tq_available", lambda: False)
    for mod, name in ((improve_mod, "run_improve"), (review_mod, "run_review")):
        monkeypatch.setattr(mod, name, lambda *a, **k: hit.append(name) or (_ for _ in ()).throw(RuntimeError("reached")))
    monkeypatch.setattr(rescore_mod, "execute_rescore",
                        lambda *a, **k: hit.append("rescore") or (_ for _ in ()).throw(RuntimeError("reached")))
    monkeypatch.setattr(improve_mod, "project_provider", lambda cfg: object())
    monkeypatch.setattr(review_mod, "project_provider", lambda cfg: object())
    return hit


@pytest.mark.parametrize("name,op,req", _requests())
def test_on_request_without_keys_is_refused(tmp_path, make_config, name, op, req) -> None:
    cfg = _cfg(tmp_path, make_config)
    result = op(cfg, req)
    assert result.ok is False
    assert "on_request" in result.summary


@pytest.mark.parametrize("name,op,req", _requests())
def test_dynamic_over_budget_is_refused(tmp_path, make_config, name, op, req) -> None:
    cfg = _cfg(tmp_path, make_config, budget_mode="dynamic", budget_monthly_usd=1e-9)
    result = op(cfg, req)
    assert result.ok is False
    assert "budget" in result.summary


@pytest.mark.parametrize("name,op,req", _requests())
def test_dynamic_within_budget_reaches_the_run(tmp_path, make_config, name, op, req) -> None:
    cfg = _cfg(tmp_path, make_config, budget_mode="dynamic", budget_monthly_usd=50.0)
    with pytest.raises(RuntimeError, match="reached"):
        op(cfg, req)


@pytest.mark.parametrize("name,op,req", _requests())
def test_local_provider_is_never_gated(tmp_path, make_config, name, op, req) -> None:
    cfg = _cfg(tmp_path, make_config, provider=ProviderConfig(kind="ollama"))
    with pytest.raises(RuntimeError, match="reached"):
        op(cfg, req)


def test_improve_named_keys_pass_on_request(tmp_path, make_config) -> None:
    cfg = _cfg(tmp_path, make_config)
    with pytest.raises(RuntimeError, match="reached"):
        op_improve(cfg, ImproveRequest(locales=["pl"], keys=["app.hello"]))

def test_refusal_names_keys_flag(tmp_path, make_config) -> None:
    cfg = _cfg(tmp_path, make_config)
    for _name, op, req in _requests():
        assert "--keys" in op(cfg, req).summary


def test_review_named_keys_pass_on_request(tmp_path, make_config) -> None:
    cfg = _cfg(tmp_path, make_config)
    with pytest.raises(RuntimeError, match="reached"):
        op_review(cfg, ReviewRequest(locales=["pl"], keys=["app.hello"]))


def test_rescore_named_keys_pass_on_request(tmp_path, make_config) -> None:
    cfg = _cfg(tmp_path, make_config)
    with pytest.raises(RuntimeError, match="reached"):
        op_rescore(cfg, RescoreRequest(locales=["pl"], keys=["app.hello"]))


def test_keys_forwarded_to_workers_and_queue(tmp_path, make_config, monkeypatch) -> None:
    cfg = _cfg(tmp_path, make_config, provider=ProviderConfig(kind="ollama"))
    seen: dict = {}
    monkeypatch.setattr(review_mod, "run_review",
                        lambda *a, **k: seen.update(review=k["keys"]) or review_mod.ReviewResult())
    op_review(cfg, ReviewRequest(locales=["pl"], keys=["app.hello"]))
    assert seen["review"] == ["app.hello"]

    def fake_rescore(cfg, **k):
        seen["rescore"] = k["keys"]
        return review_mod.OpResult(ok=True, exit_code=0, command="rescore", summary="")

    monkeypatch.setattr(rescore_mod, "execute_rescore", fake_rescore)
    op_rescore(cfg, RescoreRequest(locales=["pl"], keys=["app.hello"]))
    assert seen["rescore"] == ["app.hello"]

    class Outcome:
        ok, exit_code, message, task_ids = True, 0, "queued", ()

    ov: dict = {}
    monkeypatch.setattr(review_mod, "tq_available", lambda: True)
    monkeypatch.setattr(review_mod, "submit", lambda c, j, o: ov.update(o) or Outcome())
    op_review(cfg, ReviewRequest(locales=["pl"], keys=["app.hello", "app.bye"]))
    assert ov["--keys"] == "app.hello,app.bye"


def test_collect_rescore_items_filters_named_keys(tmp_path, make_config) -> None:
    from llm_localizator.catalog import ScoreStore, StateStore, build_catalog
    from llm_localizator.ops.rescore import collect_rescore_items

    setup_project(tmp_path, {"hello": "Hello", "bye": "Bye"},
                  existing={"hello": "Czesc", "bye": "Pa"})
    cfg = make_config(tmp_path)
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    work = collect_rescore_items(
        cfg, catalog, StateStore(cfg.state_dir), ScoreStore(cfg.scores_root()),
        locales=["pl"], namespaces=["app"], keys=["app.hello"],
    )
    assert [(i.namespace, i.key) for i in work] == [("app", "hello")]
