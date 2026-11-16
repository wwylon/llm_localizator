"""Android layouts are scanned; other XML (pom.xml, res/values/strings.xml) is not."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import build_scanner


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_android_layout_attributes(tmp_path: Path) -> None:
    _write(tmp_path, "app/src/main/res/layout/activity_main.xml", (
        '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '  <TextView android:id="@+id/title" android:text="Welcome back to the app" />\n'
        '  <Button android:text="@string/save" android:contentDescription="Save your changes now" />\n'
        '  <EditText android:hint="Search by name" android:inputType="text" />\n'
        '</LinearLayout>\n'
    ))
    _write(tmp_path, "app/src/main/res/values/strings.xml", '<resources><string name="save">Save the file now</string></resources>\n')
    _write(tmp_path, "pom.xml", '<project><name>Sign in to continue please</name></project>\n')
    hits = build_scanner("source", tmp_path, ["app", "."]).scan().hardcoded
    texts = {h.text for h in hits}
    assert {"Welcome back to the app", "Save your changes now", "Search by name"} <= texts
    assert "Save the file now" not in texts          # the project's own catalogue
    assert "Sign in to continue please" not in texts  # not a UI definition
    assert not any("@string" in t or "@+id" in t for t in texts)
