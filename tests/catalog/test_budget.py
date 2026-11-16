import threading
from pathlib import Path

import pytest

from llm_localizator.catalog.budget import BudgetStore, estimate_anthropic_usd


def test_budget_records_monthly_total(tmp_path: Path) -> None:
    store = BudgetStore(tmp_path)
    assert store.month_total() == 0.0
    store.record(0.5, locale="ar", model="claude-haiku-4-5")
    assert store.month_total() == 0.5
    assert store.remaining(2.0) == 1.5


def test_estimate_anthropic_usd() -> None:
    assert estimate_anthropic_usd("claude-haiku-4-5", 1000, 500) > 0


def test_exhausted_monthly_budget_refuses_cloud(tmp_path, make_config) -> None:
    from llm_localizator.projects.config import ProviderConfig
    from llm_localizator.providers import NullProvider, provider_for_locale

    cfg = make_config(
        tmp_path,
        budget_monthly_usd=1.0,
        allow_cloud=True,
        locale_providers={"pl": "anthropic"},
        provider=ProviderConfig(kind="null"),
    )
    BudgetStore(cfg.budget_root()).record(1.0, locale="pl", model="claude")
    lines: list[str] = []
    provider = provider_for_locale(cfg, "pl", report=lines.append)
    assert isinstance(provider, NullProvider)
    assert any("exhausted" in line for line in lines)


def test_reserve_blocks_concurrent_overspend(tmp_path: Path) -> None:
    store = BudgetStore(tmp_path)
    cap = 1.0
    first = store.reserve(0.8, cap_usd=cap)
    assert first is not None
    assert store.remaining(cap) == pytest.approx(0.2)
    assert store.reserve(0.5, cap_usd=cap) is None
    store.release(first)
    assert store.remaining(cap) == pytest.approx(1.0)
    second = store.reserve(0.5, cap_usd=cap)
    assert second is not None
    store.record(0.4, locale="pl", model="m")
    store.release(second)
    assert store.month_total() == pytest.approx(0.4)
    assert store.remaining(cap) == pytest.approx(0.6)


def test_record_past_cap_still_meters_but_remaining_is_zero(tmp_path: Path) -> None:
    store = BudgetStore(tmp_path)
    store.record(0.9, locale="pl", model="m")
    store.record(0.5, locale="pl", model="m")
    assert store.month_total() == pytest.approx(1.4)
    assert store.remaining(1.0) == 0.0
    assert store.reserve(0.1, cap_usd=1.0) is None


def test_concurrent_reserve_under_two_threads(tmp_path: Path) -> None:
    store_a = BudgetStore(tmp_path)
    store_b = BudgetStore(tmp_path)
    results: list[str | None] = [None, None]

    def take(idx: int, store: BudgetStore) -> None:
        results[idx] = store.reserve(0.7, cap_usd=1.0)

    t1 = threading.Thread(target=take, args=(0, store_a))
    t2 = threading.Thread(target=take, args=(1, store_b))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    won = [h for h in results if h is not None]
    assert len(won) == 1
    BudgetStore(tmp_path).release(won[0])
