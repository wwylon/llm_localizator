"""web.bat launcher contract (help, hard-coded ports equal to the CLI defaults)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from llm_localizator.cli.main import DEFAULT_MARKETING_PORT, DEFAULT_WEB_PORT

BAT = Path(__file__).resolve().parents[1] / "web.bat"


def test_ports_match_cli_defaults() -> None:
    text = BAT.read_text(encoding="utf-8")
    assert re.search(rf'set "PORT={DEFAULT_WEB_PORT}"', text)
    assert re.search(rf'set "MPORT={DEFAULT_MARKETING_PORT}"', text)


@pytest.mark.skipif(sys.platform != "win32", reason="batch file")
@pytest.mark.parametrize("flag", ["--help", "-h", "/?"])
def test_help_exits_zero(flag: str) -> None:
    out = subprocess.run(["cmd", "/c", str(BAT), flag], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert out.stdout.startswith("Usage: web.bat")
    assert f"http://127.0.0.1:{DEFAULT_WEB_PORT}/" in out.stdout
