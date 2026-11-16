"""Apple string catalogues and Xcode targets: which SwiftUI keys are already translated (B20).

``Text("Save")`` is a ``LocalizedStringKey``: it is translated when ``Save`` is a key of a default-table catalogue
(``Localizable.strings`` / ``.xcstrings``) that every target compiling the file ships. The files are read once per
scan by ``project_index.ProjectIndex``; this module holds the parsing and the routing decision.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["SWIFTUI_KEYED", "apple_routed", "read_pbxproj", "strings_keys"]

#: SwiftUI initialisers and modifiers whose string-literal argument is a ``LocalizedStringKey`` (looked up at run time).
SWIFTUI_KEYED = frozenset({
    "Text", "Button", "Label", "Toggle", "Section", "Picker", "Link", "Menu", "Stepper", "TextField", "SecureField",
    "GroupBox", "DisclosureGroup", "NavigationLink", "TabItem", ".navigationTitle", ".navigationBarTitle", ".alert",
    ".confirmationDialog", ".help", ".badge", ".accessibilityLabel", ".accessibilityHint",
})
_STRINGS_KEY = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*=', re.M)
_UNESCAPE = re.compile(r"\\(.)")
CATALOGUE_SKIP_DIRS = {".git", "node_modules", "Pods", "build", "DerivedData", ".build", "Carthage"}

#: ``Text("…")`` and friends look up only the default table, ``Localizable`` (B20: not ``WidgetConfiguration.strings``).
DEFAULT_TABLES = ("Localizable.strings", "Localizable.xcstrings")
_PBX_BUILD_FILE = re.compile(r"(\w{24}) /\* (.+?) in (Resources|Sources) \*/ = \{isa = PBXBuildFile;")
_PBX_PHASE = re.compile(r"(\w{24}) /\* \w+ \*/ = \{\s*isa = PBX(?:Resources|Sources)BuildPhase;.*?files = \((.*?)\);", re.S)
_PBX_TARGET = re.compile(r"(\w{24}) /\* (.+?) \*/ = \{\s*isa = PBXNativeTarget;.*?buildPhases = \((.*?)\);", re.S)
_PBX_ID = re.compile(r"\b(\w{24})\b")


def strings_keys(text: str) -> list[str]:
    """Keys of one ``.strings`` file, unescaped."""
    return [_UNESCAPE.sub(r"\1", k) for k in _STRINGS_KEY.findall(text)]


def read_pbxproj(text: str, sources: dict[str, set[str]], resources: dict[str, set[str]]) -> None:
    """Which native targets compile which Swift files and ship which resources (names only)."""
    build_files = {m.group(1): (m.group(2), m.group(3)) for m in _PBX_BUILD_FILE.finditer(text)}
    phases = {m.group(1): _PBX_ID.findall(m.group(2)) for m in _PBX_PHASE.finditer(text)}
    for target in _PBX_TARGET.finditer(text):
        name = target.group(2)
        for phase_id in _PBX_ID.findall(target.group(3)):
            for bf in phases.get(phase_id, ()):
                if bf in build_files:
                    file_name, kind = build_files[bf]
                    (sources if kind == "Sources" else resources).setdefault(file_name, set()).add(name)


def apple_routed(scanner, rel: str, literal: str) -> bool:
    """``Text("…")`` in this Swift file is translated: the key is in a default-table catalogue the file's target ships."""
    from .project_index import project_index

    index = project_index(scanner)
    if literal not in index.apple_keys:
        return False
    targets = index.apple_sources.get(Path(rel).name)
    if not targets:
        return True  # no Xcode project, or a synchronized folder it does not list: trust the catalogue
    # Every target that compiles the file must ship the catalogue: a file shared by the app and a widget extension
    # is shown by the widget from its own bundle, which may not carry Localizable (dimeapp, B20).
    return targets <= index.apple_catalogue_targets
