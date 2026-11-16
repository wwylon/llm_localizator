"""C-016: ad hoc quality report."""

from __future__ import annotations

import json

from llm_localizator.ops.quality import op_quality
from llm_localizator.ops.types import QualityRequest


def _write(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"hello": "Hello {name}", "bye": "Bye"}), encoding="utf-8")
    (tmp_path / "de.json").write_text(json.dumps({"hello": "Hallo", "bye": "Tschüss"}), encoding="utf-8")


def test_adhoc_report_flags_missing_placeholder(tmp_path):
    _write(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    res = op_quality(None, QualityRequest(
        root=str(tmp_path), path_template="{locale}.json", source="en", targets=["de"],
    ))
    assert res.data["findings"], res.lines
    assert "de" in res.data["perLocale"]
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # nothing written next to the files


def test_adhoc_needs_source_and_target(tmp_path):
    res = op_quality(None, QualityRequest(root=str(tmp_path), path_template="{locale}.json"))
    assert not res.ok and "--source" in res.summary
    res = op_quality(None, QualityRequest(root=str(tmp_path), path_template="x.json", source="en", targets=["de"]))
    assert not res.ok and "{locale}" in res.summary


def test_no_project_no_template(tmp_path):
    res = op_quality(None, QualityRequest())
    assert not res.ok
