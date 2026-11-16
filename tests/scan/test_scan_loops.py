"""Scanner.scan and agent-hardcoded share one per-file routine (M2: they used to differ on t_functions, paths,
directives and duplicates)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.agent_hardcoded import _scan_files
from llm_localizator.scan import build_scanner

_PY = (
    'def view():\n'
    '    show("Please sign in to continue")\n'
    '    tr_text("Already routed by a project wrapper")\n'
    '    notice("Hidden on purpose by a directive")  # l10n-ignore\n'
)


def _scanner(root: Path):
    scanner = build_scanner("source", root, ["src"], t_functions=["tr_text"])
    return scanner


def _project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "views.py").write_text(_PY, encoding="utf-8")
    return tmp_path


def _texts(result) -> list[tuple[str, int, str]]:
    return sorted((h.file, h.line, h.text) for h in result.hardcoded)


def test_both_loops_report_the_same_hits(tmp_path: Path) -> None:
    root = _project(tmp_path)
    direct = _scanner(root).scan()
    via_agent, _ = _scan_files(_scanner(root), None)
    assert _texts(direct) == _texts(via_agent)
    texts = {t for _, _, t in _texts(direct)}
    assert "Please sign in to continue" in texts
    assert "Already routed by a project wrapper" not in texts   # t_functions honoured in both loops
    assert "Hidden on purpose by a directive" not in texts
    assert direct.suppressed == via_agent.suppressed == 1
    assert all(not Path(h.file).is_absolute() for h in via_agent.hardcoded)


def test_per_file_cache_reuses_the_same_hits(tmp_path: Path) -> None:
    root = _project(tmp_path)
    store: dict = {}
    first, _ = _scan_files(_scanner(root), None, store)
    second, _ = _scan_files(_scanner(root), None, store)
    assert _texts(first) == _texts(second)
    assert first.suppressed == second.suppressed == 1
