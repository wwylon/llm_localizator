"""C-014: dashboard budget card payload."""

from __future__ import annotations

from llm_localizator.catalog.budget import BudgetStore
from llm_localizator.web.dashboard import _budget_card

from tests.conftest import setup_project


def test_no_ceiling_no_spend(project_root, make_config):
    setup_project(project_root, {"a": "Hi"}, existing={"a": "Czesc"})
    card = _budget_card(make_config(project_root))
    assert card["spentUsd"] == 0 and card["remainingUsd"] is None
    assert card["projectedUsd"] is None and card["byMonth"] == []
    assert card["localOnly"] is False


def test_spend_is_reported(project_root, make_config):
    setup_project(project_root, {"a": "Hi"}, existing={"a": "Czesc"})
    cfg = make_config(project_root)
    BudgetStore(cfg.budget_root()).record(1.5, locale="pl", model="m", kind="anthropic")
    card = _budget_card(cfg)
    assert card["spentUsd"] == 1.5
    assert len(card["byMonth"]) == 1 and card["byMonth"][0]["usd"] == 1.5
