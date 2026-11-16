"""Cloud spend is recorded for a call that already happened."""

from llm_localizator.catalog.budget import BudgetStore
from llm_localizator.pipeline.translate import _bill_cloud
from llm_localizator.projects.config import ProviderConfig


class _Cloud:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.last_usage = {"input_tokens": 1000, "output_tokens": 500}

    def usage(self):
        return self.last_usage


def test_bill_cloud_records_when_budget_already_exhausted(tmp_path, make_config) -> None:
    cfg = make_config(
        tmp_path,
        budget_monthly_usd=1.0,
        allow_cloud=True,
        locale_providers={"pl": "anthropic"},
        provider=ProviderConfig(kind="null"),
    )
    store = BudgetStore(cfg.budget_root())
    store.record(1.0, locale="pl", model="claude-haiku-4-5")
    assert store.remaining(1.0) == 0.0
    before = store.month_total()
    _bill_cloud(cfg, _Cloud("anthropic"), "pl", "claude-haiku-4-5")
    assert store.month_total() > before


def test_bill_cloud_skips_local_and_disallowed(tmp_path, make_config) -> None:
    cfg = make_config(
        tmp_path,
        budget_monthly_usd=1.0,
        allow_cloud=False,
        provider=ProviderConfig(kind="null"),
    )
    store = BudgetStore(cfg.budget_root())
    _bill_cloud(cfg, _Cloud("anthropic"), "pl", "claude-haiku-4-5")
    _bill_cloud(cfg, _Cloud("ollama"), "pl", "qwen")
    assert store.month_total() == 0.0


def test_unpriced_model_counts_at_fallback_rate_not_zero(tmp_path, make_config, caplog) -> None:
    cfg = make_config(
        tmp_path,
        budget_monthly_usd=100.0,
        allow_cloud=True,
        provider=ProviderConfig(kind="null"),
    )
    store = BudgetStore(cfg.budget_root())
    with caplog.at_level("WARNING"):
        _bill_cloud(cfg, _Cloud("anthropic"), "pl", "claude-unlisted-9")
    assert store.month_total() > 0.0
    assert "no price" in caplog.text


def test_metered_complete_skips_local_provider(tmp_path, make_config) -> None:
    from llm_localizator.providers import record_provider_spend

    cfg = make_config(tmp_path, budget_monthly_usd=1.0, allow_cloud=True,
                      provider=ProviderConfig(kind="null"))
    record_provider_spend(cfg, _Cloud("ollama"), "pl", model="qwen")
    assert BudgetStore(cfg.budget_root()).month_total() == 0.0
