"""Operator pages, settings round-trip, analysis buckets, and pre-translate."""

from __future__ import annotations

import pytest

import json
import re
import subprocess
import sys
from pathlib import Path

from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.state import StateStore
from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.cli.main import build_parser
from llm_localizator.ops import build_commands_manifest, dispatch_op
from llm_localizator.ops.console import analysis_payload, progress_payload, usage_payload
from llm_localizator.ops.estimate_cost import op_estimate_cost
from llm_localizator.ops.types import EstimateCostRequest
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.projects.config import load_config
from llm_localizator.web import build_state
from llm_localizator.web.server import messages, rotate_web_token
from llm_localizator.web.settings import save_settings, settings_view
from llm_localizator.web.shell import render_shell

from .conftest import setup_project, tagged, write_json


def test_manifest_groups_and_unknown_command_is_absent() -> None:
    payload = build_commands_manifest(build_parser())
    commands = payload["commands"]
    assert "not-a-real-command" not in commands
    js = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "operations.js").read_text(encoding="utf-8")
    assert "not-a-real-command" not in js
    assert commands["validate"]["group"] == "Analysis"
    assert commands["glossary-propose"]["group"] == "Other"
    assert commands["translate"]["group"] == "LLM Pipeline"
    assert commands["translate"]["submit"] is True
    assert commands["validate"]["submit"] is False
    assert commands["validate"]["stream"] is False
    assert commands["validate"]["llm"] is False
    assert commands["validate"]["requires_llm"] is False
    assert commands["translate"]["llm"] is True
    assert commands["translate"]["requires_llm"] is True
    assert commands["run-translate"]["requires_llm"] is True
    assert commands["run-translate"]["group"] == "Other"
    assert "catalogue" in commands["validate"]["description"].lower()
    assert "Admin" in commands["validate"]["roles"]
    assert "Translator" in commands["validate"]["roles"]
    assert "Translator" not in commands["translate"]["roles"]
    assert payload["groups"][0] == "Analysis"
    assert "LLM Pipeline" in payload["groups"]
    analysis = payload["group_order"]["Analysis"]
    assert analysis[0] == "validate"
    assert analysis.index("status") < analysis.index("scan")


def test_validate_dry_run_writes_no_catalogue(project_root, make_config) -> None:
    setup_project(project_root, {"greet": "Hello"})
    catalog = project_root / "messages" / "en" / "app.json"
    before = catalog.read_bytes()
    flags = project_root / "flags.jsonl"
    cfg = make_config(project_root, flags_path=flags)
    result = dispatch_op(cfg, "validate", {"dry_run": True}, actor_role="Admin")
    assert catalog.read_bytes() == before
    assert not flags.exists()
    assert result.get("data", {}).get("flagsWritten", 0) == 0


def _settings_toml(root: Path) -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(
        "# keep me\n"
        "[project]\n"
        "name = \"demo\"\n"
        "source_locale = \"en\"\n"
        "\n"
        "[catalog]\n"
        "format = \"json-nested\"\n"
        "path = \"messages/{locale}/{namespace}.json\"\n"
        "\n"
        "[locales]\n"
        "targets = [\"pl\", \"de\"]\n"
        "frozen = []\n"
        "\n"
        "[provider]\n"
        "kind = \"null\"\n"
        "\n"
        "[web]\n"
        "overlay_edit = false\n",
        encoding="utf-8",
    )
    (root / "messages" / "en").mkdir(parents=True)
    return path


def test_unchanged_settings_keep_key_order_and_comment(tmp_path) -> None:
    import tomllib

    path = _settings_toml(tmp_path)
    before = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = load_config(path)
    result = save_settings(cfg, frozen=[], overlay_edit=False)
    assert result["ok"] is True
    text = path.read_text(encoding="utf-8")
    assert "# keep me" in text
    after = tomllib.loads(text)
    assert list(before["project"]) == list(after["project"])
    assert list(before["locales"]) == list(after["locales"])
    assert "token" not in settings_view(cfg, port=8770)


def test_bad_settings_value_names_the_path(tmp_path) -> None:
    path = _settings_toml(tmp_path)
    original = path.read_bytes()
    cfg = load_config(path)
    result = save_settings(cfg, frozen=[1])
    assert result["ok"] is False
    assert str(path) in result["error"]
    assert path.read_bytes() == original
    assert not (tmp_path / ".llm-localize.toml.probe").exists()


