"""XLIFF catalogue adapter: 1.2 and 2.0, in-place saves."""

from llm_localizator.catalog import build_catalog

SRC = """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="app" source-language="en" datatype="plaintext">
    <body>
      <trans-unit id="a"><source>Save</source><note>Button</note></trans-unit>
      <trans-unit id="b"><source>Cancel</source></trans-unit>
      <trans-unit id="c" translate="no"><source>Brand</source></trans-unit>
    </body>
  </file>
</xliff>
"""
PL = """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="app" source-language="en" target-language="pl" datatype="plaintext">
    <body>
      <trans-unit id="a" approved="yes"><source>Save</source><target state="final">Zapisz <g id="1">teraz</g></target><note>Button</note></trans-unit>
      <trans-unit id="b"><source>Cancel</source></trans-unit>
      <trans-unit id="c" translate="no"><source>Brand</source><target>Brand</target></trans-unit>
      <trans-unit id="gone"><source>Old</source><target>Stare</target></trans-unit>
    </body>
  </file>
</xliff>
"""
V2 = """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="2.0" xmlns="urn:oasis:names:tc:xliff:document:2.0" srcLang="en" trgLang="pl">
  <file id="f1">
    <unit id="a"><notes><note>Button</note></notes><segment state="initial"><source>Save</source><target>Zapisz</target></segment></unit>
  </file>
</xliff>
"""


def _cat(tmp_path, pl=PL):
    (tmp_path / "app.en.xlf").write_text(SRC, encoding="utf-8")
    (tmp_path / "app.pl.xlf").write_text(pl, encoding="utf-8")
    return build_catalog("xliff", tmp_path, "{namespace}.{locale}.xlf", "en")


def test_load_source_target_notes(tmp_path):
    cat = _cat(tmp_path)
    assert cat.load("en", "app") == {"a": "Save", "b": "Cancel"}
    assert cat.load("pl", "app")["a"] == "Zapisz teraz"
    assert cat.load_entries("en", "app")["a"].note == "Button"


def test_save_keeps_attributes_prunes_and_adds(tmp_path):
    cat = _cat(tmp_path)
    msgs = cat.load("pl", "app")
    cat.save("pl", "app", {"a": msgs["a"], "b": "Anuluj"})
    text = (tmp_path / "app.pl.xlf").read_text(encoding="utf-8")
    assert '<g id="1">teraz</g>' in text and 'approved="yes"' in text and 'state="final"' in text
    assert 'translate="no"' in text and "Brand" in text
    assert "Stare" not in text
    assert '<target state="translated">Anuluj</target>' in text
    assert cat.load("pl", "app") == {"a": "Zapisz teraz", "b": "Anuluj"}


def test_changed_value_sets_state(tmp_path):
    cat = _cat(tmp_path)
    cat.save("pl", "app", {"a": "Zachowaj", "b": ""})
    text = (tmp_path / "app.pl.xlf").read_text(encoding="utf-8")
    assert '<target state="translated">Zachowaj</target>' in text


def test_new_target_file_copies_source_and_note(tmp_path):
    cat = _cat(tmp_path)
    cat.save("fr", "app", {"a": "Enregistrer"})
    text = (tmp_path / "app.fr.xlf").read_text(encoding="utf-8")
    assert 'target-language="fr"' in text and "<source>Save</source>" in text
    assert "<note>Button</note>" in text
    assert cat.load("fr", "app") == {"a": "Enregistrer"}


def test_version_2_roundtrip(tmp_path):
    cat = _cat(tmp_path, V2)
    assert cat.load("pl", "app") == {"a": "Zapisz"}
    cat.save("pl", "app", {"a": "Zapisz!"})
    text = (tmp_path / "app.pl.xlf").read_text(encoding="utf-8")
    assert 'version="2.0"' in text and 'state="translated"' in text and "<note>Button</note>" in text
    assert cat.load("pl", "app") == {"a": "Zapisz!"}
