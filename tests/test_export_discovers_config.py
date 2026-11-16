"""`export` and `import` find .llm-localize.toml from the working directory like every other command."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.cli.main import main


def _project(tmp_path: Path) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps({"a": "Hello"}), encoding="utf-8")
    (tmp_path / "locales" / "pl.json").write_text(json.dumps({"a": "Czesc"}), encoding="utf-8")
    (tmp_path / ".llm-localize.toml").write_text(
        '[project]\nname = "t"\n[catalog]\nformat = "json-nested"\npath = "locales/{locale}.json"\n'
        '[locales]\ntargets = ["pl"]\n',
        encoding="utf-8",
    )


def test_export_without_project_argument(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out.csv"
    code = main(["export", "--locales", "pl", "--format", "csv", "--out", str(out)])
    assert code == 0
    assert out.is_file() and "Hello" in out.read_text(encoding="utf-8")
