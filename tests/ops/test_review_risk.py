"""review-risk ranking (P5, ADR-126)."""

from __future__ import annotations

import json

from llm_localizator.ops.review_risk import op_review_risk, risk_of
from llm_localizator.ops.set_translation import op_set


def test_risk_of_orders_the_signals() -> None:
    clean, _ = risk_of(source="Open the settings page", score=0.97, signals=[], status="machine",
                       has_draft=False)
    assert clean == 0
    contra, why = risk_of(source="Discard", score=0.6,
                          signals=["contradiction: …", "judge suggests: Odrzuć"],
                          status="machine", has_draft=True)
    assert contra > 5 and "judge suggested another text" in why and "short label" in why
    human, _ = risk_of(source="Discard", score=0.6, signals=["contradiction: …"], status="human",
                       has_draft=False)
    assert human < contra / 2


def test_review_risk_lists_and_exports(tmp_path, make_config) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps(
        {"a.discard": "Discard", "a.long": "Open the settings page now"}), encoding="utf-8")
    (tmp_path / "locales" / "pl.json").write_text("{}", encoding="utf-8")
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                      targets=["pl"], state_dir=tmp_path / ".state")
    op_set(cfg, locale="pl", key="a.discard", text="Zrzutka")
    op_set(cfg, locale="pl", key="a.long", text="Otwórz teraz stronę ustawień")
    result = op_review_risk(cfg, locale="pl")
    assert result.ok and result.data["rows"][0]["key"] == "a.discard"
    csv_out = op_review_risk(cfg, locale="pl", fmt="csv")
    assert csv_out.lines[0].startswith("key,source,current,suggestion")
    assert op_review_risk(cfg, locale="de").exit_code == 2
