"""``bakeoff --propose-config``: a snippet from the Winners table, never a config write (ADR-12)."""

from __future__ import annotations

from llm_localizator.ops.bakeoff import op_bakeoff
from llm_localizator.ops.types import BakeoffRequest
from llm_localizator.pipeline.bakeoff_report import parse_winners, propose_models_toml

REPORT = """# Quality bakeoff report

## Winners (consumer/chat) — ADR-12

| Locale | Winner | chat BT | Runner-up | Notes |
|--------|--------|---------|-----------|-------|
| pl | `aya-expanse:8b` | 0.936 | TG 0.920 | |
| pt-PT | `qwen2.5:7b` | 0.956 | aya 0.952 | |
| xx | `not a model` | 0.5 | none | |

## Later section
"""


def test_parse_winners_reads_rows() -> None:
    rows = parse_winners(REPORT)
    assert [r["locale"] for r in rows] == ["pl", "pt-PT", "xx"]
    assert rows[0]["winner"] == "aya-expanse:8b"


def test_proposal_marks_unchanged_skips_bad_tags_and_missing_locales() -> None:
    toml, notes = propose_models_toml(REPORT, ["pl", "pt-PT", "xx", "de"], {"pl": "aya-expanse:8b"})
    assert toml.startswith("[locales.models]\n")
    assert 'pl = "aya-expanse:8b"  # unchanged' in toml
    assert 'pt-PT = "qwen2.5:7b"' in toml
    assert "# pl runner-up: TG 0.920" in toml
    assert "xx" not in toml.split("# pl")[0]
    assert any("xx" in n for n in notes) and any("de: not in" in n for n in notes)


def test_op_prints_proposal_and_writes_nothing(project_root, make_config, tmp_path) -> None:
    cfg = make_config(project_root)
    (tmp_path / "REPORT.md").write_text(REPORT, encoding="utf-8")
    before = dict(cfg.models)
    result = op_bakeoff(cfg, BakeoffRequest(locales=["pl"], out=str(tmp_path), propose_config=True))
    assert result.ok
    assert 'pl = "aya-expanse:8b"' in result.data["toml"]
    assert "unchanged" in result.summary
    assert cfg.models == before


def test_op_refuses_without_report_or_winner(project_root, make_config, tmp_path) -> None:
    cfg = make_config(project_root)
    missing = op_bakeoff(cfg, BakeoffRequest(out=str(tmp_path), propose_config=True))
    assert not missing.ok and "no report" in missing.summary
    (tmp_path / "REPORT.md").write_text("# nothing\n", encoding="utf-8")
    bare = op_bakeoff(cfg, BakeoffRequest(out=str(tmp_path), propose_config=True))
    assert not bare.ok and "Winners" in bare.summary
