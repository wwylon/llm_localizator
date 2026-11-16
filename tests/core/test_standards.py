"""Message standards: tokens, syntax, and the accept gate."""

from __future__ import annotations

import pytest

from llm_localizator.core.standards import get_standard
from llm_localizator.core.validate import validate_translation

_CASES = [
    ("icu", "Hello {name}", None, {"name"}),
    ("icu", "Hello {{name}}", None, set()),
    ("printf", "Hello %s", None, {"%s"}),
    ("printf", "100% sure", None, set()),
    ("printf", "Hello %(name)s", None, {"%(name)s"}),
    ("printf", "Hello %1$s", None, {"%1$s"}),
    ("printf", "Hello %(name", "unclosed printf placeholder", set()),
    ("brace", "Hello {0:N}", None, {"0:N"}),
    ("brace", "Hello {name}", None, {"name"}),
    ("brace", "{n, plural, one {#} other {#}}", "ICU plural is not valid brace syntax", set()),
    ("i18next", "Hello {{name}}", None, {"name"}),
    ("i18next", "Hello {{.Name}}", "go template is not an i18next placeholder", set()),
    ("go-template", "Hello {{.Name}}", None, {".Name"}),
    ("go-template", "Hello {{ .Name }}", None, {".Name"}),
    ("laravel", "Hello :name", None, {":name"}),
    ("laravel", "Meet at 12:30", None, set()),
    ("laravel", "mailto:user", None, set()),
]


@pytest.mark.parametrize("standard_id,text,error,tokens", _CASES)
def test_standard_tokens(standard_id, text, error, tokens) -> None:
    standard = get_standard(standard_id)
    assert standard.syntax_error(text) == error
    if error is None:
        assert standard.tokens(text) == tokens


def test_printf_drop_is_rejected() -> None:
    standard = get_standard("printf")
    ok, reason = validate_translation(
        "Hello %s", "Cześć", "pl", {}, standard=standard,
    )
    assert not ok
    assert "placeholder" in reason


def test_icu_plural_still_rejected() -> None:
    standard = get_standard("icu")
    ok, reason = validate_translation(
        "{n, plural, one {# file} other {# files}}",
        "{n, plural, other {# plików}}",
        "pl",
        {},
        standard=standard,
    )
    assert not ok
    assert "plural" in reason


def test_i18next_missing_sibling() -> None:
    standard = get_standard("i18next")
    missing = standard.missing_plural_keys(
        {"item_one": "a", "item_other": "b"}, "pl",
    )
    assert "item_few" in missing
    assert "item_many" in missing


def test_v16_reports_unclosed_source(tmp_path, make_config) -> None:
    from llm_localizator.catalog import JsonNestedCatalog
    from llm_localizator.pipeline.validate import run_validation

    from tests.conftest import setup_project

    setup_project(tmp_path, {"greet": "Hello {name"})
    cfg = make_config(tmp_path)
    catalog = JsonNestedCatalog(cfg.root, cfg.catalog_path, cfg.source_locale)
    report = run_validation(cfg, catalog, locales=["pl"])
    assert any(item.check == "V16" for item in report.findings)


def test_every_standard_has_a_case() -> None:
    covered = {row[0] for row in _CASES}
    from llm_localizator.core.languages import standard_ids

    assert covered == set(standard_ids())
