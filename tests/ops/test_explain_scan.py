"""explain-scan: why one line was or was not reported (M6, ADR-154)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.explain_scan import ExplainScanRequest, op_explain_scan
from llm_localizator.projects import load_config

_SOURCE = (
    'def f():\n'
    '    return "Please sign in now"\n'
    'x = t("Already routed text")\n'
    'name = "Bridge"\n'
    'y = "Ignored on purpose here"  # i18n-ignore\n'
)


def _project(tmp_path: Path) -> object:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(_SOURCE, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.py").write_text('msg = "Please sign in now"\n', encoding="utf-8")
    (tmp_path / ".llm-localize.toml").write_text(
        '[project]\nname = "ex"\n[scan]\nadapter = "source"\nsrc_dirs = ["src", "docs"]\n', encoding="utf-8",
    )
    return load_config(tmp_path / ".llm-localize.toml")


def test_reported_line_shows_the_hit(tmp_path: Path) -> None:
    result = op_explain_scan(_project(tmp_path), ExplainScanRequest(target="src/app.py:2"))
    assert result.ok
    assert [h["text"] for h in result.data["hits"]] == ["Please sign in now"]
    assert result.data["hits"][0]["state"] == "reported"


def test_routed_and_non_prose_literals_get_a_verdict(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    routed = op_explain_scan(cfg, ExplainScanRequest(target="src/app.py:3")).data["literals"]
    assert routed and "translation call" in routed[0]["verdict"]
    word = op_explain_scan(cfg, ExplainScanRequest(target="src/app.py:4")).data["literals"]
    assert word and "not prose" in word[0]["verdict"]


def test_skipped_folder_is_explained(tmp_path: Path) -> None:
    data = op_explain_scan(_project(tmp_path), ExplainScanRequest(target="docs/guide.py:1")).data
    assert data["steps"][-1]["step"] == "skip"
    assert not data["hits"]


def test_missing_file_and_empty_target(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    assert op_explain_scan(cfg, ExplainScanRequest(target="src/nope.py:1")).data["steps"][0]["verdict"] == "no such file"
    assert not op_explain_scan(cfg, ExplainScanRequest(target="")).ok


def test_web_dispatch_matches_cli(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    web = dispatch_op(cfg, "explain-scan", {"file": "src/app.py", "line": "2"}, actor_role="Translator")
    assert web["data"]["hits"][0]["text"] == "Please sign in now"
