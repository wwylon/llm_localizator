"""Usage & costs page: ledger schema, period payload, CSV export, help entries."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

from llm_localizator.catalog.budget import BudgetStore
from llm_localizator.ops.console import USAGE_PERIODS, usage_export_csv, usage_payload

from .conftest import setup_project

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 19)


def _seed_ledger(cfg, events: dict[str, list[dict]]) -> None:
    root = cfg.budget_root()
    root.mkdir(parents=True, exist_ok=True)
    data = {
        month: {"total_usd": round(sum(e["usd"] for e in rows), 6), "events": rows}
        for month, rows in events.items()
    }
    (root / "spend.json").write_text(json.dumps(data), encoding="utf-8")


def _cfg(project_root, make_config, **kw):
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    return make_config(project_root, targets=["pl", "de"], locale_providers={"de": "openai"}, **kw)


def test_ledger_records_kind_and_tokens_and_reads_old_events(tmp_path) -> None:
    store = BudgetStore(tmp_path)
    store.record(0.5, locale="de", model="m", kind="openai", input_tokens=10, output_tokens=4)
    store.record(0.1, locale="de", model="m")
    events = store.events()
    assert events[0]["kind"] == "openai"
    assert events[0]["input_tokens"] == 10 and events[0]["output_tokens"] == 4
    assert "kind" not in events[1] and "input_tokens" not in events[1]
    assert len(store.months()) == 1


def test_usage_payload_keeps_legacy_fields_and_zero_cloud(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    payload = usage_payload(cfg, today=TODAY)
    assert payload["ok"] is True and "monthUsd" in payload and payload["runs"] == []
    assert payload["cards"]["cloudUsd"] == 0
    assert payload["cards"]["projectedUsd"] is None
    assert payload["cards"]["tokens"] is None
    assert payload["budget"]["allowCloud"] is False
    assert {r["locale"] for r in payload["locales"]} == {"pl", "de"}
    assert all(r["usd"] == 0 for r in payload["locales"])
    assert payload["providers"]["cloud"] == []


def test_usage_payload_periods_projection_and_groups(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    _seed_ledger(cfg, {
        "2026-09": [{"ts": "2026-09-10T10:00:00+00:00", "usd": 1.0, "locale": "de", "model": "m1"}],
        "2026-10": [
            {"ts": "2026-10-02T10:00:00+00:00", "usd": 1.0, "locale": "de", "model": "m1",
             "kind": "openai", "input_tokens": 100, "output_tokens": 50},
            {"ts": "2026-10-10T10:00:00+00:00", "usd": 2.0, "locale": "de", "model": "m2",
             "kind": "openai", "input_tokens": 10, "output_tokens": 5},
        ],
    })
    month = usage_payload(cfg, "month", today=TODAY)
    assert month["cards"]["cloudUsd"] == 3.0
    assert month["cards"]["tokens"] == 165
    # 3.0 over 19 elapsed days of a 31-day month.
    assert month["cards"]["projectedUsd"] == round(3.0 / 19 * 31, 6)
    assert [p["model"] for p in month["providers"]["cloud"]] == ["m2", "m1"]
    assert month["providers"]["cloud"][0]["share"] == round(2 / 3, 4)
    assert len(month["daily"]) == 19
    assert sum(d["usd"] for d in month["daily"]) == 3.0

    last = usage_payload(cfg, "last_month", today=TODAY)
    assert last["cards"]["cloudUsd"] == 1.0
    assert last["cards"]["projectedUsd"] is None
    assert last["period"]["from"] == "2026-09-01" and last["period"]["to"] == "2026-09-30"

    everything = usage_payload(cfg, "all", today=TODAY)
    assert everything["cards"]["cloudUsd"] == 4.0
    assert usage_payload(cfg, "bogus", today=TODAY)["period"]["key"] == "month"


def test_estimate_local_is_zero_and_unpriced_model_is_not_guessed(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    rows = {r["locale"]: r for r in usage_payload(cfg, today=TODAY)["estimate"]["rows"]}
    assert rows["pl"]["usd"] == 0.0 and rows["pl"]["note"] == "own_hardware"
    assert rows["de"]["provider"] == "openai"
    # Never a silent cheap default: either priced, or flagged as unpriced.
    assert rows["de"]["priced"] is True or rows["de"]["usd"] is None


def test_export_csv_filters_by_period(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    _seed_ledger(cfg, {
        "2026-09": [{"ts": "2026-09-10T10:00:00+00:00", "usd": 1.0, "locale": "de", "model": "m1"}],
        "2026-10": [{"ts": "2026-10-02T10:00:00+00:00", "usd": 2.0, "locale": "de", "model": "m2",
                     "kind": "openai", "input_tokens": 7}],
    })
    rows = list(csv.DictReader(io.StringIO(usage_export_csv(cfg, "month", today=TODAY))))
    assert [r["model"] for r in rows] == ["m2"]
    assert rows[0]["input_tokens"] == "7" and rows[0]["provider"] == "openai"
    assert len(list(csv.DictReader(io.StringIO(usage_export_csv(cfg, "all", today=TODAY))))) == 2


def test_periods_are_documented_in_routes_and_help() -> None:
    assert USAGE_PERIODS == ("month", "last_month", "90d", "all")
    routes = (ROOT / "llm_localizator" / "web" / "api_routes.py").read_text(encoding="utf-8")
    assert "/api/usage/export" in routes
    import json

    help_keys = json.loads((ROOT / "llm_localizator" / "web" / "locales" / "help" / "en.json").read_text(encoding="utf-8"))
    for key in ("usage:general", "usage:providers", "usage:locales", "usage:estimate"):
        assert key in help_keys
