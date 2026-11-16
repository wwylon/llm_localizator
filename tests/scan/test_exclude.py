"""Scan exclude path substrings (T-07)."""

from __future__ import annotations

from llm_localizator.scan.base import Scanner, ScanResult


class _Dummy(Scanner):
    @property
    def file_glob(self) -> str:
        return "**/*.tsx"

    def scan_file(self, path, lines, result: ScanResult) -> None:
        result.files_scanned += 0  # noqa: B018 — counted in scan()


def test_scan_exclude_skips_matching_paths(tmp_path) -> None:
    root = tmp_path
    keep = root / "apps" / "web" / "features" / "clubs" / "A.tsx"
    skip = root / "apps" / "web" / "features" / "design" / "DesignDirections.tsx"
    keep.parent.mkdir(parents=True)
    skip.parent.mkdir(parents=True)
    keep.write_text("export const X = () => <p>Hello</p>\n", encoding="utf-8")
    skip.write_text("export const Y = () => <p>Noise</p>\n", encoding="utf-8")

    scanner = _Dummy(
        root,
        ["apps/web/features"],
        exclude=["features/design"],
    )
    paths = [p.as_posix() for p in scanner.iter_files()]
    assert any("clubs" in p for p in paths)
    assert not any("design" in p for p in paths)


def test_exclude_and_unskip_match_whole_segments() -> None:
    from pathlib import Path

    from llm_localizator.scan.base import path_is_skipped

    keep = Path("apps/web/features/designSystem.tsx")
    assert not path_is_skipped(keep, exclude=("features/design",))
    assert path_is_skipped(Path("apps/web/features/design/A.tsx"), exclude=("features/design",))
    assert path_is_skipped(Path("apps/web/features/design.tsx"), exclude=("features/design.tsx",))
    # Substring inside a segment keeps working for a bare token that is a whole segment.
    assert path_is_skipped(Path("a/TranslateWorkspace/x.tsx"), exclude=("TranslateWorkspace",))
    # unskip must not match "docs" inside a longer segment.
    assert path_is_skipped(Path("a/docs/x.tsx"), unskip=("docsify",))
    assert not path_is_skipped(Path("a/docs/x.tsx"), unskip=("docs",))
    assert not path_is_skipped(Path("a/docs/x.tsx"), unskip=("a/docs",))
