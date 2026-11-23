"""Per-scan facts from the project's side files (M3, audit D5).

Some hits depend on files that are never scanned: the root ``go.mod`` (is this a CLI or a terminal-UI project?),
Apple string catalogues and the Xcode project (is this ``Text("…")`` key translated for the file's target?) and
``Info.plist``. One ``ProjectIndex`` per scan holds them; it lives on the scanner and ``Scanner.reset_tree`` drops it,
so a long-lived scanner (web server, watch) never keeps the first scan's facts. Each part is read on first use: a
scan with no Go or Swift file reads nothing.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .apple_index import CATALOGUE_SKIP_DIRS, DEFAULT_TABLES, read_pbxproj, strings_keys

__all__ = ["ProjectIndex", "project_index"]

#: CLI frameworks: in a project that requires one, what it prints is its UI (B3, B23).
GO_CLI_LIBS = ("github.com/spf13/cobra", "github.com/urfave/cli", "github.com/alecthomas/kong")
#: Terminal UI frameworks: in a project that requires one, prose literals are screen copy (pool D: lazymake, grofer).
GO_TUI_LIBS = ("github.com/charmbracelet/bubbletea", "github.com/rivo/tview", "github.com/gizak/termui",
               "github.com/jroimartin/gocui", "github.com/awesome-gocui/gocui", "github.com/gdamore/tcell")

_ATTR = "_project_index"
_PY_GUI_DEP = re.compile(r"(?im)^\s*[\"']?(?:PyQt[4-6]|PySide[2-6]|wxPython|customtkinter|ttkbootstrap|kivy|toga|flet)\b")
_PY_GUI_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:tkinter|Tkinter|customtkinter|PyQt[4-6]|PySide[2-6]|wx|kivy|toga|flet|qt|slicer|ctk)\b", re.M,
)


class ProjectIndex:
    """Side-file facts for one project root, each read once."""

    def __init__(self, root) -> None:
        self.root = Path(root) if root else None
        self._go: tuple[bool, bool] | None = None
        self._py_gui: bool | None = None
        self._walked = False
        self._apple_keys: frozenset[str] = frozenset()
        self._apple_sources: dict[str, set[str]] = {}
        self._apple_targets: set[str] = set()
        self._info_plists: list[Path] = []

    # ------------------------------------------------------------ Python desktop GUI
    @property
    def py_gui(self) -> bool:
        """The project is a Python desktop GUI app: it depends on, or its top modules import, Tk, Qt, wx, Kivy or Toga.

        Exception messages and label tables are screen copy there (a worker thread's error ends up in a dialog).
        """
        if self._py_gui is None:
            self._py_gui = self._detect_py_gui()
        return self._py_gui

    def _detect_py_gui(self) -> bool:
        if not self.root or not self.root.is_dir():
            return False
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "environment.yml"):
            try:
                text = (self.root / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _PY_GUI_DEP.search(text):
                return True
        # Three shallow listings, not a second tree walk: the scan walks the tree once.
        seen = 0
        for pattern in ("*.py", "*/*.py", "*/*/*.py"):
            for path in self.root.glob(pattern):
                if any(part in CATALOGUE_SKIP_DIRS or part.startswith(".") for part in path.relative_to(self.root).parts[:-1]):
                    continue
                seen += 1
                if seen > 300:
                    return False
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        head = fh.read(6000)
                except OSError:
                    continue
                if _PY_GUI_IMPORT.search(head):
                    return True
        return False

    # ------------------------------------------------------------ Go
    def _read_go(self) -> tuple[bool, bool]:
        if self._go is None:
            mod = self.root / "go.mod" if self.root else None
            try:
                text = mod.read_text(encoding="utf-8", errors="replace") if mod and mod.is_file() else ""
            except OSError:
                text = ""
            self._go = (any(lib in text for lib in GO_CLI_LIBS), any(lib in text for lib in GO_TUI_LIBS))
        return self._go

    @property
    def go_cli(self) -> bool:
        """The root ``go.mod`` requires a CLI framework: its error strings end up in a terminal."""
        return self._read_go()[0]

    @property
    def go_tui(self) -> bool:
        """The root ``go.mod`` requires a terminal UI framework."""
        return self._read_go()[1]

    # ------------------------------------------------------------ one walk: catalogues, pbxproj, Info.plist
    def _walk(self) -> None:
        if self._walked:
            return
        self._walked = True
        keys: set[str] = set()
        sources: dict[str, set[str]] = {}       # Swift file name -> targets that compile it
        resources: dict[str, set[str]] = {}     # resource file name -> targets that ship it
        seen_pbx = False
        for dirpath, dirnames, filenames in os.walk(self.root) if self.root else ():
            dirnames[:] = [d for d in dirnames if d not in CATALOGUE_SKIP_DIRS]
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    if name == "Localizable.strings":
                        with open(path, encoding="utf-8", errors="replace") as fh:
                            keys.update(strings_keys(fh.read()))
                    elif name == "Localizable.xcstrings":
                        with open(path, encoding="utf-8") as fh:
                            keys.update(json.load(fh).get("strings", {}))
                    elif name == "project.pbxproj":
                        with open(path, encoding="utf-8", errors="replace") as fh:
                            read_pbxproj(fh.read(), sources, resources)
                        seen_pbx = True
                    elif name == "Info.plist":
                        self._info_plists.append(Path(path))
                except (OSError, ValueError, AttributeError):
                    continue
        self._apple_keys = frozenset(keys)
        self._apple_sources = sources if seen_pbx else {}
        self._apple_targets = set().union(*(resources.get(t, set()) for t in DEFAULT_TABLES))

    @property
    def apple_keys(self) -> frozenset[str]:
        """Keys of the default-table catalogues (``Localizable.strings`` / ``.xcstrings``)."""
        self._walk()
        return self._apple_keys

    @property
    def apple_sources(self) -> dict[str, set[str]]:
        """Swift file name -> the Xcode targets that compile it (empty without a ``project.pbxproj``)."""
        self._walk()
        return self._apple_sources

    @property
    def apple_catalogue_targets(self) -> set[str]:
        """Targets that ship a default-table catalogue."""
        self._walk()
        return self._apple_targets

    @property
    def info_plists(self) -> list[Path]:
        """Every ``Info.plist`` under the root (same pruned walk)."""
        self._walk()
        return self._info_plists


def project_index(scanner) -> ProjectIndex:
    """The scanner's index for this scan (built on first use; a scanner without ``__dict__`` gets a fresh one)."""
    cache = getattr(scanner, "__dict__", None)
    if cache is None:
        return ProjectIndex(getattr(scanner, "root", None))
    index = cache.get(_ATTR)
    if index is None:
        index = cache[_ATTR] = ProjectIndex(getattr(scanner, "root", None))
    return index
