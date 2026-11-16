"""Static scripts parse. The review page is no longer one inlined string."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static"


@pytest.mark.slow
def test_static_scripts_parse() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    for path in sorted(STATIC.glob("*.js")):
        proc = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{path.name}: {proc.stderr}"
