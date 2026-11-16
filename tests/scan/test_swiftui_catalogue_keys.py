"""SwiftUI literals whose exact key the project's catalogue translates are routed (ADR-150, B6)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.scan import build_scanner

_VIEW = '''import SwiftUI

struct BuildView: View {
    var body: some View {
        VStack {
            Text("Loading Photos...")
            Button("Start Search") { start() }
            Text("Build finished without errors.")
            Text(verbatim: "Plain debug text here")
        }
        .navigationTitle("Index Photos")
    }
}
'''


def _hits(tmp_path: Path, catalogue: str | None, xc: dict | None = None) -> set[str]:
    src = tmp_path / "App"
    src.mkdir()
    (src / "BuildView.swift").write_text(_VIEW, encoding="utf-8")
    if catalogue is not None:
        lproj = src / "de.lproj"
        lproj.mkdir()
        (lproj / "Localizable.strings").write_text(catalogue, encoding="utf-8")
    if xc is not None:
        (src / "Localizable.xcstrings").write_text(json.dumps(xc), encoding="utf-8")
    return {h.text for h in build_scanner("source", tmp_path, ["App"]).scan().hardcoded if h.confidence != "low"}


def test_translated_keys_are_routed(tmp_path: Path) -> None:
    hits = _hits(tmp_path, '"Loading Photos..." = "Fotos werden geladen...";\n"Index Photos" = "Fotos indizieren";\n',
                 {"sourceLanguage": "en", "strings": {"Start Search": {}}})
    assert "Loading Photos..." not in hits
    assert "Index Photos" not in hits
    assert "Start Search" not in hits
    assert "Build finished without errors." in hits   # no catalogue entry: still hardcoded


def test_without_catalogue_everything_is_reported(tmp_path: Path) -> None:
    hits = _hits(tmp_path, None)
    assert {"Loading Photos...", "Start Search", "Build finished without errors."} <= hits


_PBXPROJ = """// !$*UTF8*$!
{
	objects = {
		AAAAAAAAAAAAAAAAAAAAAA01 /* BuildView.swift in Sources */ = {isa = PBXBuildFile; fileRef = AAAAAAAAAAAAAAAAAAAAAA11 /* BuildView.swift */; };
		AAAAAAAAAAAAAAAAAAAAAA02 /* WidgetView.swift in Sources */ = {isa = PBXBuildFile; fileRef = AAAAAAAAAAAAAAAAAAAAAA12 /* WidgetView.swift */; };
		AAAAAAAAAAAAAAAAAAAAAA03 /* Localizable.strings in Resources */ = {isa = PBXBuildFile; fileRef = AAAAAAAAAAAAAAAAAAAAAA13 /* Localizable.strings */; };
		AAAAAAAAAAAAAAAAAAAAAA21 /* Sources */ = {
			isa = PBXSourcesBuildPhase;
			files = (
				AAAAAAAAAAAAAAAAAAAAAA01 /* BuildView.swift in Sources */,
			);
		};
		AAAAAAAAAAAAAAAAAAAAAA22 /* Resources */ = {
			isa = PBXResourcesBuildPhase;
			files = (
				AAAAAAAAAAAAAAAAAAAAAA03 /* Localizable.strings in Resources */,
			);
		};
		AAAAAAAAAAAAAAAAAAAAAA23 /* Sources */ = {
			isa = PBXSourcesBuildPhase;
			files = (
				AAAAAAAAAAAAAAAAAAAAAA02 /* WidgetView.swift in Sources */,
			);
		};
		AAAAAAAAAAAAAAAAAAAAAA31 /* App */ = {
			isa = PBXNativeTarget;
			buildPhases = (
				AAAAAAAAAAAAAAAAAAAAAA21 /* Sources */,
				AAAAAAAAAAAAAAAAAAAAAA22 /* Resources */,
			);
		};
		AAAAAAAAAAAAAAAAAAAAAA32 /* Widget */ = {
			isa = PBXNativeTarget;
			buildPhases = (
				AAAAAAAAAAAAAAAAAAAAAA23 /* Sources */,
			);
		};
	};
}
"""


def test_key_counts_only_in_a_target_that_ships_the_catalogue(tmp_path: Path) -> None:
    """The widget target does not ship Localizable.strings, so its Text("Loading Photos...") is not translated (B20)."""
    src = tmp_path / "App"
    src.mkdir()
    (src / "BuildView.swift").write_text('import SwiftUI\nlet a = Text("Loading Photos...")\n', encoding="utf-8")
    (src / "WidgetView.swift").write_text('import SwiftUI\nlet b = Text("Loading Photos...")\n', encoding="utf-8")
    lproj = src / "en.lproj"
    lproj.mkdir()
    (lproj / "Localizable.strings").write_text('"Loading Photos..." = "Loading Photos...";\n', encoding="utf-8")
    proj = tmp_path / "App" / "App.xcodeproj"
    proj.mkdir()
    (proj / "project.pbxproj").write_text(_PBXPROJ, encoding="utf-8")
    hits = build_scanner("source", tmp_path, ["App"]).scan().hardcoded
    files = {h.file.rsplit("/", 1)[-1] for h in hits if h.text == "Loading Photos..." and h.confidence != "low"}
    assert files == {"WidgetView.swift"}


def test_file_shared_with_a_widget_is_still_reported(tmp_path: Path) -> None:
    """Compiled into the app (which ships Localizable) and the widget (which does not): the widget shows it untranslated."""
    shared = _PBXPROJ.replace(
        "\t\tAAAAAAAAAAAAAAAAAAAAAA03 /* Localizable.strings in Resources */",
        "\t\tAAAAAAAAAAAAAAAAAAAAAA04 /* WidgetView.swift in Sources */ = {isa = PBXBuildFile; fileRef = "
        "AAAAAAAAAAAAAAAAAAAAAA12 /* WidgetView.swift */; };\n"
        "\t\tAAAAAAAAAAAAAAAAAAAAAA03 /* Localizable.strings in Resources */",
    ).replace(
        "\t\t\t\tAAAAAAAAAAAAAAAAAAAAAA01 /* BuildView.swift in Sources */,\n",
        "\t\t\t\tAAAAAAAAAAAAAAAAAAAAAA01 /* BuildView.swift in Sources */,\n"
        "\t\t\t\tAAAAAAAAAAAAAAAAAAAAAA04 /* WidgetView.swift in Sources */,\n",
    )
    assert shared != _PBXPROJ
    src = tmp_path / "App"
    src.mkdir()
    (src / "WidgetView.swift").write_text('import SwiftUI\nlet b = Text("Loading Photos...")\n', encoding="utf-8")
    lproj = src / "en.lproj"
    lproj.mkdir()
    (lproj / "Localizable.strings").write_text('"Loading Photos..." = "Loading Photos...";\n', encoding="utf-8")
    proj = src / "App.xcodeproj"
    proj.mkdir()
    (proj / "project.pbxproj").write_text(shared, encoding="utf-8")
    hits = build_scanner("source", tmp_path, ["App"]).scan().hardcoded
    assert any(h.text == "Loading Photos..." and h.confidence != "low" for h in hits)
