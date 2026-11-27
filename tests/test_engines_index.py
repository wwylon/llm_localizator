"""Site build publishes engines/index.json for ``engine fetch``."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.engines.fetch import build_index


def test_build_index_writes_index_json(tmp_path: Path) -> None:
    out = tmp_path / "engines"
    index = build_index(out=out)
    path = out / "index.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "engines" in data
    assert isinstance(data["engines"], list)
    assert data == index