def test_settings_html_system_settings_tabs() -> None:
    html = render_shell("settings")
    assert "System settings" in html
    assert 'data-page="settings"' in html
    assert 'data-tab="llm"' in html
    assert 'data-tab="permissions"' in html
    assert 'id="settings-tabs"' in html
    assert "/static/settings.js" in html


def test_settings_js_smoke_markers() -> None:
    js = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "settings.js").read_text(encoding="utf-8")
    assert "data-panel" in js
    assert "allow_model_writes" in js
    assert "/api/remove-locale" in js
    assert "/api/provider-status" in js
    assert "reset_permissions" in js


def test_usage_renders_cloud_cost_and_local_zero(project_root, make_config) -> None:
    cfg = make_config(
        project_root,
        targets=["pl", "de"],
        locale_providers={"de": "openai"},
    )
    runs = cfg.state_root() / "_runs"
    runs.mkdir(parents=True)
    write_json(runs / "local.json", {
        "run_id": "local",
        "command": "translate",
        "locales": ["pl"],
        "metrics": {},
        "counts": {},
    })
    write_json(runs / "cloud.json", {
        "run_id": "cloud",
        "command": "translate",
        "locales": ["de"],
        "metrics": {"usd": 1.25},
        "counts": {},
    })
    payload = usage_payload(cfg)
    labels = {row["runId"]: row["cost"] for row in payload["runs"]}
    assert labels["local"] == "0"
    assert labels["cloud"] == "1.25"
    assert "monthUsd" in payload


def test_progress_skips_eta_for_frozen_locales(project_root, make_config) -> None:
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    cfg = make_config(project_root, targets=["pl", "de"], frozen=["de"])
    runs = cfg.state_root() / "_runs"
    runs.mkdir(parents=True)
    write_json(runs / "rate.json", {
        "run_id": "rate",
        "command": "translate",
        "locales": ["pl"],
        "wall_s": 86400,
        "metrics": {"written": 2},
        "counts": {},
    })
    payload = progress_payload(cfg)
    # stringsPerDay follows the 30-day velocity window (an undated run adds nothing there); ETAs still use the run rate.
    assert payload["stringsPerDay"] == 0.0
    by_locale = {row["locale"]: row for row in payload["locales"]}
    assert by_locale["de"]["frozen"] is True
    assert by_locale["de"]["etaDays"] is None
    assert by_locale["pl"]["etaDays"] is not None
    assert payload["runs"][0]["command"] == "translate"
    assert payload["runs"][0]["keys"] == 2
    assert by_locale["pl"]["scorePoints"] == []


def test_progress_series_priority_and_stage_counts(project_root, make_config) -> None:
    from datetime import datetime, timedelta, timezone

    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    cfg = make_config(project_root, targets=["pl", "de"], frozen=["de"], asap=["pl"])
    today = datetime.now(timezone.utc).date()
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "greet", score=0.9, signals=[], text="Witaj")
    scores.save("pl")
    runs = cfg.state_root() / "_runs"
    runs.mkdir(parents=True)
    recent_at = (today - timedelta(days=3)).isoformat() + "T10:00:00+00:00"
    old_at = (today - timedelta(days=40)).isoformat() + "T10:00:00+00:00"
    write_json(runs / "recent.json", {
        "run_id": "recent", "command": "translate", "locales": ["pl"],
        "finished_at": recent_at, "wall_s": 100,
        "metrics": {"written": 4}, "counts": {},
    })
    write_json(runs / "old.json", {
        "run_id": "old", "command": "translate", "locales": ["pl"],
        "finished_at": old_at, "wall_s": 100,
        "metrics": {"written": 9}, "counts": {},
    })
    payload = progress_payload(cfg, today=today)
    series = payload["series"]
    assert series["windowDays"] == 30
    assert len(series["days"]) == 30
    assert series["days"][-1] == today.isoformat()
    assert series["velocity"]["pl"][-4] == 4
    assert sum(series["velocity"]["pl"]) == 4
    assert series["quality"]["pl"]["meanScore"][-1] == 0.9
    assert series["quality"]["pl"]["rolling7"][-1] == 0.9
    assert series["quality"]["de"]["meanScore"][-1] is None
    assert {run["delta"] for run in payload["runs"]} == {4, 9}
    by_locale = {row["locale"]: row for row in payload["locales"]}
    assert by_locale["pl"]["priority"] == "asap"
    assert by_locale["de"]["priority"] == "frozen"
    assert by_locale["pl"]["velocityPerDay"] == round(4 / 30, 2)
    assert by_locale["pl"]["humanVerified"] == 0
    assert by_locale["pl"]["localized"] == by_locale["pl"]["translated"]
    stages = series["stages"]
    assert all(len(row) == 30 for row in stages.values())
    assert stages["localized"][-1] == by_locale["pl"]["translated"]
    assert stages["localized"] == sorted(stages["localized"])
    assert series["avgPerDay"] == round(4 / 30, 1)
    assert by_locale["de"]["etaDates"] is None
    assert by_locale["pl"]["velocity7PerDay"] == round(4 / 7, 2)
    eta = by_locale["pl"]["etaDates"]
    assert set(eta) == {"localized", "llm", "human"}
    assert all("provider" in run and "model" in run for run in payload["runs"])


