"""``server-copy``: people-facing English in Python server code (B3, ADR-134).

Reads ``[scan] server_dirs`` (``.py`` only) through ``scan/py_sinks.py``. Each row is
something the server writes into a response that the front end then shows: route it
through the catalogue (return a key, or translate on the server) or mark it as an
internal message. Read-only.
"""

from __future__ import annotations

from pathlib import Path

from ..projects import ProjectConfig
from ..scan.locate import source_files
from ..scan.py_sinks import server_strings
from .types import OpResult

__all__ = ["op_server_copy"]


def op_server_copy(cfg: ProjectConfig) -> OpResult:
    if not getattr(cfg, "scan_server_dirs", None):
        return OpResult(ok=True, exit_code=0, command="server-copy",
                        summary="no [scan] server_dirs: add the Python server package to scan it",
                        data={"rows": []})
    root = Path(cfg.root)
    rows = []
    server_only = type("C", (), {"root": cfg.root, "scan_src_dirs": [],
                                 "scan_server_dirs": cfg.scan_server_dirs,
                                 "scan_exclude": getattr(cfg, "scan_exclude", []),
                                 "scan_unskip": getattr(cfg, "scan_unskip", [])})()
    for path in source_files(server_only, server=True):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        rows += [{"file": rel, "line": s.line, "text": s.text, "sink": s.sink}
                 for s in server_strings(text)]
    lines = [f"{r['file']}:{r['line']}  [{r['sink']}]  {r['text']}" for r in rows]
    return OpResult(ok=True, exit_code=0, command="server-copy",
                    summary=f"{len(rows)} people-facing string(s) in server code",
                    lines=lines, data={"rows": rows})
