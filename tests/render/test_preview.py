"""Preview is a view. Stored text is not rewritten."""

from __future__ import annotations

from llm_localizator.core.plural import plural_category
from llm_localizator.render import preview, preview_payload
from llm_localizator.render.icu import preview_icu, render_message

_PL = "{n, plural, one {# nowe} few {# nowe} many {# nowych} other {# nowe}}"
_PROMETHEUS = (
    "HTTP mean {mean} ms over {count, plural, one {# request} other {# requests}} "
    "(p95 via Prometheus)"
)


def test_polish_samples_pick_one_few_many_other() -> None:
    assert plural_category("pl", 1) == "one"
    assert plural_category("pl", 2) == "few"
    assert plural_category("pl", 5) == "many"
    assert plural_category("pl", 1.5) == "other"
    assert plural_category("pl", 12) == "many"


def test_icu_preview_renders_the_polish_arms() -> None:
    html = preview(_PL, "pl", "icu")
    assert "n=1" in html and "one" in html and "1 nowe" in html
    assert "few" in html and "many" in html and "other" in html
    assert "1.5" in html


def test_exact_arm_wins_over_the_category() -> None:
    text = "{n, plural, =0 {brak} one {# nowe} other {# nowe}}"
    html = preview(text, "pl", "icu")
    assert "brak" in html


def test_markdown_preview_is_html_and_does_not_change_source() -> None:
    source = "# Hello\n\n<script>alert(1)</script>\n"
    html = preview(source, "en", "markdown")
    assert "<h1>Hello</h1>" in html
    assert "<script>" not in html
    assert source == "# Hello\n\n<script>alert(1)</script>\n"


def test_html_preview_strips_script_and_handlers() -> None:
    source = (
        '<p onclick="steal()">Hi</p><script>bad()</script>'
        '<a href="https://evil.test">x</a>'
        '<a href=javascript:alert(1)>y</a>'
        '<svg/onload=alert(1)>'
    )
    html = preview(source, "en", "html")
    assert "<script>" not in html
    assert "onclick" not in html
    assert "javascript:" not in html.lower()
    assert "onload" not in html.lower()
    # Allowlisted https links stay; javascript/handlers do not.
    assert 'href="https://evil.test"' in html
    assert source.startswith("<p onclick")


def test_filled_preview_substitutes_all_placeholders() -> None:
    filled = render_message(_PROMETHEUS, "en", {"mean": "12.4", "count": 1})
    assert filled == "HTTP mean 12.4 ms over 1 request (p95 via Prometheus)"
    payload = preview_payload(
        _PROMETHEUS, "en", "icu", values={"mean": "12.4", "count": "1"},
    )
    assert payload["placeholders"] == ["count", "mean"]
    assert "12.4" in payload["html"]
    assert "1 request" in payload["html"]
    assert "{mean}" not in payload["html"]
    assert "<ul" not in payload["html"]


def test_samples_preview_merges_bare_placeholder_values() -> None:
    html = preview_icu(_PROMETHEUS, "en", base_values={"mean": "9"})
    assert "mean=9" not in html  # label is count=…
    assert "HTTP mean 9 ms" in html
    assert "{mean}" not in html
    payload = preview_payload(
        _PROMETHEUS, "en", "icu", values={"mean": "9"}, mode="samples",
    )
    assert "HTTP mean 9 ms" in payload["html"]
    assert "<ul" in payload["html"]


def test_preview_payload_lists_placeholders_without_values() -> None:
    payload = preview_payload(_PROMETHEUS, "en", "icu")
    assert payload["placeholders"] == ["count", "mean"]
    assert "count=1" in payload["html"]
