"""Settings → Hardcoded scan: [scan] round-trips through the web save, with list and bool checks (M6)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.projects.config import load_config
from llm_localizator.web.project_config import project_config_view, save_project_config


def _toml(root: Path) -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(
        '[project]\nname = "demo"\nsource_locale = "en"\n\n'
        '[catalog]\nformat = "json-nested"\npath = "messages/{locale}/{namespace}.json"\n\n'
        '[locales]\ntargets = ["pl"]\n\n[scan]\nsrc_dirs = ["src"]\n',
        encoding="utf-8",
    )
    (root / "messages" / "en").mkdir(parents=True, exist_ok=True)
    return path


def test_scan_settings_round_trip(tmp_path) -> None:
    path = _toml(tmp_path)
    result = save_project_config(load_config(path), scan={
        "adapter": "", "srcDirs": ["src", "app"], "exclude": ["content/**"], "unskip": [],
        "tFunctions": ["myT"], "contentGlobs": ["api/openapi.yaml"], "unusedAllow": [], "directiveAliases": False,
    })
    assert result["ok"], result
    cfg = load_config(path)
    assert cfg.scan_src_dirs == ["src", "app"] and cfg.scan_exclude == ["content/**"]
    assert cfg.scan_t_functions == ["myT"] and cfg.scan_content_globs == ["api/openapi.yaml"]
    assert cfg.scan_directive_aliases is False
    view = project_config_view(cfg)["scan"]
    assert view["srcDirs"] == ["src", "app"] and view["directiveAliases"] is False


def test_empty_lists_remove_keys(tmp_path) -> None:
    path = _toml(tmp_path)
    assert save_project_config(load_config(path), scan={"srcDirs": [], "directiveAliases": True})["ok"]
    text = path.read_text(encoding="utf-8")
    assert "src_dirs" not in text and "directive_aliases" not in text


def test_malformed_values_are_refused_and_file_kept(tmp_path) -> None:
    path = _toml(tmp_path)
    before = path.read_text(encoding="utf-8")
    assert not save_project_config(load_config(path), scan={"tFunctions": "tr"})["ok"]
    assert not save_project_config(load_config(path), scan={"directiveAliases": "false"})["ok"]
    assert path.read_text(encoding="utf-8") == before
