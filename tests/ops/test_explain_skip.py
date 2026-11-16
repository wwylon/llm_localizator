from pathlib import Path

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.explain_skip import explain_key


def test_explain_key_reports_skip_keys(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path, skip_keys={"brand"})
    row = explain_key(cfg, "app", "brand", "Brand")
    assert row["skipped"] is True
    assert "skip_keys" in row["reasons"]


def test_explain_skip_op(tmp_path, make_config, make_catalog) -> None:
    cfg = make_config(tmp_path, skip_keys={"brand"})
    cat = make_catalog(cfg)
    cat.save(cfg.source_locale, "app", {"brand": "Brand", "hello": "Hello"})
    out = dispatch_op(
        cfg, "explain-skip", {"namespace": "app", "limit": 10}, actor_role="Admin",
    )
    assert out["ok"]
    keys = {r["key"] for r in out["data"]["rows"]}
    assert "brand" in keys
