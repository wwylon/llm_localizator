"""Apple .xcstrings adapter: one file, all locales, plurals as ICU."""

import json

from llm_localizator.catalog import build_catalog

DOC = {
    "sourceLanguage": "en",
    "version": "1.0",
    "strings": {
        "Save": {"comment": "Button label", "extractionState": "manual", "localizations": {
            "pl": {"stringUnit": {"state": "needs_review", "value": "Zapisz"}}}},
        "Cancel": {},
        "items": {"localizations": {
            "en": {"variations": {"plural": {
                "one": {"stringUnit": {"state": "translated", "value": "%lld item"}},
                "other": {"stringUnit": {"state": "translated", "value": "%lld items"}}}}}}},
        "Tablet": {"localizations": {"en": {"variations": {"device": {
            "ipad": {"stringUnit": {"value": "Tap"}}}}}}},
        "Do not": {"shouldTranslate": False},
    },
}


def _cat(tmp_path):
    p = tmp_path / "Localizable.xcstrings"
    p.write_text(json.dumps(DOC), encoding="utf-8")
    return build_catalog("xcstrings", tmp_path, "Localizable.xcstrings", "en"), p


def test_load_source_uses_key_and_flattens_plurals(tmp_path):
    cat, _ = _cat(tmp_path)
    got = cat.load("en", None)
    assert got["Save"] == "Save" and got["Cancel"] == "Cancel"
    assert got["items"] == "{count, plural, one {%lld item} other {%lld items}}"
    assert "Tablet" not in got and "Do not" not in got
    assert cat.load("pl", None) == {"Save": "Zapisz"}
    assert cat.load_entries("en", None)["Save"].note == "Button label"
    assert cat.locales_present() == ["pl"]


def test_save_adds_locale_and_preserves_everything_else(tmp_path):
    cat, p = _cat(tmp_path)
    msgs = cat.load("pl", None)
    msgs["items"] = "{count, plural, one {%lld rzecz} few {%lld rzeczy} other {%lld rzeczy}}"
    msgs["Cancel"] = "Anuluj"
    cat.save("pl", None, msgs)
    raw = json.loads(p.read_text(encoding="utf-8"))
    s = raw["strings"]
    assert s["Save"]["localizations"]["pl"]["stringUnit"]["state"] == "needs_review"
    assert s["Save"]["comment"] == "Button label" and s["Save"]["extractionState"] == "manual"
    assert s["Cancel"]["localizations"]["pl"]["stringUnit"] == {"state": "translated", "value": "Anuluj"}
    plural = s["items"]["localizations"]["pl"]["variations"]["plural"]
    assert set(plural) == {"one", "few", "other"}
    assert s["items"]["localizations"]["en"]["variations"]["plural"]["one"]["stringUnit"]["value"] == "%lld item"
    assert s["Tablet"] == DOC["strings"]["Tablet"] and s["Do not"] == {"shouldTranslate": False}
    assert cat.load("pl", None)["items"].startswith("{count, plural, one {%lld rzecz}")


def test_unchanged_value_keeps_its_state_and_removal_drops_only_that_locale(tmp_path):
    cat, p = _cat(tmp_path)
    cat.save("pl", None, {"Save": "Zapisz"})
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["strings"]["Save"]["localizations"]["pl"]["stringUnit"]["state"] == "needs_review"
    cat.save("pl", None, {})
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert "pl" not in raw["strings"]["Save"].get("localizations", {})
    assert "items" in raw["strings"] and raw["strings"]["Tablet"] == DOC["strings"]["Tablet"]


def test_new_file_and_corrupt_file(tmp_path):
    cat = build_catalog("xcstrings", tmp_path, "Localizable.xcstrings", "en")
    cat.save("pl", None, {"Hello": "Czesc"})
    raw = json.loads((tmp_path / "Localizable.xcstrings").read_text(encoding="utf-8"))
    assert raw["sourceLanguage"] == "en" and raw["strings"]["Hello"]["localizations"]["pl"]
    (tmp_path / "Localizable.xcstrings").write_text("{broken", encoding="utf-8")
    import pytest
    with pytest.raises(Exception):
        cat.save("pl", None, {"Hello": "x"})
