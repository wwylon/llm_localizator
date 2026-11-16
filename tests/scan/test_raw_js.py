"""RawJsScanner — §3 template literal tag expansion and §4 routed-skip patterns."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.scan.raw_js import RawJsScanner


def scan_source_js(tmp_path: Path, source: str, name: str = "app.js"):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / name).write_text(source, encoding="utf-8")
    return RawJsScanner(tmp_path, ["src"]).scan()


def scan_source_html(tmp_path: Path, source: str, name: str = "page.html"):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / name).write_text(source, encoding="utf-8")
    return RawJsScanner(tmp_path, ["src"]).scan()


# ---- §3 template literal tag expansion -------------------------------------

def test_p_tag_in_template_literal(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, "const x = `<p>Loading results</p>`;")
    assert result.hardcoded


def test_li_tag_in_template_literal(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, "const x = `<li>No items found yet</li>`;")
    assert result.hardcoded


def test_option_tag_in_template_literal(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, "const x = `<option>Select a country</option>`;")
    assert result.hardcoded


def test_template_literal_with_expression_still_matches(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, "const x = `<p>${user.name} joined the club</p>`;")
    assert any("joined the club" in h.text for h in result.hardcoded)


def test_template_literal_confidence_is_medium(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, "const x = `<p>Loading results</p>`;")
    assert result.hardcoded
    assert all(h.confidence == "medium" for h in result.hardcoded)


# ---- §4 already-routed skip in raw JS / HTML --------------------------------

@pytest.mark.parametrize("source", [
    "const x = i18n.t('key');",
    '<p data-i18n="nav.title">Sign in</p>',
    "const label = $t('auth.signIn')",
    "container.innerHTML = __('Sign in');",
])
def test_already_routed_lines_not_flagged(tmp_path: Path, source: str) -> None:
    result = scan_source_js(tmp_path, source)
    assert result.hardcoded == []


# ---- §7 confidence in HTML -------------------------------------------------

def test_html_text_confidence_is_high(tmp_path: Path) -> None:
    result = scan_source_html(tmp_path, "<p>Please sign in now</p>")
    assert result.hardcoded
    assert all(h.confidence == "high" for h in result.hardcoded)


def test_el_multiword_label(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'var b = el("button", "btn", "Approve all");')
    assert any(h.text == "Approve all" for h in result.hardcoded)


def test_el_single_word_widget(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'var b = el("button", "btn", "Lock");')
    assert any(h.text == "Lock" and h.confidence == "medium" for h in result.hardcoded)


def test_el_class_list_not_flagged(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'var d = el("div", "btn btn-primary", "x");')
    assert not any(h.text == "btn btn-primary" for h in result.hardcoded)


def test_confirm_dialog(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'window.confirm("Replace in all locales?");')
    assert any("Replace in all locales" in h.text for h in result.hardcoded)


def test_textContent_assignment(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'node.textContent = "Nothing matches.";')
    assert any(h.text == "Nothing matches." for h in result.hardcoded)


def test_uit_routed_line_skipped(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'var t = uiT("suggest_why", "Why this result");')
    assert result.hardcoded == []


def test_el_concat_short_prefix_not_flagged(tmp_path: Path) -> None:
    """``el(..., "No " + level)`` must not report the orphan prefix ``No``."""
    src = 'table.appendChild(el("div", "log-line-dim", "No " + level + " findings."));'
    result = scan_source_js(tmp_path, src)
    assert not any(h.text.strip() in {"No", "No "} for h in result.hardcoded)


def test_el_concat_prose_prefix_flagged(tmp_path: Path) -> None:
    src = 'el("div", "", "No matching results for " + q);'
    result = scan_source_js(tmp_path, src)
    assert any("No matching results for" in h.text for h in result.hardcoded)


def test_el_complete_third_arg_still_flagged(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'el("button", "btn", "Approve all");')
    assert any(h.text == "Approve all" for h in result.hardcoded)


def test_create_text_node_prose(tmp_path: Path) -> None:
    result = scan_source_js(
        tmp_path, 'lab.appendChild(document.createTextNode("Include screenshots"));'
    )
    assert any(h.text == "Include screenshots" for h in result.hardcoded)


def test_create_text_node_joiner_skipped(tmp_path: Path) -> None:
    result = scan_source_js(
        tmp_path, 'lab.appendChild(document.createTextNode(" "));'
    )
    assert result.hardcoded == []


def test_set_status_helper_sink(tmp_path: Path) -> None:
    result = scan_source_js(tmp_path, 'setStatus("Provider id is required.");')
    assert any(h.text == "Provider id is required." for h in result.hardcoded)


def test_label_array_foreach_headers(tmp_path: Path) -> None:
    src = (
        '["Translator", "Changes", "By trigger"].forEach(function (label) {\n'
        '  hr.appendChild(el("th", "", label));\n'
        "});\n"
    )
    result = scan_source_js(tmp_path, src)
    texts = {h.text for h in result.hardcoded}
    assert {"Translator", "Changes", "By trigger"} <= texts


def test_label_array_uit_skipped(tmp_path: Path) -> None:
    src = (
        '[["act_col_translator", "Translator"]].forEach(function (row) {\n'
        '  hr.appendChild(el("th", "", uiT(row[0], row[1])));\n'
        "});\n"
    )
    result = scan_source_js(tmp_path, src)
    assert not any(h.text == "Translator" for h in result.hardcoded)


def test_multiline_el_concat_prose(tmp_path: Path) -> None:
    src = (
        "wrap.appendChild(el(\n"
        '  "div", "users-section-label",\n'
        '  "Translators — " + n\n'
        "));\n"
    )
    result = scan_source_js(tmp_path, src)
    assert any("Translators —" in h.text for h in result.hardcoded)
