"""v69: formatted messages in a desktop GUI project are screen text; the same f-strings in logs and code are not."""

from __future__ import annotations

from llm_localizator.scan.py_sinks import server_strings

SOURCE = '''
import logging
import tkinter as tk

log = logging.getLogger(__name__)

def run(self, name, n):
    self.status.set(f"Chapters ({n})")
    messagebox.showerror("Error", f"Error: {name}")
    log.info(f"Loading project {name}")
    print(f"Output: {name}")
    url = f"https://example.com/{name}"
    query = f"SELECT * FROM books WHERE id = {n}"
    path = f"{name}/cover.png"
    key = f"item_{n}"
'''


def _texts(gui: bool) -> set[str]:
    return {s.text for s in server_strings(SOURCE, gui_project=gui)}


def test_formatted_messages_are_found_in_a_gui_project() -> None:
    texts = _texts(True)
    assert any(t.startswith("Chapters") for t in texts)
    assert any(t.startswith("Error:") for t in texts)


def test_logs_urls_queries_and_paths_are_not() -> None:
    texts = " | ".join(_texts(True))
    for noise in ("Loading project", "Output:", "example.com", "SELECT", "cover.png", "item_"):
        assert noise not in texts


def test_nothing_is_added_outside_a_gui_project() -> None:
    assert not any(s.sink == "gui-fstring" for s in server_strings(SOURCE, gui_project=False))
