"""Apple .stringsdict adapter: plural entries round-trip through ICU."""

import pytest

from llm_localizator.catalog import build_catalog

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>items</key><dict>
<key>NSStringLocalizedFormatKey</key><string>You have %#@n@ left</string>
<key>n</key><dict>
<key>NSStringFormatSpecTypeKey</key><string>NSStringPluralRuleType</string>
<key>NSStringFormatValueTypeKey</key><string>lu</string>
<key>one</key><string>%lu item</string>
<key>other</key><string>%lu items</string>
</dict></dict></dict></plist>
"""


def _cat(tmp_path):
    return build_catalog("ios-stringsdict", tmp_path, "{locale}.lproj/Localizable.stringsdict")


def _write(tmp_path, text=PLIST):
    p = tmp_path / "en.lproj" / "Localizable.stringsdict"
    p.parent.mkdir(parents=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_load_flattens_to_icu(tmp_path):
    _write(tmp_path)
    got = _cat(tmp_path).load("en", None)
    assert got == {"items": "You have {n, plural, one {%lu item} other {%lu items}} left"}


def test_save_roundtrips_and_keeps_value_type(tmp_path):
    p = _write(tmp_path)
    cat = _cat(tmp_path)
    cat.save("en", None, {"items": "You have {n, plural, one {%lu thing} other {%lu things}} left"})
    assert "<string>lu</string>" in p.read_text(encoding="utf-8")
    assert cat.load("en", None)["items"].endswith("{%lu thing} other {%lu things}} left")


def test_multi_variable_entry_is_refused_not_dropped(tmp_path):
    _write(tmp_path, PLIST.replace("%#@n@ left", "%#@n@ and %#@m@"))
    with pytest.raises(ValueError, match="exactly one"):
        _cat(tmp_path).load("en", None)
