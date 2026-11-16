"""C-013: metrics --by activity report and CSV."""

from __future__ import annotations

from llm_localizator.catalog.translator_activity import append_activity
from llm_localizator.ops.metrics import activity_csv, csv_safe, op_metrics
from llm_localizator.ops.types import MetricsRequest

from tests.conftest import setup_project


def _seed(cfg):
    for user, loc, trig in [("ann", "pl", "web_edit"), ("ann", "pl", "translate"),
                            ("=cmd", "de", "web_edit")]:
        append_activity(cfg.state_root(), user_id=user, username=user, locale=loc,
                        namespace="app", key="a", trigger=trig)


def test_csv_safe():
    assert csv_safe("=1+1") == "'=1+1" and csv_safe("@x") == "'@x"
    assert csv_safe("-5") == "'-5" and csv_safe("ok") == "ok" and csv_safe(None) == ""


def test_by_variants(project_root, make_config):
    setup_project(project_root, {"a": "Hi"}, existing={"a": "Czesc"})
    cfg = make_config(project_root)
    _seed(cfg)
    by_user = op_metrics(cfg, MetricsRequest(by="user")).data["rows"]
    assert {r["user"]: r["edits"] for r in by_user} == {"ann": 2, "=cmd": 1}
    by_loc = op_metrics(cfg, MetricsRequest(by="locale")).data["rows"]
    assert {r["locale"]: r["edits"] for r in by_loc} == {"pl": 2, "de": 1}
    both = op_metrics(cfg, MetricsRequest(by="locale+user", locale="pl")).data["rows"]
    assert len(both) == 1 and both[0]["edits"] == 2


def test_csv_escapes_formula_users(project_root, make_config):
    setup_project(project_root, {"a": "Hi"}, existing={"a": "Czesc"})
    cfg = make_config(project_root)
    _seed(cfg)
    text = op_metrics(cfg, MetricsRequest(by="user", fmt="csv")).data["csv"]
    assert text.splitlines()[0].startswith("user,edits")
    assert "'=cmd," in text and "\n=cmd" not in text


def test_bad_by(project_root, make_config):
    setup_project(project_root, {"a": "Hi"}, existing={"a": "Czesc"})
    assert not op_metrics(make_config(project_root), MetricsRequest(by="x")).ok


def test_activity_csv_header():
    assert activity_csv([], "locale").splitlines() == ["locale,edits,translate,web_edit,last_at"]
