"""HTML integrity (V27) and quality_band helpers."""

from __future__ import annotations

from llm_localizator.core.quality import quality_band
from llm_localizator.core.validate import (
    check_html_integrity,
    source_has_html_tags,
    validate_translation,
    validate_translation_detailed,
)
from llm_localizator.pipeline.prompts import BatchItem, build_batch_prompt, build_single_prompt


def test_comparison_less_than_is_not_html() -> None:
    assert not source_has_html_tags("score a < b for ranking")
    assert check_html_integrity("score a < b", "wynik a < b") is None


def test_html_tag_preserved() -> None:
    src = 'Click <a href="{url}">here</a> now'
    ok = 'Kliknij <a href="{url}">tutaj</a> teraz'
    assert check_html_integrity(src, ok) is None
    assert validate_translation(src, ok, "pl", {})[0]


def test_html_tag_dropped_rejects() -> None:
    src = "Click <b>here</b> now"
    bad = "Kliknij tutaj teraz"
    issue = check_html_integrity(src, bad)
    assert issue and "missing" in issue
    ok, reason = validate_translation(src, bad, "pl", {})
    assert not ok
    assert "HTML" in reason
    detailed_ok, failures = validate_translation_detailed(src, bad, "pl", {})
    assert not detailed_ok
    assert failures[0].id == "V27"


def test_html_void_br_preserved() -> None:
    src = "Line one<br/>Line two"
    ok = "Linia jeden<br/>Linia dwa"
    assert check_html_integrity(src, ok) is None


def test_invented_html_without_source_tags() -> None:
    issue = check_html_integrity("Hello", "<b>Cześć</b>")
    assert issue and "invented" in issue


def test_force_html_when_context_flag() -> None:
    # force with no source tags still rejects invented markup
    assert check_html_integrity("Play", "<b>Graj</b>", force=True)


def test_introduced_javascript_url_is_rejected() -> None:
    src = 'Click <a href="https://example.com">here</a>'
    bad = 'Kliknij <a href="javascript:alert(1)">tutaj</a>'
    issue = check_html_integrity(src, bad)
    assert issue and "javascript" in issue
    kept = 'Kliknij <a href="https://example.com">tutaj</a>'
    assert check_html_integrity(src, kept) is None
    already = 'Click <a href="javascript:void(0)">here</a>'
    same = 'Kliknij <a href="javascript:void(0)">tutaj</a>'
    assert check_html_integrity(already, same) is None


def test_quality_band_bt_keeps_threshold() -> None:
    assert quality_band(0.55, scale="bt") == "approve"
    assert quality_band(0.54, scale="bt") == "retranslate"
    assert quality_band(0.0, scale="bt") == "fail"


def test_quality_band_lqs_tiers() -> None:
    assert quality_band(0.96, scale="lqs") == "approve"
    assert quality_band(0.92, scale="lqs") == "flag"
    assert quality_band(0.85, scale="lqs") == "retranslate"
    assert quality_band(0.70, scale="lqs") == "needs_review"


def test_prompt_includes_message_key_and_html() -> None:
    item = BatchItem(
        source='Go <a href="{u}">here</a>',
        message_key="app.cta",
        html=True,
        context="video player button",
    )
    batch = build_batch_prompt([item], "Polish", "pl", "demo", "")
    assert "[key: app.cta]" in batch
    assert "[html: preserve tags]" in batch
    assert "[context: video player button]" in batch
    single = build_single_prompt(item, "Polish", "demo", "")
    assert "Message key: app.cta" in single
    assert "HTML" in single
