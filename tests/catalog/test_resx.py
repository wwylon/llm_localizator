"""C-043: .resx adapter."""

from __future__ import annotations

from llm_localizator.catalog import build_catalog

TEMPLATE = "{namespace}.{locale}.resx"

SOURCE = """<?xml version="1.0" encoding="utf-8"?>
<root>
  <xsd:schema id="root" xmlns="" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
    <xsd:element name="root" />
  </xsd:schema>
  <resheader name="resmimetype">
    <value>text/microsoft-resx</value>
  </resheader>
  <data name="Greeting" xml:space="preserve">
    <value>Hello {0}</value>
    <comment>Shown on login</comment>
  </data>
  <data name="Logo" type="System.Resources.ResXFileRef, System.Windows.Forms">
    <value>logo.png;System.Drawing.Bitmap</value>
  </data>
  <data name="&gt;&gt;label1.Name" xml:space="preserve">
    <value>label1</value>
  </data>
  <data name="Bye" xml:space="preserve">
    <value>Goodbye &amp; take care</value>
  </data>
</root>
"""


def _cat(tmp_path):
    return build_catalog("resx", tmp_path, TEMPLATE, "en")


def test_load_skips_typed_and_designer_entries(tmp_path):
    (tmp_path / "App.en.resx").write_text(SOURCE, encoding="utf-8")
    cat = _cat(tmp_path)
    assert cat.load("en", "App") == {"Greeting": "Hello {0}", "Bye": "Goodbye & take care"}
    assert cat.load_entries("en", "App")["Greeting"].note == "Shown on login"
    assert cat.namespaces() == ["App"]


def test_save_preserves_everything_but_strings(tmp_path):
    path = tmp_path / "App.en.resx"
    path.write_text(SOURCE, encoding="utf-8")
    cat = _cat(tmp_path)
    cat.save("en", "App", {"Greeting": "Hi {0}", "Bye": "Goodbye & take care", "New": "x<y"})
    text = path.read_text(encoding="utf-8")
    assert "xmlns:xsd=" in text and "logo.png" in text and ">&gt;label1" not in text
    assert "&gt;&gt;label1.Name" in text and "resmimetype" in text
    assert "Shown on login" in text  # comment kept
    assert cat.load("en", "App") == {"Greeting": "Hi {0}", "Bye": "Goodbye & take care", "New": "x<y"}


def test_target_gets_source_notes_and_prunes_orphans(tmp_path):
    (tmp_path / "App.en.resx").write_text(SOURCE, encoding="utf-8")
    cat = _cat(tmp_path)
    cat.save("de", "App", {"Greeting": "Hallo {0}", "Old": "weg"})
    assert cat.load_entries("de", "App")["Greeting"].note == "Shown on login"
    cat.save("de", "App", {"Greeting": "Hallo {0}"})
    assert cat.load("de", "App") == {"Greeting": "Hallo {0}"}
    assert cat.locales_present() == ["de"]
