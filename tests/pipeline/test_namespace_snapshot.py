"""Wave 1: screen/peer indexes are O(n) per namespace, not O(n²) per key."""

from __future__ import annotations

from llm_localizator.pipeline._shared import build_namespace_snapshot
from llm_localizator.projects.context import ContextNotes


class _FakeCatalog:
    def __init__(self, source, target):
        self._source = source
        self._target = target

    def load(self, locale, namespace):
        return dict(self._source if locale == "en" else self._target)


def test_build_namespace_snapshot_indexes_siblings(tmp_path, make_config) -> None:
    source = {f"k{i}": f"Hello {i}" for i in range(40)}
    target = {f"k{i}": f"Witaj {i}" for i in range(40)}
    notes_dir = tmp_path / "context"
    notes_dir.mkdir()
    # One shared screen for every key.
    (notes_dir / "app.json").write_text(
        __import__("json").dumps({f"k{i}": {"screen": "home"} for i in range(40)}),
        encoding="utf-8",
    )
    cfg = make_config(tmp_path, context_dir=notes_dir)
    notes = ContextNotes(notes_dir)
    snap = build_namespace_snapshot(
        cfg, _FakeCatalog(source, target), notes, "pl", "app",
    )
    assert "home" in snap.siblings_by_screen
    assert len(snap.siblings_by_screen["home"]) == 12
    assert snap.source["k0"] == "Hello 0"
