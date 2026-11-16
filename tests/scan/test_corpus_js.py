"""Golden FN/FP corpus for the raw-js pack (detection promotion rule)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan.raw_js import RawJsScanner

CORPUS = Path(__file__).parent / "corpus" / "js"
PY_CORPUS = Path(__file__).parent / "corpus" / "py"


def test_must_hit_corpus() -> None:
    result = RawJsScanner(CORPUS, ["must_hit"]).scan()
    by_file: dict[str, set[str]] = {}
    for h in result.hardcoded:
        by_file.setdefault(Path(h.file).name, set()).add(h.text)

    expected = {
        "el_approve.js": {"Approve all"},
        "el_div_label.js": {"Getting started", "Coverage by locale"},
        "card_helper.js": {
            "Assign a provider and model for each locale",
            "Confirm the bakeoff Winner note before swapping models. ADR-12 confirm.",
        },
        "field_panel_section.js": {
            "Model to evaluate",
            "Confirm the bakeoff Winner note before swapping.",
            "Translation stages",
            "Human verified coverage over time",
            "Workflow automation",
        },
        "inner_html_quoted.js": {
            "Review queue",
            "No items waiting for approval",
        },
        "label_array_foreach.js": {
            "Translator",
            "Changes",
            "By trigger",
            "Last activity",
            "By translator",
            "By locale",
            "Translators —",
        },
    }
    for name, texts in expected.items():
        found = by_file.get(name, set())
        missing = texts - found
        assert not missing, f"{name}: missing {missing}; got {found}"


def test_must_not_corpus() -> None:
    result = RawJsScanner(CORPUS, ["must_not"]).scan()
    forbidden = {
        "change", "click", "keydown", "submit",
        "human", "machine", "stale", "GET", "get",
        "button", "tab",
        "btn btn-primary",
        # Routed key+fallback arrays / uiT multiline el (label_array_uit.js)
        "Translator", "Changes", "Translators — {n}",
    }
    for h in result.hardcoded:
        assert h.text not in forbidden, (
            f"must_not false positive: {h.text!r} in {h.file}:{h.line}"
        )


def test_must_hit_ssr_shell_py() -> None:
    result = RawJsScanner(PY_CORPUS, ["must_hit"]).scan()
    texts = {h.text for h in result.hardcoded}
    assert "System settings" in texts
    assert any(h.text == "System settings" and h.confidence == "medium" for h in result.hardcoded)
    assert "Locales" in texts or "Translation engine" in texts


def test_negatives_module() -> None:
    from llm_localizator.scan.negatives import (
        is_listener_event_arg,
        is_non_ui_literal,
        is_non_user_attr_value,
    )

    assert is_non_ui_literal("change")
    assert is_non_ui_literal("human")
    assert not is_non_ui_literal("System settings")
    assert is_listener_event_arg('el.addEventListener("change", fn)', "change")
    assert is_non_user_attr_value('type="button"', "button")