def test_estimate_cost_does_not_open_a_provider(monkeypatch, project_root, make_config) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("provider HTTP")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    cfg = make_config(project_root)
    result = op_estimate_cost(cfg, EstimateCostRequest(locales=["pl"]))
    assert result.ok
    assert result.data["local"] is True


def test_estimate_cost_eta_uses_recent_translate_speed(project_root, make_config) -> None:
    from llm_localizator.pipeline.run_manifest import RunManifest

    cfg = make_config(project_root)
    first = op_estimate_cost(cfg, EstimateCostRequest(locales=["pl"]))
    assert first.data["eta_s"] is None  # no earlier runs, or nothing due
    for rate in (2.0, 4.0):
        run = RunManifest.start(command="translate", locales=["pl"])
        run.finish(keys_per_s=rate)
        run.write(cfg.state_root())
    from llm_localizator.ops.estimate_cost import _eta_seconds

    assert _eta_seconds(cfg, 30) == 10.0  # median 3 keys/s
    assert _eta_seconds(cfg, 0) is None


def test_analysis_buckets_sum_to_the_source_count(project_root, make_config) -> None:
    setup_project(project_root, {
        "a": "hello world",
        "b": "hello world",
        "c": "one two three",
        "d": "red blue green white",
        "e": "zzzz unique",
    })
    cfg = make_config(project_root)
    tm = TranslationMemory(cfg.tm_root())
    tm.record(locale="pl", source="hello world", text="witaj swiecie", model="t")
    tm.record(locale="pl", source="one two three four", text="jeden", model="t")
    tm.record(locale="pl", source="red blue green black", text="czerwony", model="t")
    payload = analysis_payload(cfg, "pl")
    assert payload["ok"] is True
    assert payload["exact"] + payload["fuzzyHigh"] + payload["fuzzyLow"] + payload["noMatch"] == payload["sourceCount"]
    assert payload["sourceCount"] == 5
    assert payload["exact"] == 2
    assert payload["fuzzyHigh"] == 1
    assert payload["fuzzyLow"] == 1
    assert payload["noMatch"] == 1
    assert payload["repetitions"] == 2


def test_analysis_report_buckets_only_due_strings(project_root, make_config) -> None:
    from llm_localizator.ops.console import analysis_due_sources, analysis_report

    setup_project(
        project_root,
        {"a": "hello world", "b": "hello world", "c": "one two three", "d": "zzzz unique"},
        existing={"c": "jeden dwa trzy"},
    )
    cfg = make_config(project_root)
    tm = TranslationMemory(cfg.tm_root())
    tm.record(locale="pl", source="hello world", text="witaj swiecie", model="t")
    report = analysis_report(cfg)
    assert report["ok"] is True
    row = report["locales"][0]
    assert row["locale"] == "pl"
    assert report["sourceStrings"] == 4
    assert row["due"] == 3  # "c" has a state-less translation; a, b, d are missing
    assert row["exact"] + row["fuzzyHigh"] + row["fuzzyLow"] + row["noMatch"] == row["due"]
    assert row["exact"] == 2
    assert row["cloud"] is False
    assert row["maxUsd"] == 0.0
    assert row["effortMin"] is None
    assert report["active"]["due"] == 3
    assert report["repetitions"]["total"] == 2
    assert report["repetitions"]["top"][0]["count"] == 2
    assert report["budget"]["allowCloud"] is False

    gaps = analysis_report(cfg, bands=False)
    assert gaps["bandsReady"] is False
    assert gaps["lengthByLocale"] == []
    assert gaps["locales"][0]["noMatch"] == 3
    assert gaps["locales"][0]["exact"] == 0
    _scope, due = analysis_due_sources(cfg)
    reuse = analysis_report(cfg, bands=True, due=due)
    assert reuse["locales"][0]["exact"] == 2


