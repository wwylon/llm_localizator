"""`report`: read-only shareable page with a verdict (ADR-163)."""

from __future__ import annotations

import json

from llm_localizator.ops.report import _verdict, op_report, render_html, render_markdown

from tests.conftest import setup_project


def _cfg(project_root, make_config, existing):
    setup_project(project_root, {"hello": "Hello", "bye": "Goodbye"}, existing=existing)
    return make_config(project_root)


def test_complete_but_unrecorded_catalogue_is_go_with_notes(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config, {"hello": "Cześć", "bye": "Pa"})
    out = op_report(cfg)
    assert out.ok and out.exit_code == 0
    assert out.data["verdict"] == "go-with-notes"
    text = out.data["text"]
    assert text.startswith("# Localization report: testproj")
    assert "| pl | 2/2 (100.0%) |" in text  # has text, even without state records
    assert any("not recorded" in n for n in out.data["notes"])


def test_missing_translation_in_active_locale_is_no_go(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config, {"hello": "Cześć"})
    out = op_report(cfg)
    assert out.data["verdict"] == "no-go" and out.exit_code == 1  # V01, same as validate
    assert "| pl | 1/2 (50.0%) |" in out.data["text"]


def test_validation_errors_make_it_no_go_and_exit_1(project_root, make_config) -> None:
    setup_project(project_root, {"n": "{count} files"}, existing={"n": "pliki"})  # placeholder lost
    cfg = make_config(project_root)
    out = op_report(cfg)
    assert out.data["verdict"] == "no-go" and out.exit_code == 1
    assert any("validation error" in r for r in out.data["reasons"])


def test_report_writes_only_the_out_file(project_root, make_config, tmp_path_factory) -> None:
    cfg = _cfg(project_root, make_config, {"hello": "Cześć", "bye": "Pa"})
    before = {p: p.read_bytes() for p in project_root.rglob("*") if p.is_file()}
    dest = tmp_path_factory.mktemp("elsewhere") / "out" / "report.html"
    out = op_report(cfg, fmt="html", out=str(dest))
    assert dest.read_text(encoding="utf-8").startswith("<!doctype html>")
    after = {p: p.read_bytes() for p in project_root.rglob("*") if p.is_file()}
    assert after == before, "report must not touch the project"
    assert out.data["path"] == str(dest)


def test_json_format_round_trips(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config, {"hello": "Cześć", "bye": "Pa"})
    facts = json.loads(op_report(cfg, fmt="json").data["text"])
    assert facts["project"] == "testproj" and facts["active"] == ["pl"]


def test_html_escapes_untrusted_text() -> None:
    facts = {
        "project": "<script>x</script>", "generated_at": "t", "source_locale": "en",
        "active": ["pl"], "frozen": [], "coverage": [], "keys": None,
        "validate": {"errors": 0, "warnings": 0, "errors_by_check": {}, "examples": ["<b>e</b>"]},
        "hardcoded": {"counts": {}, "stale": False, "cached": True},
        "review": {}, "drafts": {}, "spend": None, "runs": [],
    }
    facts["verdict"], facts["reasons"], facts["notes"] = _verdict(facts)
    page = render_html(facts)
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page
    assert "<b>e</b>" not in page
    assert facts["verdict"] == "go" and "Nothing to fix" in render_markdown(facts)


def _facts(keys: dict) -> dict:
    return {
        "active": ["pl"], "coverage": [], "keys": keys,
        "validate": {"errors": 0, "warnings": 0},
        "hardcoded": {"counts": {}, "stale": False}, "review": {}, "drafts": {},
    }


def test_stale_pseudo_locale_is_a_note_not_no_go() -> None:
    verdict, reasons, notes = _verdict(_facts({"ok": False, "summary": "en-XX stale", "missing": 0}))
    assert verdict == "go-with-notes" and not reasons and any("en-XX" in n for n in notes)
    verdict, reasons, _ = _verdict(_facts({"ok": False, "summary": "s", "missing": 2}))
    assert verdict == "no-go" and "2 key(s)" in reasons[0]


def test_unknown_format_is_usage_error(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config, {"hello": "Cześć"})
    assert op_report(cfg, fmt="pdf").exit_code == 64
