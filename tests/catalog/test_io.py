"""Tests for catalog I/O helpers."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from llm_localizator.catalog.io import atomic_write_text


def test_atomic_write_text_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "ko.json"
    atomic_write_text(target, '{"ok": true}\n')
    assert target.read_text(encoding="utf-8") == '{"ok": true}\n'


def test_atomic_write_text_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "ko.json"
    target.write_text("old\n", encoding="utf-8")
    atomic_write_text(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"


def test_atomic_write_text_retries_replace_on_access_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "ko.json"
    target.write_text("old\n", encoding="utf-8")
    calls = {"n": 0}
    real_replace = __import__("os").replace

    def flaky_replace(src: str, dst: str | bytes) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "Permission denied", src, dst, 5)
        real_replace(src, dst)

    monkeypatch.setattr("llm_localizator.catalog.io.os.replace", flaky_replace)
    monkeypatch.setattr("llm_localizator.catalog.io.time.sleep", lambda _s: None)

    atomic_write_text(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert calls["n"] == 3


def test_atomic_write_text_raises_after_replace_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "ko.json"

    def always_denied(_src: str, _dst: str | bytes) -> None:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr("llm_localizator.catalog.io.os.replace", always_denied)
    monkeypatch.setattr("llm_localizator.catalog.io.time.sleep", lambda _s: None)

    with pytest.raises(OSError, match="Permission denied"):
        atomic_write_text(target, "new\n")

    assert not target.exists()
    leftovers = list(tmp_path.glob(".*"))
    assert leftovers == []
