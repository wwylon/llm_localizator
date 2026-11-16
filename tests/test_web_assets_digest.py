"""ui_source digest follows per-file mtimes, not the directory mtime."""

from __future__ import annotations

import os

from llm_localizator.doctor import ui_digest
from llm_localizator.web.assets import ui_source


def test_in_place_edit_changes_the_digest(tmp_path) -> None:
    (tmp_path / "a.js").write_text("one", encoding="utf-8")
    first = ui_digest(ui_source(tmp_path))
    dir_mtime = tmp_path.stat().st_mtime_ns
    (tmp_path / "a.js").write_text("two", encoding="utf-8")
    stamp = (tmp_path / "a.js").stat().st_mtime_ns + 5_000_000_000
    os.utime(tmp_path / "a.js", ns=(stamp, stamp))
    os.utime(tmp_path, ns=(dir_mtime, dir_mtime))  # directory mtime unchanged
    assert ui_digest(ui_source(tmp_path)) != first


def test_unchanged_files_reuse_the_cached_text(tmp_path, monkeypatch) -> None:
    (tmp_path / "a.js").write_text("one", encoding="utf-8")
    ui_source(tmp_path)
    reads = []
    real = type(tmp_path).read_text
    monkeypatch.setattr(type(tmp_path), "read_text", lambda s, *a, **k: reads.append(s) or real(s, *a, **k))
    ui_source(tmp_path)
    assert reads == []
