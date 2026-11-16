"""Property-line UI definitions: QML, Kivy, Godot scenes (ADR-143)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import build_scanner


def _texts(tmp_path: Path, name: str, body: str) -> set[str]:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / name).write_text(body, encoding="utf-8")
    hits = build_scanner("source", tmp_path, ["src"]).scan().hardcoded
    return {" ".join(h.text.split()) for h in hits}


def test_qml_text_properties_but_not_translated_or_bound_values(tmp_path: Path) -> None:
    texts = _texts(tmp_path, "Main.qml", (
        "Item {\n"
        '    Button { text: "Save changes" }\n'
        '    Label { text: i18n("Already translated text") }\n'
        "    Label { text: root.title }\n"
        "    ListElement { displayName: \"Text Color\"; value: 1 }\n"
        '    // text: "Commented out text here"\n'
        '    property var rules: { "label": "Stretch" }\n'
        "}\n"
    ))
    assert {"Save changes", "Text Color"} <= texts
    assert not any("Already translated" in t or "Commented out" in t for t in texts)


def test_kivy_properties(tmp_path: Path) -> None:
    texts = _texts(tmp_path, "main.kv", (
        "<Root>:\n"
        "    Button:\n"
        "        text: 'Close'\n"
        "        info_text: 'Search (Ctrl+Shift+F)'\n"
        "        on_release: app.close('now')\n"
    ))
    assert {"Close", "Search (Ctrl+Shift+F)"} <= texts
    assert "now" not in texts


def test_godot_scene_text_over_several_lines_and_script_source_ignored(tmp_path: Path) -> None:
    texts = _texts(tmp_path, "Menu.tscn", (
        '[node name="Label" type="Label"]\n'
        'text = "Pause Menu"\n'
        '[node name="Desc" type="Label"]\n'
        'text = "An old, slightly rusted sword.\n'
        'Fairly dull."\n'
        '[sub_resource type="GDScript" id=1]\n'
        'script/source = "extends Node\nvar title = \\"Not UI text here\\"\n"\n'
        'icon = "res://icons/save.png"\n'
    ))
    assert "Pause Menu" in texts
    assert any(t.startswith("An old, slightly rusted sword.") for t in texts)
    assert not any("Not UI text" in t or "res://" in t for t in texts)
