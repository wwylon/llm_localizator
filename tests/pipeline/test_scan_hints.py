from __future__ import annotations

import json

from llm_localizator.pipeline.context_assembler import assemble_context
from llm_localizator.scan.usage_hints import load_usage_hints


def test_hints_read_components(tmp_path) -> None:
    (tmp_path / "ui.json").write_text(json.dumps({
        "save": [{"file": "a/Form.tsx", "line": 3, "component": "Form"},
                 {"file": "b/Bar.tsx", "line": 1, "component": ""}],
        "bad": "x",
    }), encoding="utf-8")
    hints = load_usage_hints(tmp_path, "ui")
    assert hints == {"save": "used in Form, Bar"}


def test_hints_missing_or_corrupt(tmp_path) -> None:
    assert load_usage_hints(None, "ui") == {}
    assert load_usage_hints(tmp_path, "ui") == {}
    (tmp_path / "ui.json").write_text("{nope", encoding="utf-8")
    assert load_usage_hints(tmp_path, "ui") == {}


def test_trace_entry_only_when_hint() -> None:
    kw = dict(source="Save", locale="pl", namespace="ui", key="save")
    assert not [t for t in assemble_context(**kw).trace if t.startswith("scan:")]
    pkg = assemble_context(**kw, scan_hint="used in Form")
    assert "scan:used in Form" in pkg.trace
