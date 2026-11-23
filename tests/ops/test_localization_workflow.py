"""Status "no record", scan surfaces, localize-project, doctor key check, engine use."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_localizator.doctor import _key_checks
from llm_localizator.ops.engines import op_engine
from llm_localizator.ops.localize_project import LocalizeProjectRequest, op_localize_project
from llm_localizator.ops.scan_surfaces import OTHER, mode_of, surface_of, unknown_names
from llm_localizator.ops.status import collect
from llm_localizator.projects import ConfigError
from llm_localizator.projects.config_load import _scan_surfaces

from tests.conftest import setup_project


def _project(project_root, make_config, make_catalog):
    setup_project(
        project_root,
        {"a": "Alpha", "b": "Beta", "c": "Gamma", "d": "Delta"},
        # a: real translation without a record, b: empty, c: copy of source, d: absent
        existing={"a": "Alfa", "b": "", "c": "Gamma"},
    )
    cfg = make_config(project_root)
    return cfg, make_catalog(cfg)


def test_status_separates_no_record_from_missing(project_root, make_config, make_catalog) -> None:
    cfg, catalog = _project(project_root, make_config, make_catalog)
    row = next(r for r in collect(cfg, catalog) if r.locale == "pl")
    assert row.no_record == 1  # "a": text exists, the record does not
    assert row.missing == 3    # b empty, c copy of the source, d absent
    assert row.translated == 0


def test_localize_project_reports_gaps_and_submits_nothing(project_root, make_config, make_catalog) -> None:
    cfg, _ = _project(project_root, make_config, make_catalog)
    result = op_localize_project(cfg, LocalizeProjectRequest(locales=["pl"]))
    assert result.ok
    assert result.data["missing"] == {"pl": 2}  # only absent or empty values
    assert "nothing submitted" in result.summary
    text = "\n".join(result.lines)
    assert "--only-missing" in text and "have text but no state record" in text


def test_surface_matching_uses_globs_and_directory_prefixes() -> None:
    surfaces = {
        "web": {"paths": ["tqdaemon/web", "static/**/*.js"], "mode": "fix"},
        "cli": {"paths": ["tqdaemon/cli.py"], "mode": "report"},
        "tests": {"paths": ["tests/"], "mode": "ignore"},
    }
    assert surface_of(surfaces, "tqdaemon/web/routes.py") == "web"
    assert surface_of(surfaces, "static/js/app.js") == "web"
    assert surface_of(surfaces, "tqdaemon\\cli.py") == "cli"
    assert surface_of(surfaces, "tests/test_x.py") == "tests"
    assert surface_of(surfaces, "other/file.py") == OTHER
    assert mode_of(surfaces, "cli") == "report"
    assert mode_of(surfaces, OTHER) == "fix"  # unmatched findings behave as before
    assert unknown_names(surfaces, {"web", "nope", OTHER}) == ["nope"]


def test_surface_config_is_validated() -> None:
    path = Path("x.toml")
    ok = _scan_surfaces({"cli": {"paths": ["a.py"], "mode": "report"}}, path)
    assert ok == {"cli": {"paths": ["a.py"], "mode": "report"}}
    assert _scan_surfaces(None, path) == {}
    with pytest.raises(ConfigError):
        _scan_surfaces({"cli": {"paths": ["a.py"], "mode": "maybe"}}, path)
    with pytest.raises(ConfigError):
        _scan_surfaces({"cli": {"mode": "fix"}}, path)  # no paths
    with pytest.raises(ConfigError):
        _scan_surfaces({"cli": {"paths": ["a.py"], "color": "red"}}, path)


def test_doctor_names_the_key_variable_but_never_prints_the_key(monkeypatch) -> None:
    cfg = SimpleNamespace(provider=SimpleNamespace(kind="anthropic", api_key_env=None))
    for name in ("ANTHROPIC_API_KEY", "LLM_LOCALIZATOR_ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    (missing,) = _key_checks(cfg)
    assert missing.status == "warn" and "LLM_LOCALIZATOR_ANTHROPIC_API_KEY" in missing.detail

    monkeypatch.setenv("LLM_LOCALIZATOR_ANTHROPIC_API_KEY", "sk-test-do-not-print")
    (found,) = _key_checks(cfg)
    assert found.status == "ok"
    assert "LLM_LOCALIZATOR_ANTHROPIC_API_KEY" in found.detail
    assert "sk-test-do-not-print" not in found.detail

    assert _key_checks(SimpleNamespace(provider=SimpleNamespace(kind="ollama", api_key_env=None))) == []


def test_engine_use_is_an_alias_for_apply(project_root, make_config, make_catalog) -> None:
    cfg, _ = _project(project_root, make_config, make_catalog)
    assert op_engine(cfg, "use", None).summary == op_engine(cfg, "apply", None).summary


def test_localize_project_baseline_separates_new_errors_from_old(project_root, make_config, make_catalog) -> None:
    cfg, _ = _project(project_root, make_config, make_catalog)
    first = op_localize_project(cfg, LocalizeProjectRequest(locales=["pl"]))
    assert any("no baseline yet" in line for line in first.lines)

    saved = op_localize_project(cfg, LocalizeProjectRequest(locales=["pl"], baseline=True))
    assert "baseline" in saved.data
    again = op_localize_project(cfg, LocalizeProjectRequest(locales=["pl"]))
    assert any("0 new" in line for line in again.lines)

    # Break a translation after the baseline: it shows up as new.
    import json
    path = project_root / "messages" / "pl" / "app.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["a"] = ""
    path.write_text(json.dumps(data), encoding="utf-8")
    after = op_localize_project(cfg, LocalizeProjectRequest(locales=["pl"]))
    assert after.data["validation"]["old"] >= 0
