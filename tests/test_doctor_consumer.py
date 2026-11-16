"""doctor's consumer checks (P5)."""

from __future__ import annotations

from llm_localizator.doctor import consumer_checks
from llm_localizator.projects.qa_config import QaConfig


def test_consumer_checks(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    names = {c.name: c.status for c in consumer_checks(cfg)}
    assert names == {"approach": "warn"}
    cfg.translate_approach = "local"
    cfg.web_runtime_path = "web/js"
    cfg.qa = QaConfig(base_url="http://127.0.0.1:9")
    checks = {c.name: c for c in consumer_checks(cfg)}
    assert "approach" not in checks
    assert checks["runtime"].status == "warn" and "not installed" in checks["runtime"].detail
    assert checks["qa"].status == "warn" and "not running" in checks["qa"].detail
