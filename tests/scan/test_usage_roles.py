"""Roles from the markup a key renders into (ADR-129)."""

from __future__ import annotations

from llm_localizator.pipeline.prompts import BatchItem, _item_annotations
from llm_localizator.scan.usage_calls import KeyUsage, collect_key_usage


def test_roles_from_tags_and_attributes() -> None:
    usage = KeyUsage()
    collect_key_usage(
        '<button class="b" data-i18n="a.new">New</button>\n'
        '<th data-i18n="a.col">Col</th>\n'
        '<label class="f" data-i18n="a.deal">Deal</label>\n'
        '<input data-i18n-placeholder="a.ph" placeholder="x">\n'
        '<span data-i18n="a.plain">Plain</span>\n', "f.html", usage)
    assert usage.roles["a.new"].startswith("button")
    assert usage.roles["a.col"].startswith("table column header")
    assert usage.roles["a.deal"].startswith("form field label")
    assert usage.roles["a.ph"].startswith("input placeholder")
    assert "a.plain" not in usage.roles


def test_markup_role_wins_over_key_name() -> None:
    item = BatchItem(source="Deal", message_key="table.ctrl.button_deal", ui_role="form field label: noun phrase")
    assert "[role: form field label: noun phrase]" in _item_annotations(item)
    assert "[role: button label]" in _item_annotations(BatchItem(source="Go", message_key="x.button"))
