"""Server-side copy in Python (B3, ADR-134)."""

from __future__ import annotations

from llm_localizator.scan.py_sinks import server_strings

SRC = '''
from fastapi import HTTPException
def a(job):
    if not job:
        raise HTTPException(404, "unknown job")
    raise HTTPException(status_code=400, detail=f"bad target {job}")
def b():
    return {"error": "Queue is paused", "status": "ok", "path": "/tmp/x"}
def c():
    flash("Saved your settings")
    raise HTTPException(500, _("already routed"))
def d():
    return JSONResponse({"message": "ok"})
'''


def test_sinks() -> None:
    got = [(s.line, s.text, s.sink) for s in server_strings(SRC)]
    assert got == [
        (5, "unknown job", "exception"),
        (6, "bad target {…}", "exception"),
        (8, "Queue is paused", "payload:error"),
        (10, "Saved your settings", "flash"),
    ]


def test_syntax_error_is_empty() -> None:
    assert server_strings("def (:") == []


def test_locator_reads_server_dirs(tmp_path) -> None:
    from types import SimpleNamespace

    from llm_localizator.scan.locate import LiteralIndex, source_files

    (tmp_path / "web").mkdir()
    (tmp_path / "srv").mkdir()
    (tmp_path / "web" / "app.js").write_text("show('hello');\n", encoding="utf-8")
    (tmp_path / "srv" / "api.py").write_text('raise HTTPException(404, "unknown job")\n', encoding="utf-8")
    cfg = SimpleNamespace(root=tmp_path, scan_src_dirs=["web"], scan_server_dirs=["srv"],
                          scan_exclude=[], scan_unskip=[])
    assert [p.name for p in source_files(cfg)] == ["app.js"]  # scanners: unchanged
    hit = LiteralIndex(cfg).find("unknown job")
    assert hit is not None and hit.file == "srv/api.py" and hit.line == 1
