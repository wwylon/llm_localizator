"""Glossary CSV/TBX import and export. Parse the whole file before any write."""

from __future__ import annotations


from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.glossary_exchange import export_csv, export_tbx, parse_csv, parse_tbx
from ..projects import ProjectConfig, load_glossary
from ..projects.glossary_edit import import_glossary_records
from .types import GlossaryExportRequest, GlossaryImportRequest, OpResult
from ..projects.paths import project_path

__all__ = ["op_glossary_export", "op_glossary_import"]


def op_glossary_export(cfg: ProjectConfig, req: GlossaryExportRequest) -> OpResult:
    fmt = (req.format or "csv").lower()
    if fmt not in {"csv", "tbx"}:
        return _fail("glossary-export", f"unknown format {fmt!r}")
    glossary = load_glossary(cfg.glossary_path)
    text = export_tbx(glossary, source_locale=cfg.source_locale) if fmt == "tbx" else export_csv(glossary)
    if req.file:
        dest = project_path(cfg.root, req.file)
        if not dest.is_absolute():
            dest = cfg.root / dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        summary = f"wrote {dest}"
    else:
        summary = f"glossary {fmt}"
    return OpResult(
        ok=True, exit_code=0, command="glossary-export", summary=summary,
        lines=[summary], data={"format": fmt, "text": text},
    )


def op_glossary_import(cfg: ProjectConfig, req: GlossaryImportRequest) -> OpResult:
    if req.dry_run:
        return _op_glossary_import(cfg, req)
    with project_mutation_lock(cfg):
        return _op_glossary_import(cfg, req)


def _op_glossary_import(cfg: ProjectConfig, req: GlossaryImportRequest) -> OpResult:
    fmt = (req.format or "").lower()
    path_label = req.file or "upload"
    if req.text:
        text = req.text
        if not fmt:
            fmt = "tbx" if path_label.lower().endswith(".tbx") else "csv"
    elif req.file:
        src = project_path(cfg.root, req.file)
        if not src.is_absolute():
            src = cfg.root / src
        path_label = str(src)
        if not src.is_file():
            return _fail("glossary-import", f"{src}: file not found")
        text = src.read_text(encoding="utf-8")
        if not fmt:
            fmt = "tbx" if src.suffix.lower() == ".tbx" else "csv"
    else:
        return _fail("glossary-import", "glossary-import needs a file")
    if fmt not in {"csv", "tbx"}:
        return _fail("glossary-import", f"unknown format {fmt!r}")
    try:
        if fmt == "tbx":
            records = parse_tbx(text, path=path_label, source_locale=cfg.source_locale)
        else:
            records = parse_csv(text, path=path_label)
        counts = import_glossary_records(
            cfg.glossary_path, records,
            conflict=req.conflict or "skip",
            dry_run=bool(req.dry_run),
        )
    except ValueError as exc:
        return _fail("glossary-import", str(exc))
    summary = (
        f"glossary import {fmt}: applied={counts['applied']} "
        f"skipped={counts['skipped']}"
        + (" (dry-run)" if counts["dry_run"] else "")
    )
    return OpResult(
        ok=True, exit_code=0, command="glossary-import", summary=summary,
        lines=[summary], data=counts,
    )


def _fail(command: str, summary: str) -> OpResult:
    return OpResult(ok=False, exit_code=1, command=command, summary=summary, lines=[summary])
