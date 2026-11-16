"""Analytics op aggregation."""

from __future__ import annotations

import json

from llm_localizator.ops.analytics import op_analytics
from llm_localizator.ops.types import AnalyticsRequest


def test_op_analytics_text(project_root, make_config) -> None:
    cfg = make_config(project_root, state_dir=project_root / ".state")
    runs = cfg.state_root() / "_runs"
    runs.mkdir(parents=True)
    (runs / "r1.json").write_text(json.dumps({
        "run_id": "r1",
        "started_at": "2026-06-01T12:00:00Z",
        "command": "translate",
        "locales": ["pl"],
        "model": "testmodel",
        "wall_s": 40.0,
        "metrics": {"written": 4, "keys_per_s": 0.1},
    }), encoding="utf-8")

    result = op_analytics(cfg, AnalyticsRequest(run_command="translate", last=5))
    assert result.ok
    assert "0.1000 keys/s" in "\n".join(result.lines) or "0.1" in "\n".join(result.lines)


def test_op_analytics_json(project_root, make_config) -> None:
    cfg = make_config(project_root, state_dir=project_root / ".state")
    (cfg.state_root() / "_runs").mkdir(parents=True, exist_ok=True)

    result = op_analytics(cfg, AnalyticsRequest(fmt="json"))
    assert result.ok
    assert "runs" in result.data
    assert "lag" in result.data
