"""Hermetic checks for the leftovers and process wave."""

from __future__ import annotations

from llm_localizator.catalog.state import translation_status
from llm_localizator.ops.release import op_release_diff, op_release_freeze
from llm_localizator.ops.terminology import op_term_report
from llm_localizator.providers._prompt_utils import extract_sources as _extract_sources

from tests.conftest import setup_project, write_json


def test_intentional_status_only_when_value_matches_source() -> None:
    from llm_localizator.core.hash import src_hash

    fresh = {"status": "intentional", "src_sha": src_hash("Save")}
    assert translation_status("Save", "Save", fresh) == "intentional"
    assert translation_status("Save", "Zapisz", fresh) == "human"


def test_deepl_does_not_guess_the_last_line() -> None:
    assert _extract_sources("JSON array of N translations:", None) == []


def test_term_report_names_a_missing_approved_term(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"title": "Save the file"}, existing={"title": "Save the file"})
    glossary = tmp_path / "glossary.json"
    write_json(glossary, {"doNotTranslate": [], "terms": {"Save": {"pl": "Zapisz"}}})
    cfg = make_config(tmp_path, glossary_path=glossary)
    result = op_term_report(cfg)
    assert result.ok
    assert any("title" in line and "Save" in line for line in result.lines)


def test_release_freeze_and_diff_do_not_touch_catalogues(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"title": "Hello"})
    cfg = make_config(tmp_path)
    frozen = op_release_freeze(cfg, name="rc1")
    assert frozen.ok
    snap = tmp_path / "messages" / ".state" / "releases" / "rc1.json"
    assert snap.exists()
    source = (tmp_path / "messages" / "en" / "app.json").read_text(encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"title": "Hello", "extra": "New"})
    diff = op_release_diff(cfg, name="rc1")
    assert diff.ok
    assert "extra" in " ".join(diff.data["added"])
    assert (tmp_path / "messages" / "en" / "app.json").read_text(encoding="utf-8") != source
