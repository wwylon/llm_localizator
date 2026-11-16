"""One tree walk per scan must yield the same files, in the same order, as the globs."""

from __future__ import annotations

from llm_localizator.core.languages import literal_languages, source_languages
from llm_localizator.scan import SourceScanner
from llm_localizator.scan.base import SKIP_DIR_PARTS, path_is_skipped
from llm_localizator.scan.literals import _literal_paths, scan_unseen_literals


def _old_paths(scanner, exts, skip_names=()):
    for rel in scanner.src_dirs:
        base = scanner.root / rel
        if not base.is_dir():
            continue
        for ext in exts:
            for path in sorted(base.glob(f"**/*{ext}")):
                if path.name in skip_names:
                    continue
                if path_is_skipped(path, exclude=scanner.exclude, unskip=scanner.unskip):
                    continue
                yield path


def _make_tree(root):
    names = [
        "src/a/A.tsx", "src/a/b/B.ts", "src/a/c.py", "src/a/i18n.js", "src/x/main.go",
        "src/x/page.html", "src/x/app.js", "src/x/app.test.js", "src/docs/D.tsx",
        "src/scripts/s.py", "src/node_modules/m/M.js", "src/.hidden/H.tsx",
        "src/build/o.js", "lib/L.py", "lib/deep/er/E.tsx", "src/features/designSystem.tsx",
        "src/features/design/D.tsx", "src/readme.py", "src/types.d.ts",
    ]
    for name in names:
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n", encoding="utf-8")


def test_single_walk_matches_globs(tmp_path) -> None:
    _make_tree(tmp_path)
    scanner = SourceScanner(
        tmp_path, ["src", "lib", "missing"], exclude=["features/design"], unskip=["src/scripts"],
    )
    exts = [e for lang in source_languages() for e in lang.extensions]
    assert list(scanner.iter_files()) == list(_old_paths(scanner, exts, ("i18n.js",)))
    lit = [e for lang in literal_languages() for e in lang.extensions]
    assert list(_literal_paths(scanner)) == list(_old_paths(scanner, lit))
    got = {p.relative_to(tmp_path).as_posix() for p in scanner.iter_files()}
    assert "src/features/designSystem.tsx" in got
    assert "src/features/design/D.tsx" not in got
    assert "src/scripts/s.py" in got
    assert not any(part in SKIP_DIR_PARTS for p in got for part in p.split("/"))


def test_scan_walks_once(tmp_path, monkeypatch) -> None:
    import llm_localizator.scan.base as base

    _make_tree(tmp_path)
    calls = []
    real = base.os.walk
    monkeypatch.setattr(base.os, "walk", lambda *a, **k: calls.append(a) or real(*a, **k))
    scanner = SourceScanner(tmp_path, ["src", "lib"])
    scanner.scan()
    assert len(calls) == 2  # one per src dir, not per extension or pass
    scan_unseen_literals(scanner, scanner.scan(), set())
    assert len(calls) == 4  # scan() resets; the extra literal pass reuses the walk


def test_iter_files_uses_pruned_walk_not_recursive_glob(tmp_path, monkeypatch) -> None:
    """The default iter_files must match the old glob result without a recursive glob."""
    from pathlib import Path

    from llm_localizator.scan import NextIntlScanner

    root = tmp_path
    for name in ("src/A.tsx", "src/deep/B.tsx", "src/node_modules/x/C.tsx", "src/D.ts"):
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    expected = sorted(
        p for p in (root / "src").glob("**/*.tsx")
        if not path_is_skipped(p, root=root)
    )

    def boom(self, pattern):
        raise AssertionError("recursive glob used")

    scanner = NextIntlScanner(root, ["src"])
    monkeypatch.setattr(Path, "glob", boom)
    assert list(scanner.iter_files()) == expected
