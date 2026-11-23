"""v63: a string on the line after ``Text(`` is a UI sink; AppStream store text is scanned."""

from __future__ import annotations

from llm_localizator.scan.source import SourceScanner

DART = """import 'package:flutter/material.dart';

Widget build(BuildContext context) {
  return TextButton(
    child: const Text(
      'Close',
      style: kStyle,
    ),
    onPressed: () {},
  );
}

const kPath = 'assets/images/background.png';
"""

METAINFO = """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.example.Notes</id>
  <name>Example Notes</name>
  <summary>Write and sync notes between devices</summary>
  <description>
    <p>Notes keeps every note on your own machines and syncs them over your network.</p>
    <ul><li>Works without an account</li></ul>
  </description>
  <url type="homepage">https://example.org</url>
</component>
"""


def test_a_string_on_the_line_after_a_widget_call_is_found(tmp_path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "menu.dart").write_text(DART, encoding="utf-8")
    texts = {hit.text for hit in SourceScanner(tmp_path, ["."]).scan().hardcoded}
    assert "Close" in texts
    assert "assets/images/background.png" not in texts


def test_appstream_summary_description_and_list_items_are_found_but_ids_and_urls_are_not(tmp_path) -> None:
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging" / "org.example.Notes.metainfo.xml").write_text(METAINFO, encoding="utf-8")
    texts = {hit.text for hit in SourceScanner(tmp_path, ["."]).scan().hardcoded}
    assert "Write and sync notes between devices" in texts
    assert "Works without an account" in texts
    assert "org.example.Notes" not in texts and "https://example.org" not in texts
