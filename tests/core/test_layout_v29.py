"""V29 pixel-budget layout check (ADR-159)."""

from __future__ import annotations

from llm_localizator.catalog.layout_budgets import lookup_budget, merge_budget
from llm_localizator.core.layout_qa import check_layout, estimate_text_width_px


def test_estimate_cjk_wider_than_latin() -> None:
    latin = estimate_text_width_px("Hello", font_size_px=14, locale="en")
    cjk = estimate_text_width_px("你好啊哈", font_size_px=14, locale="zh")
    assert cjk > latin


def test_v29_fires_when_text_exceeds_budget() -> None:
    issues = check_layout(
        "Hi", "This is a very long Polish translation that will not fit",
        "pl", max_width_px=40, font_size_px=14,
    )
    assert any(i.code == "V29" for i in issues)


def test_v29_ok_when_short() -> None:
    issues = check_layout("Hi", "Cześć", "pl", max_width_px=200, font_size_px=14)
    assert not any(i.code == "V29" for i in issues)


def test_merge_budget_keeps_max_width() -> None:
    budgets: dict = {}
    merge_budget(budgets, "nav.home", max_width_px=80, font_size_px=12)
    merge_budget(budgets, "nav.home", max_width_px=120, font_size_px=14)
    assert budgets["nav.home"]["maxWidthPx"] == 120
    assert budgets["nav.home"]["fontSizePx"] == 14
    assert lookup_budget(budgets, "", "nav.home")["maxWidthPx"] == 120
