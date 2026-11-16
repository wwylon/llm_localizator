"""Qt Linguist ``.ts`` adapter: real file shapes survive a round trip (ADR-140)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.catalog import build_catalog

SEP = "\x04"
EN = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="en" sourcelanguage="en">
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../mainwindow.cpp" line="12"/>
        <source>Open file</source>
        <extracomment>Menu entry</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Save</source>
        <comment>verb</comment>
        <translation type="unfinished"></translation>
    </message>
    <message numerus="yes">
        <source>%n file(s) selected</source>
        <translation type="unfinished">
            <numerusform></numerusform>
            <numerusform></numerusform>
        </translation>
    </message>
    <message>
        <source>Gone</source>
        <translation type="vanished">Gone</translation>
    </message>
</context>
</TS>
"""
PL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="pl" sourcelanguage="en">
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../mainwindow.cpp" line="12"/>
        <source>Open file</source>
        <extracomment>Menu entry</extracomment>
        <translation>Otwórz plik</translation>
    </message>
    <message>
        <source>Save</source>
        <comment>verb</comment>
        <translation type="unfinished"></translation>
    </message>
    <message numerus="yes">
        <source>%n file(s) selected</source>
        <translation>
            <numerusform>%n plik</numerusform>
            <numerusform>%n pliki</numerusform>
            <numerusform>%n plików</numerusform>
        </translation>
    </message>
</context>
</TS>
"""
OPEN = f"MainWindow{SEP}Open file"
SAVE = f"MainWindow{SEP}Save{SEP}verb"
FILES = f"MainWindow{SEP}%n file(s) selected"


def _cat(tmp_path: Path):
    (tmp_path / "app_en.ts").write_text(EN, encoding="utf-8")
    (tmp_path / "app_pl.ts").write_text(PL, encoding="utf-8")
    return build_catalog("qt-ts", tmp_path, "app_{locale}.ts", "en")


def test_source_locale_reads_source_text_and_skips_vanished(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    en = cat.load("en")
    assert en[OPEN] == "Open file" and en[SAVE] == "Save"
    assert en[FILES].startswith("{n, plural,")
    assert not any("Gone" in k for k in en)
    assert cat.load_entries("en")[OPEN].note == "Menu entry"


def test_target_reads_translations_and_plural_forms(tmp_path: Path) -> None:
    pl = _cat(tmp_path).load("pl")
    assert pl[OPEN] == "Otwórz plik"
    assert SAVE not in pl  # unfinished and empty
    assert "# plików" in pl[FILES] and "one {# plik}" in pl[FILES]


def test_save_unchanged_is_byte_identical_and_edit_is_local(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    path = tmp_path / "app_pl.ts"
    cat.save("pl", None, {**cat.load("pl"), SAVE: "Zapisz"})
    text = path.read_text(encoding="utf-8")
    assert "<translation>Zapisz</translation>" in text
    assert text.count('type="unfinished"') == 0
    assert '<location filename="../mainwindow.cpp" line="12"/>' in text
    assert "Menu entry" in text
    again = path.read_bytes()
    cat.invalidate()
    cat.save("pl", None, cat.load("pl"))
    assert path.read_bytes() == again


def test_new_and_pruned_messages(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    merged = {k: v for k, v in cat.load("pl").items() if k != OPEN}
    merged[f"Dialog{SEP}Cancel"] = "Anuluj"
    cat.save("pl", None, merged)
    cat.invalidate()
    out = cat.load("pl")
    assert OPEN not in out and out[f"Dialog{SEP}Cancel"] == "Anuluj" and FILES in out


def test_plural_edit_keeps_slot_count(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    value = cat.load("pl")[FILES].replace("plików", "plikow")
    cat.save("pl", None, {**cat.load("pl"), FILES: value})
    text = (tmp_path / "app_pl.ts").read_text(encoding="utf-8")
    assert text.count("<numerusform>") == 3 and "%n plikow" in text
