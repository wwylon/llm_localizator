"""`normalize`: the candidate normalizer applied to existing catalogue values."""

from __future__ import annotations

import json

from llm_localizator.catalog.state import state_key
from llm_localizator.ops.normalize_existing import op_normalize
from llm_localizator.pipeline.recording import provenance_stores

from tests.conftest import setup_project


def _project(project_root, make_config):
    setup_project(
        project_root,
        {"saving": "Saving…", "missing": "Missing", "title": "settings"},
        existing={"saving": "Zapisywanie...", "missing": "„Brakujące”", "title": "Ustawienia"},
    )
    return make_config(project_root)


def _pl(project_root) -> dict:
    return json.loads((project_root / "messages" / "pl" / "app.json").read_text(encoding="utf-8"))


def test_report_only_by_default(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    out = op_normalize(cfg)
    assert out.ok and not out.data["written"]
    fixed = {f["key"]: f["after"] for f in out.data["fixes"]}
    assert fixed == {"saving": "Zapisywanie…", "missing": "Brakujące"}
    # "title" needs the opt-in case step (source is lowercase): counted, not changed.
    assert out.data["needs_opt_in"] == 1
    assert _pl(project_root)["saving"] == "Zapisywanie..."


def test_opt_in_case_step(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    out = op_normalize(cfg, steps=["case"])
    assert [f["key"] for f in out.data["fixes"]] == ["title"]


def test_write_applies_and_keeps_status(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    stores = provenance_stores(cfg)
    stores.state.load("pl")[state_key("app", "saving")] = {"status": "human", "provider": "human"}
    stores.state.save("pl")
    out = op_normalize(cfg, write=True)
    assert out.data["written"]
    assert _pl(project_root)["saving"] == "Zapisywanie…"
    entry = provenance_stores(cfg).state.load("pl")[state_key("app", "saving")]
    assert entry["status"] == "human", "a cosmetic fix keeps the key's provenance"


def test_verified_and_locked_keys_are_never_touched(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    stores = provenance_stores(cfg)
    data = stores.state.load("pl")
    data[state_key("app", "saving")] = {"status": "human", "verified_at": "2026-11-01T00:00:00Z"}
    data[state_key("app", "missing")] = {"status": "machine", "locked": True}
    stores.state.save("pl")
    out = op_normalize(cfg, write=True)
    assert out.data["fixes"] == [] and out.data["protected"] == 2
    assert _pl(project_root)["saving"] == "Zapisywanie..."


def test_unknown_step_is_a_usage_error(project_root, make_config) -> None:
    cfg = _project(project_root, make_config)
    assert op_normalize(cfg, steps=["bogus"]).exit_code == 64
