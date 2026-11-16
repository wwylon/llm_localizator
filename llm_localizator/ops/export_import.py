"""Export and import operations."""

from __future__ import annotations

import base64
from contextlib import nullcontext

from ..catalog.import_formats import detect_format, explode_import_file, format_import_report, import_documents, load_catalog
from ..catalog.export_formats import format_export_report, render_export
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.io import decode_import_bytes
from ..projects import ProjectConfig
from .types import ExportRequest, ImportRequest, OpResult, resolve_namespaces


def _export_files(cfg, req: ExportRequest) -> OpResult:
    """Markdown (and other file) export is the file itself, not a key table."""
    from ..projects.collections import (
        get_collection,
        list_collection_files,
        read_collection_file,
    )

    try:
        coll = get_collection(cfg, req.collection)
        locales = req.locales or list(cfg.targets)
        rows = list_collection_files(cfg, coll.name, locales)
    except ValueError as exc:
        return OpResult(ok=False, exit_code=64, command="export", summary=str(exc))
    files = []
    lines = [f"{coll.name}: {len(rows)} file(s)"]
    for row in rows:
        for locale in locales:
            text = read_collection_file(cfg, coll.name, locale, row["path"])
            if locale != cfg.source_locale and not text:
                continue
            files.append({"locale": locale, "path": row["path"], "text": text})
            lines.append(f"{locale}/{row['path']}")
    return OpResult(
        ok=True,
        exit_code=0,
        command="export",
        summary=f"{coll.name}: {len(files)} file(s)",
        lines=lines,
        data={"collection": coll.name, "files": files, "format": coll.format},
    )


def op_export(cfg: ProjectConfig, req: ExportRequest) -> OpResult:
    if req.collection and req.collection != "messages":
        return _export_files(cfg, req)
    catalog = load_catalog(cfg)
    locales = req.locales or list(cfg.targets)
    namespaces = resolve_namespaces(req.namespace, req.namespaces)
    fmt = req.fmt or "csv"
    screenshots = bool(req.screenshots) or fmt == "zip"
    if fmt == "zip":
        fmt = "csv"
    try:
        body, content_type, filename, report = render_export(
            cfg, catalog, locales=locales, namespaces=namespaces,
            fmt=fmt, layout=req.layout or "single", only=req.only or "all",
            screenshots=screenshots, file_count=req.file_count,
            approved_only=req.approved_only,
            xliff_version=req.xliff_version or "1.2", bom=bool(req.bom),
        )
    except ValueError as exc:
        return OpResult(
            ok=False, exit_code=1, command="export", summary=str(exc),
        )
    lines = format_export_report(report)
    data: dict = {
        "format": fmt,
        "filename": filename,
        "content_type": content_type,
        "report": report,
    }
    if content_type.startswith("text/") or content_type.startswith("application/xliff") or content_type.startswith("application/json"):
        data["text"] = body.decode("utf-8")
    else:
        data["binary"] = True
    return OpResult(
        ok=True,
        exit_code=0,
        command="export",
        summary=lines[0] if lines else "exported",
        lines=lines,
        data=data,
    )


def _documents_from_request(req: ImportRequest) -> tuple[list[tuple[str, str]], list[str]]:
    docs: list[tuple[str, str]] = []
    problems: list[str] = []
    if req.files:
        for item in req.files:
            if not isinstance(item, dict):
                problems.append("import file entry is not an object")
                continue
            name = str(item.get("name") or "handoff")
            raw = None
            text = item.get("text")
            if item.get("base64"):
                try:
                    raw = base64.b64decode(item["base64"], validate=True)
                except (ValueError, TypeError):
                    problems.append(f"{name}: could not read file bytes")
                    continue
                if len(raw) > 8 * 1024 * 1024:
                    problems.append(f"{name}: file exceeds 8 MiB")
                    continue
                if not name.lower().endswith((".zip", ".xlsx", ".xls")):
                    text = decode_import_bytes(raw)
                    raw = None
            elif isinstance(text, str) and len(text.encode("utf-8")) > 8 * 1024 * 1024:
                problems.append(f"{name}: file exceeds 8 MiB")
                continue
            expanded, error = explode_import_file(
                name, text=None if raw is not None else (text or ""), raw=raw,
            )
            if error:
                problems.append(error)
                continue
            docs.extend(expanded)
    elif req.text:
        kind = detect_format("paste", req.text, req.fmt if req.fmt in {"csv", "xliff", "json"} else None)
        suffix = {"xliff": ".xliff", "json": ".json"}.get(kind, ".csv")
        docs.append((f"paste{suffix}", req.text))
    return docs, problems


def op_import(cfg: ProjectConfig, req: ImportRequest) -> OpResult:
    catalog = load_catalog(cfg)
    docs, problems = _documents_from_request(req)
    model = req.model or "import"
    if problems:
        result = {
            "ok": False,
            "accepted": 0,
            "unchanged": 0,
            "rejected": 0,
            "skipped": 0,
            "errors": [{"file": "import", "error": problem} for problem in problems],
            "changes": [],
            "coverage": [],
            "files": [
                {"name": name, "structural": None, "accepted": 0, "unchanged": 0,
                 "rejected": 0, "skipped": 0}
                for name, _text in docs
            ] + [
                {"name": "import", "structural": problem, "accepted": 0,
                 "unchanged": 0, "rejected": 0, "skipped": 0}
                for problem in problems
            ],
            "structural": "; ".join(problems),
            "applied": False,
            "blocked": True,
            "model": model,
            "provider": "import",
        }
    elif not docs:
        result = {
            "ok": False,
            "accepted": 0,
            "unchanged": 0,
            "rejected": 0,
            "skipped": 0,
            "errors": [{"file": "import", "error": "no file to import"}],
            "changes": [],
            "coverage": [],
            "files": [{"name": "import", "structural": "no file to import",
                       "accepted": 0, "unchanged": 0, "rejected": 0, "skipped": 0}],
            "structural": "no file to import",
            "applied": False,
            "blocked": True,
            "model": model,
            "provider": "import",
        }
    else:
        lock_cm = nullcontext() if req.dry_run else project_mutation_lock(cfg)
        with lock_cm:
            result = import_documents(
                cfg, catalog, docs,
                locales=req.locales, dry_run=req.dry_run,
                model=model,
                fmt=req.fmt if req.fmt in {"csv", "xliff", "json"} else None,
            )
    lines = format_import_report(result)
    if result.get("structural"):
        summary = str(result["structural"])
    else:
        summary = (
            f"{result.get('accepted', 0)} written, "
            f"{result.get('unchanged', 0)} unchanged, "
            f"{result.get('rejected', 0)} rejected, "
            f"{result.get('skipped', 0)} skipped"
        )
    if req.dry_run and not result.get("blocked"):
        summary += " (dry-run)"
    return OpResult(
        ok=bool(result.get("ok")),
        exit_code=0 if result.get("ok") else 1,
        command="import",
        summary=summary,
        lines=lines,
        data=result,
    )