def test_analysis_report_namespace_filter_and_frozen(project_root, make_config) -> None:
    from llm_localizator.ops.console import analysis_report

    setup_project(project_root, {"a": "alpha beta"}, namespace="app")
    setup_project(project_root, {"b": "gamma delta"}, namespace="other")
    cfg = make_config(project_root, targets=["pl", "de"], frozen=["de"])
    full = analysis_report(cfg)
    assert {r["locale"] for r in full["locales"]} == {"pl", "de"}
    assert full["active"]["locales"] == ["pl"]
    assert full["active"]["due"] == 2
    de = next(r for r in full["locales"] if r["locale"] == "de")
    assert de["frozen"] is True and de["due"] == 2
    narrowed = analysis_report(cfg, namespace="other")
    assert narrowed["sourceStrings"] == 1
    assert narrowed["active"]["due"] == 1
    assert analysis_report(cfg, namespace="nope")["ok"] is False
    only_de = analysis_report(cfg, locales=["pl"])
    assert [r["locale"] for r in only_de["locales"]] == ["pl"]


def test_analysis_report_effort_needs_measured_history(project_root, make_config) -> None:
    from llm_localizator.ops import console
    from llm_localizator.ops.console import analysis_report

    setup_project(project_root, {f"k{i}": f"unique text {i} zz{i}" for i in range(30)})
    cfg = make_config(project_root)
    assert analysis_report(cfg)["locales"][0]["effortMin"] is None
    records = [
        {"command": "translate", "locales": ["pl"], "wall_s": 60.0, "metrics": {"written": 30}},
        {"command": "translate", "locales": ["pl", "de"], "wall_s": 9999.0, "metrics": {"written": 1}},
    ]
    original = console.iter_run_records
    console.iter_run_records = lambda _root: iter(records)
    try:
        row = analysis_report(cfg)["locales"][0]
    finally:
        console.iter_run_records = original
    assert row["due"] == 30
    assert row["effortMin"] == 1.0  # 30 strings x 2 s = 60 s


def test_analysis_report_cloud_cost_and_default_namespace_key(
    project_root, make_config, monkeypatch,
) -> None:
    from types import SimpleNamespace

    from llm_localizator.catalog import cloud_cost
    from llm_localizator.ops.console import analysis_report

    setup_project(project_root, {"a": "same text", "b": "same text", "c": "other text"})
    cfg = make_config(project_root)
    monkeypatch.setattr(cloud_cost, "paying_cloud_kind", lambda _c, _l: "openai")
    monkeypatch.setattr(
        cloud_cost, "quote_locale",
        lambda _c, _l, srcs, **_k: (SimpleNamespace(max_usd=1.25), "openai", "gpt-x"),
    )
    report = analysis_report(cfg)
    row = report["locales"][0]
    assert row["cloud"] is True
    assert row["maxUsd"] == 1.25
    assert report["active"]["maxUsd"] == 1.25
    top = report["repetitions"]["top"][0]
    assert not top["key"].startswith(".")


def test_analysis_page_loads_help_and_help_keys_exist() -> None:
    from llm_localizator.web.shell import _HELP_DEFER, _PAGE_SCRIPTS

    # help.js is deferred after first paint (Wave 3); page script stays lean.
    assert "/static/help.js" not in _PAGE_SCRIPTS["analysis"]
    assert "__LLM_ENSURE_HELP" in _HELP_DEFER
    help_keys = json.loads(
        (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "locales" / "help" / "en.json").read_text(encoding="utf-8")
    )  # help text lives in locales/help/<loc>.json; help.js only renders it
    for topic in ("general", "breakdown", "repetitions", "providers", "queue"):
        assert f"analysis:{topic}" in help_keys


