"""CLI wiring: exit codes and output formats.

Exit-code semantics are a contract with CI and with taskqueue: 0 clean,
1 errors, 2 warnings-only, 64 usage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.cli.main import main

from .conftest import write_json

CONFIG = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    return tmp_path


def run(args: list[str], project: Path) -> int:
    return main([*args, "--config", str(project / ".llm-localize.toml")])


# ---- exit codes ------------------------------------------------------------

def test_clean_catalogue_exits_zero(project: Path, capsys) -> None:
    write_json(project / "messages" / "pl" / "app.json", {"greet": "Witaj"})
    assert run(["validate"], project) == 0


def test_missing_key_is_an_error_exit_one(project: Path, capsys) -> None:
    write_json(project / "messages" / "pl" / "app.json", {})
    assert run(["validate"], project) == 1


def test_warnings_only_exits_two(project: Path, capsys) -> None:
    # Identical to source is a warning, not an error.
    write_json(project / "messages" / "pl" / "app.json", {"greet": "Hello"})
    assert run(["validate"], project) == 2


def test_strict_promotes_warnings_to_errors(project: Path, capsys) -> None:
    write_json(project / "messages" / "pl" / "app.json", {"greet": "Hello"})
    assert run(["validate", "--strict"], project) == 1


def test_missing_config_is_a_usage_error(tmp_path: Path, capsys) -> None:
    assert main(["validate", "--config", str(tmp_path / "nope.toml")]) == 64


def test_no_command_prints_help(capsys) -> None:
    assert main([]) == 64
    assert "usage:" in capsys.readouterr().out


def test_version_flag(capsys) -> None:
    from llm_localizator import __version__

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


# ---- output formats --------------------------------------------------------

def test_json_format_is_parseable(project: Path, capsys) -> None:
    write_json(project / "messages" / "pl" / "app.json", {})
    run(["validate", "--format", "json"], project)
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"] == 1
    assert payload["findings"][0]["check"] == "V01"


def test_github_format_emits_annotations(project: Path, capsys) -> None:
    write_json(project / "messages" / "pl" / "app.json", {})
    run(["validate", "--format", "github"], project)
    assert capsys.readouterr().out.startswith("::error ")


def test_github_annotations_are_single_line(project: Path, capsys) -> None:
    """A newline inside a workflow command truncates the annotation."""
    write_json(project / "messages" / "pl" / "app.json", {})
    run(["validate", "--format", "github"], project)
    for line in capsys.readouterr().out.strip().splitlines():
        assert line.startswith("::")


def test_quiet_prints_only_the_summary(project: Path, capsys) -> None:
    write_json(project / "messages" / "pl" / "app.json", {})
    run(["validate", "--quiet"], project)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("checked")


# ---- scoping ---------------------------------------------------------------

def test_locale_filter_restricts_the_run(project: Path, capsys) -> None:
    write_json(project / "messages" / "pl" / "app.json", {})       # broken
    write_json(project / "messages" / "de" / "app.json", {"greet": "Hallo"})  # clean

    assert run(["validate", "--locale", "de"], project) == 0, "pl's problems must be out of scope"
    assert run(["validate", "--locale", "pl"], project) == 1


def test_expansion_check_is_off_by_default(project: Path, capsys) -> None:
    """V14 is opt-in: it fired on ~half of bridge's keys as false positives."""
    write_json(project / "messages" / "pl" / "app.json", {"greet": "W"})
    run(["validate", "--format", "json"], project)
    checks = {f["check"] for f in json.loads(capsys.readouterr().out)["findings"]}
    assert "V14" not in checks


def test_expansion_check_can_be_enabled(project: Path, capsys) -> None:
    write_json(project / "messages" / "en" / "app.json", {"greet": "Hello there friend"})
    write_json(project / "messages" / "pl" / "app.json", {"greet": "W"})
    run(["validate", "--check-expansion", "--format", "json"], project)
    checks = {f["check"] for f in json.loads(capsys.readouterr().out)["findings"]}
    assert "V14" in checks


# ---- status ----------------------------------------------------------------

def test_status_reports_zero_coverage_for_an_untranslated_locale(
    project: Path, capsys
) -> None:
    assert run(["status"], project) == 0
    assert "never translated" in capsys.readouterr().out


# ---- V08 independence ------------------------------------------------------

def test_signature_mismatch_on_unchanged_source_is_reported(project: Path, capsys) -> None:
    """The check that would have caught the Go divergence.

    A stale signature on a source that has *not* changed cannot come from an
    edit. It means whatever wrote it computes signatures differently -- a second
    implementation, or an unmigrated format version. Nesting this inside the
    'source changed' branch hid exactly that case.
    """
    import json as _json

    from llm_localizator.catalog import StateStore, make_entry

    write_json(project / "messages" / "pl" / "app.json", {"greet": "Witaj"})
    store = StateStore(project / "messages" / ".state")
    entry = make_entry("Hello", "m")          # src_sha matches the source...
    entry["structure_sig"] = "deadbeef0000"   # ...but the signature does not
    store.record("pl", "app", "greet", entry)
    store.save("pl")

    # The default project config has no [state] dir, so point at one (beside the config, not the engine home).
    cfg = project / ".llm-localize.toml"
    cfg.write_text(
        CONFIG.replace('name = "demo"\n', 'name = "demo"\ndata_home = "project"\n', 1)
        + '\n[state]\ndir = "messages/.state"\n',
        encoding="utf-8",
    )

    run(["validate", "--format", "json"], project)
    payload = _json.loads(capsys.readouterr().out)
    findings = {f["check"]: f["message"] for f in payload["findings"]}

    assert "V08" in findings, "an unmigrated signature must be visible"
    assert "migrate-state" in findings["V08"]
    assert "V07" not in findings, "the source did not change, so it is not stale"


def test_add_locale_writes_targets(project: Path) -> None:
    from llm_localizator.projects.config import load_config

    assert run(["add-locale", "--locale", "de", "--model", "aya:8b"], project) == 0
    cfg = load_config(project / ".llm-localize.toml")
    assert "de" in cfg.targets
    assert cfg.models.get("de") == "aya:8b"
    assert run(["add-locale", "--locale", "de"], project) == 1
    assert run(["add-locale", "--locale", "../nope"], project) == 1
