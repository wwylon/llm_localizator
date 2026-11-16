"""scripts/pre_commit.py: staged-file checks (M5)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pre_commit  # noqa: E402


def _run(monkeypatch, tmp_path, files: dict[str, bytes], env: dict | None = None) -> int:
    for name, data in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    monkeypatch.setattr(pre_commit, "ROOT", tmp_path)
    monkeypatch.setattr(pre_commit, "staged", lambda: list(files))
    monkeypatch.delenv("ALLOW_USER_FILES", raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return pre_commit.main()


def test_clean_files_pass(monkeypatch, tmp_path) -> None:
    assert _run(monkeypatch, tmp_path, {"a.py": b"x = 1\n"}) == 0


def test_control_byte_and_syntax_error_fail(monkeypatch, tmp_path, capsys) -> None:
    assert _run(monkeypatch, tmp_path, {"a.py": b"r = 're\x08x'\n", "b.py": b"def (:\n"}) == 1
    err = capsys.readouterr().err
    assert "0x08" in err and "does not compile" in err


def test_user_files_need_an_override(monkeypatch, tmp_path) -> None:
    files = {"uv.lock": b"x\n"}
    assert _run(monkeypatch, tmp_path, files) == 1
    assert _run(monkeypatch, tmp_path, files, {"ALLOW_USER_FILES": "1"}) == 0
