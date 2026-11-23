"""Tests for ``llm-localizator doctor``."""

from __future__ import annotations

from pathlib import Path

from llm_localizator import __version__
from llm_localizator.doctor import package_info, run_doctor, ui_digest
from llm_localizator.web.assets import WEB_FEATURES, ui_source

from tests.pipeline.test_translate import setup_project


def test_package_info_has_version() -> None:
    info = package_info()
    assert info["version"] == __version__
    assert "packagePath" in info


def test_ui_digest_stable() -> None:
    page = ui_source()
    assert ui_digest(page) == ui_digest(page)
    assert len(ui_digest(page)) == 12


def test_web_features_markers_present() -> None:
    from llm_localizator.web.shell import render_shell
    html = render_shell("editor")
    ops_js = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "ops.js").read_text(encoding="utf-8")
    # ops-drawer was removed from the shell template; ops panel is inside operations.js
    assert "ops-import-files" in ops_js
    assert "ops-layout" in ops_js or "op-layout" in html or "op-layout" in ops_js
    assert "ops" in WEB_FEATURES


def test_doctor_project_checks(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    checks = run_doctor(cfg, web_port=19999, skip_ollama=True)
    names = {c.name for c in checks}
    assert "package" in names
    assert "catalog" in names
    assert "config" in names


def _by_name(checks):
    return {c.name: c for c in checks}


def test_doctor_flags_missing_targets(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    cfg = make_config(project_root, targets=[])
    check = _by_name(run_doctor(cfg, web_port=19999, skip_ollama=True))["targets"]
    assert check.status == "warn"
    assert "add-locale --locale pl" in check.detail


def test_doctor_fails_when_there_are_no_source_strings(project_root, make_config) -> None:
    setup_project(project_root, {})
    cfg = make_config(project_root)
    source = _by_name(run_doctor(cfg, web_port=19999, skip_ollama=True))["source"]
    assert source.status == "fail"
    assert "messages/{locale}/{namespace}.json" in source.detail


def test_doctor_reports_source_key_count(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A", "b": "B"})
    cfg = make_config(project_root)
    catalog = _by_name(run_doctor(cfg, web_port=19999, skip_ollama=True))["catalog"]
    assert "2 source key(s)" in catalog.detail


def test_unreachable_ollama_is_a_warning_with_a_hint_and_fails_only_when_strict(
    project_root, make_config, monkeypatch, capsys,
) -> None:
    import argparse

    from llm_localizator import doctor as doctor_mod
    from llm_localizator.cli.cmd_doctor import run
    from llm_localizator.projects.config import ProviderConfig

    monkeypatch.setattr(
        doctor_mod, "_ping_ollama",
        lambda url: doctor_mod.Check("ollama", "warn", f"not reachable at {url}"),
    )
    setup_project(project_root, {"a": "A"})
    ollama = make_config(project_root, provider=ProviderConfig(kind="ollama"))
    check = _by_name(run_doctor(ollama, web_port=19999))["ollama"]
    assert check.status == "warn"
    assert "https://ollama.com" in check.detail
    assert _by_name(run_doctor(None, web_port=19999))["ollama"].status == "warn"

    config_path = project_root / ".llm-localize.toml"
    config_path.write_text(
        '[project]\nname = "testproj"\n\n[catalog]\n'
        'path = "messages/{locale}/{namespace}.json"\n\n[locales]\ntargets = ["pl"]\n',
        encoding="utf-8",
    )

    def args(strict: bool) -> argparse.Namespace:
        return argparse.Namespace(
            project=None, config=config_path, port=19999,
            skip_ollama=False, json=True, strict=strict,
        )

    assert run(args(False)) == 0
    assert run(args(True)) == 1
    capsys.readouterr()


def test_doctor_hides_the_web_probe_when_no_server_runs(project_root, make_config) -> None:
    setup_project(project_root, {"a": "A"})
    names = {c.name for c in run_doctor(make_config(project_root), web_port=19999, skip_ollama=True)}
    assert "web" not in names


def test_doctor_cli_json(project_root, make_config, capsys) -> None:
    from llm_localizator.cli.cmd_doctor import run
    import argparse

    setup_project(project_root, {"a": "A"})
    make_config(project_root)
    config_path = project_root / ".llm-localize.toml"
    config_path.write_text(
        f'[project]\nname = "testproj"\n\n[catalog]\n'
        f'path = "messages/{{locale}}/{{namespace}}.json"\n\n'
        f'[locales]\ntargets = ["pl"]\n',
        encoding="utf-8",
    )
    args = argparse.Namespace(
        project=None, config=config_path,
        port=19999, skip_ollama=True, json=True,
    )
    code = run(args)
    assert code == 0
    out = capsys.readouterr().out
    assert __version__ in out
