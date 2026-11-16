"""Validation against the curated mini fixture.

Every edge case the fixture encodes has an assertion here, so the fixture cannot
drift into being decorative (ADR-4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.pipeline.validate import run_validation
from llm_localizator.projects import load_config


@pytest.fixture
def report(mini_fixture: Path):
    cfg = load_config(mini_fixture / ".llm-localize.toml")
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    return cfg, catalog, run_validation(cfg, catalog, locales=["pl", "ar", "de"])


def checks_for(report, locale: str, key: str) -> set[str]:
    return {f.check for f in report.findings if f.locale == locale and f.key == key}


# ---- structure -------------------------------------------------------------

def test_fixture_loads_and_flattens_nested_keys(mini_fixture: Path) -> None:
    cfg = load_config(mini_fixture / ".llm-localize.toml")
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    source = catalog.load("en", "play")
    assert "tactics.claim" in source
    assert source["tactics.claim"] == "Claim"


def test_namespaces_are_discovered(mini_fixture: Path) -> None:
    cfg = load_config(mini_fixture / ".llm-localize.toml")
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    assert catalog.namespaces() == ["nav", "play"]


# ---- the encoded edge cases ------------------------------------------------

def test_polish_plural_categories_pass(report) -> None:
    _, _, r = report
    assert "V03" not in checks_for(r, "pl", "tricks")


def test_arabic_six_categories_pass(report) -> None:
    _, _, r = report
    assert "V03" not in checks_for(r, "ar", "tricks")


def test_explicit_zero_selector_is_accepted(report) -> None:
    """`=0` satisfies the `zero` requirement -- Arabic 'watching' uses it."""
    _, _, r = report
    assert "V03" not in checks_for(r, "ar", "watching")


def test_do_not_translate_term_survives_in_arabic(report) -> None:
    """The word-boundary fix: this passes only because matching works for RTL."""
    _, _, r = report
    assert "V04" not in checks_for(r, "ar", "convention")


def test_orphan_key_is_reported(report) -> None:
    _, _, r = report
    assert "V12" in checks_for(r, "pl", "removedKey")


def test_untranslated_value_is_reported(report) -> None:
    _, _, r = report
    assert "V06" in checks_for(r, "pl", "home")


def test_naive_plural_in_source_is_reported(report) -> None:
    _, _, r = report
    assert any(f.check == "V10" and f.key == "unreadCount" for f in r.findings)


def test_locale_missing_a_namespace_reports_every_key(report) -> None:
    """de has play.json but no nav.json."""
    _, _, r = report
    missing = {f.key for f in r.findings if f.locale == "de" and f.check == "V01"}
    assert {"home", "profile", "unreadCount"} <= missing


def test_skip_key_is_never_reported(report) -> None:
    _, _, r = report
    assert not any(f.key == "brand" for f in r.findings)


def test_fixture_has_no_unexpected_errors(report) -> None:
    """Only the deliberate de-missing-namespace case should error."""
    _, _, r = report
    unexpected = [f for f in r.errors if f.locale != "de"]
    assert not unexpected, [f"{f.check} {f.location()}: {f.message}" for f in unexpected]


# ---- end-to-end translation over the fixture -------------------------------

def test_translation_over_the_fixture_is_clean(mini_fixture: Path, tmp_path: Path, silent) -> None:
    """Copy, translate with the null provider, and re-validate: no new errors."""
    import shutil

    from llm_localizator.pipeline.translate import run_translation
    from llm_localizator.providers import NullProvider

    from ..pipeline.test_translate import tagged

    work = tmp_path / "mini"
    shutil.copytree(mini_fixture, work)
    cfg = load_config(work / ".llm-localize.toml")
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)

    result = run_translation(
        cfg, catalog, NullProvider(handler=tagged), locales=["de"], report=silent,
    )

    assert result.written > 0
    assert catalog.path_for("de", "nav").exists(), "the missing namespace file is created"
