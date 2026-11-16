"""Store listing text present in the source locale but missing in other locales (M6, B22)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.catalog.store_metadata import store_metadata_gaps


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_changelogs_only_in_english_are_reported(tmp_path: Path) -> None:
    meta = tmp_path / "fastlane" / "metadata" / "android"
    for loc in ("en-US", "cs-CZ", "ro", "ru-RU"):
        _write(meta / loc / "full_description.txt")
        _write(meta / loc / "short_description.txt")
    _write(meta / "en-US" / "changelogs" / "14.txt", "Added language filter")
    _write(meta / "en-US" / "images" / "icon.png")
    gaps = store_metadata_gaps(tmp_path, "en")
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.folder == "fastlane/metadata/android" and gap.source == "en-US"
    assert gap.missing == {"changelogs/14.txt": ["cs-CZ", "ro", "ru-RU"]}


def test_fully_translated_listing_is_quiet(tmp_path: Path) -> None:
    meta = tmp_path / "fastlane" / "metadata"
    for loc in ("en-US", "de-DE"):
        _write(meta / loc / "description.txt")
    assert store_metadata_gaps(tmp_path, "en") == []


def test_no_fastlane_folder(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.py")
    assert store_metadata_gaps(tmp_path, "en") == []
