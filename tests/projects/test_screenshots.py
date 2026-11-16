"""Screenshot path resolution tests."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.projects.paths import is_under_root
from llm_localizator.projects.screenshots import resolve_screenshot_path


def test_resolve_by_screen_id(tmp_path: Path) -> None:
    shots = tmp_path / "screenshots"
    shots.mkdir()
    (shots / "add-locale-modal.png").write_bytes(b"\x89PNG")
    assert resolve_screenshot_path(tmp_path, screen="add-locale-modal") is not None


def test_resolve_by_explicit_image(tmp_path: Path) -> None:
    (tmp_path / "custom.png").write_bytes(b"\x89PNG")
    path = resolve_screenshot_path(tmp_path, image="custom.png")
    assert path is not None
    assert path.name == "custom.png"


def test_screen_id_without_file_returns_none(tmp_path: Path) -> None:
    assert resolve_screenshot_path(tmp_path, screen="missing") is None


def test_locale_prefixed_preferred_over_generic(tmp_path: Path) -> None:
    shots = tmp_path / "screenshots"
    shots.mkdir()
    (shots / "home.png").write_bytes(b"generic")
    (shots / "pl__home.png").write_bytes(b"locale")
    path = resolve_screenshot_path(tmp_path, screen="home", locale="pl")
    assert path is not None
    assert path.name == "pl__home.png"


def test_locale_falls_back_to_generic(tmp_path: Path) -> None:
    shots = tmp_path / "screenshots"
    shots.mkdir()
    (shots / "home.png").write_bytes(b"generic")
    path = resolve_screenshot_path(tmp_path, screen="home", locale="ar")
    assert path is not None
    assert path.name == "home.png"


def test_is_under_root_accepts_child(tmp_path: Path) -> None:
    root = tmp_path / "context"
    root.mkdir()
    child = root / "screenshots" / "a.png"
    child.parent.mkdir()
    child.write_bytes(b"x")
    assert is_under_root(child, root)


def test_is_under_root_rejects_sibling_prefix(tmp_path: Path) -> None:
    root = tmp_path / "context"
    root.mkdir()
    evil = tmp_path / "context_evil"
    evil.mkdir()
    target = evil / "secret.png"
    target.write_bytes(b"x")
    assert not is_under_root(target, root)
    assert resolve_screenshot_path(root, image="../context_evil/secret.png") is None


def test_is_under_root_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "context"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    assert not is_under_root(outside, root)
    assert resolve_screenshot_path(root, image="../outside.png") is None
