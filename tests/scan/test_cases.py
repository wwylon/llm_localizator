"""Data-driven scanner cases harvested from the scanner bench (plan Part A, S3).

Each case is ``cases/<dir>/<name>.<ext>`` plus ``<name>.expect.json``::

    {"adapter": "source",
     "must_hit": [{"text": "Filter title", "min_conf": "medium"}],
     "must_not": ["btn-primary"],
     "xfail": "optional: known gap, cluster tag"}

``must_hit`` text matches a hit whose text equals or contains it (whitespace
collapsed). ``xfail`` is strict: once the scanner catches the case the test
fails until the marker is removed, so the backlog cannot rot.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from llm_localizator.scan import build_scanner

CASES = Path(__file__).parent / "cases"
_RANK = {"high": 0, "medium": 1, "low": 2}


def _cases() -> list[Path]:
    return sorted(CASES.rglob("*.expect.json"))


def _norm(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("expect_path", _cases(), ids=lambda p: p.relative_to(CASES).as_posix())
def test_case(expect_path: Path, tmp_path: Path, request) -> None:
    spec = json.loads(expect_path.read_text(encoding="utf-8"))
    stem = expect_path.name[: -len(".expect.json")]
    if spec.get("xfail"):
        request.applymarker(pytest.mark.xfail(reason=spec["xfail"], strict=True))
    folder = expect_path.parent / stem
    if folder.is_dir():
        # Multi-file case: the folder is the project root (go.mod, catalogues, an Xcode project next to the source).
        shutil.copytree(folder, tmp_path / "project")
        root, src_dirs = tmp_path / "project", list(spec.get("src_dirs", ["."]))
    else:
        sources = [p for p in expect_path.parent.glob(stem + ".*") if p != expect_path]
        assert len(sources) == 1, f"{expect_path}: expected one source file, got {sources}"
        src = tmp_path / "src"
        src.mkdir()
        shutil.copy(sources[0], src / sources[0].name)
        root, src_dirs = tmp_path, ["src"]
    scanner = build_scanner(spec.get("adapter", "source"), root, src_dirs)
    hits = scanner.scan().hardcoded

    missing = []
    for want in spec.get("must_hit", []):
        text = _norm(want["text"] if isinstance(want, dict) else want)
        floor = _RANK[(want.get("min_conf") if isinstance(want, dict) else None) or "medium"]
        if not any(text in _norm(h.text) and _RANK[h.confidence] <= floor for h in hits):
            missing.append(text)
    forbidden = {_norm(t) for t in spec.get("must_not", [])}
    false_pos = [f"{h.text!r}@{h.line}" for h in hits if _norm(h.text) in forbidden]
    got = sorted({f"[{h.confidence}] {h.text}" for h in hits})
    assert not missing and not false_pos, (
        f"missing={missing} false_positives={false_pos}\nhits={got}"
    )