def test_pre_translate_skips_score_and_matches_filter(
    project_root, make_config, make_catalog, silent,
) -> None:
    from llm_localizator.providers import NullProvider

    setup_project(project_root, {"greet": "Hello"})
    flags = project_root / "flags.jsonl"
    cfg = make_config(project_root, flags_path=flags)
    catalog = make_catalog(cfg)
    result = run_translation(
        cfg, catalog, NullProvider(handler=tagged),
        pre_translate=True, report=silent,
    )
    assert result.written == 1
    assert catalog.load("pl", "app")["greet"] == "[xx] Hello"
    assert ScoreStore(cfg.scores_root()).get("pl", "app", "greet") is None
    assert not flags.exists()
    event = HistoryStore(cfg.history_root()).latest("pl", "app", "greet")
    assert event is not None
    assert event.trigger == "pre-translate"
    entry = StateStore(cfg.state_dir).entry("pl", "app", "greet")
    assert entry["status"] == "machine"
    assert TranslationMemory(cfg.tm_root()).exact("pl", "Hello") is None
    payload = messages(build_state(cfg), ["pl"], "app", only="pre_translated")
    assert [row["key"] for row in payload["rows"]] == ["greet"]


@pytest.mark.slow
def test_ci_doc_invokes_validate_only() -> None:
    text = Path("docs/ci.md").read_text(encoding="utf-8")
    fences = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    assert len(fences) >= 2
    proc = subprocess.run(
        [sys.executable, "-m", "llm_localizator", "validate", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    help_text = proc.stdout + proc.stderr
    found = False
    for fence in fences:
        assert "impact" not in fence
        for invocation in re.findall(r"llm-localizator[ \t]+\S+", fence):
            found = True
            assert invocation.split()[1] == "validate"
        for flag in re.findall(r"--[A-Za-z0-9][\w-]*", fence):
            assert flag in help_text
    assert found


def test_token_regenerate_prints_once(tmp_path, capsys) -> None:
    path = _settings_toml(tmp_path)
    cfg = load_config(path)

    class Handler:
        session_token = "old"

    token = rotate_web_token(Handler, cfg)
    assert token != "old"
    assert Handler.session_token == token
    printed = capsys.readouterr().out
    assert printed.count("token:") == 1
    assert (cfg.state_root() / "web.token").read_text(encoding="utf-8").strip() == token


def test_progress_helpers_eta_velocity_and_stage_series() -> None:
    from datetime import date

    from llm_localizator.ops.console import _eta, _stage_series, _velocity_by_day

    today = date(2026, 10, 18)
    assert _eta(0, 0, today) == {"days": 0, "date": "2026-10-18"}
    assert _eta(10, 0, today) is None
    assert _eta(10, 3, today) == {"days": 4, "date": "2026-10-22"}

    days = ["2026-10-16", "2026-10-17", "2026-10-18"]
    records = [
        {"command": "translate", "locales": ["pl", "de"], "finished_at": "2026-10-17T10:00:00",
         "metrics": {"written": 10}},
        {"command": "improve", "locales": ["pl"], "finished_at": "2026-10-17T11:00:00",
         "metrics": {"written": 99}},
    ]
    vel = _velocity_by_day(records, days, ["pl", "de"])
    assert vel == {"pl": [0, 5, 0], "de": [0, 5, 0]}

    series = _stage_series(
        [("human_edited", "2026-10-18"), ("llm_generated", ""), ("tm_reused", "2026-10-17"),
         ("llm_generated", "2027-01-01")],
        days,
    )
    assert series["localized"] == [1, 2, 4]
    assert series["llm"] == [1, 2, 3]
    assert series["human"] == [0, 0, 1]


def test_progress_help_is_registered() -> None:
    from pathlib import Path

    from llm_localizator.web.shell import _HELP_DEFER, _PAGE_SCRIPTS

    root = Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static"
    assert "/static/help.js" not in _PAGE_SCRIPTS["progress"]
    assert "__LLM_ENSURE_HELP" in _HELP_DEFER
    help_keys = json.loads((root.parent / "locales" / "help" / "en.json").read_text(encoding="utf-8"))
    assert "progress:general" in help_keys
    assert 'helpBtn("progress:general")' in (root / "progress.js").read_text(encoding="utf-8")
