"""v67: captions passed to Jinja macros, Java display-name methods, Slicer-style Qt modules."""

from __future__ import annotations

from llm_localizator.scan.py_sinks import server_strings
from llm_localizator.scan.source import SourceScanner

HTML = """<div class="input-row">
  {{ web_input("login-password", placeholder="Password", type="password") }}
  {{ web_button("login-button", "Login", variant="accent", icon_url=asset_urls.icons.check) }}
  <img src="{{ url_for('static', filename='logo.png') }}">
  {{ include("partials/Header.html") }}
</div>
"""

JAVA = """package app;

public class PositionConverter extends StringConverter<Pos> {
    @Override
    public String toString(Pos object) {
        if (object.equals(Pos.TOP_RIGHT)) {
            return "Top Right";
        }
        return "Center";
    }

    public String helper() {
        return "Not shown";
    }
}
"""

SLICER = '''
import qt
import slicer

class Home:
    def go(self):
        reply = qt.QMessageBox.question(slicer.util.mainWindow(), "Initialize Confirmation", "Create a new database?")
        self.status_label.setText("Waiting for the device")
        raise UpdateCheckError("GitHub returned malformed release information.")
'''


def test_macro_captions_are_found_but_ids_and_paths_are_not(tmp_path) -> None:
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "login.html").write_text(HTML, encoding="utf-8")
    texts = {h.text for h in SourceScanner(tmp_path, ["."]).scan().hardcoded}
    assert {"Password", "Login"} <= texts
    assert not any("login-button" in t or "logo.png" in t or "Header.html" in t for t in texts)


def test_java_display_name_methods_return_ui_text_but_other_methods_do_not(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "PositionConverter.java").write_text(JAVA, encoding="utf-8")
    texts = {h.text for h in SourceScanner(tmp_path, ["."]).scan().hardcoded if h.confidence in ("high", "medium")}
    assert {"Top Right", "Center"} <= texts
    assert "Not shown" not in texts


def test_a_slicer_style_qt_module_is_a_gui_module() -> None:
    texts = {s.text for s in server_strings(SLICER, gui_project=True)}
    assert {"Initialize Confirmation", "Create a new database?", "Waiting for the device"} <= texts
    assert "GitHub returned malformed release information." in texts
