"""Export and import translation catalogues."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from ..catalog.export_formats import format_export_report, render_export
from ..catalog.import_formats import format_import_report
from ..catalog.io import decode_import_bytes
from ..ops.export_import import op_import
from ..ops.types import ImportRequest
from ..projects import resolve


def export_cmd(args) -> int:
    cfg = resolve(args.project, args.config)
    collection = getattr(args, "collection", None)
    if collection and collection != "messages":
        from ..ops.export_import import op_export
        from ..ops.types import ExportRequest

        result = op_export(cfg, ExportRequest(
            locales=args.locales,
            collection=collection,
            fmt=getattr(args, "format", "csv") or "csv",
        ))
        if result.summary:
            print(result.summary)
        for line in result.lines:
            print(line)
        out = getattr(args, "out", None)
        if out and result.ok:
            dest = Path(out)
            dest.mkdir(parents=True, exist_ok=True)
            for item in result.data.get("files", []):
                path = dest / item["locale"] / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(item["text"], encoding="utf-8")
            print(f"wrote files under {dest}")
        return result.exit_code
    from ..catalog.import_formats import load_catalog

    catalog = load_catalog(cfg)
    locales = args.locales or list(cfg.targets)
    namespaces = [args.namespace] if getattr(args, "namespace", None) else None
    fmt = getattr(args, "format", "csv") or "csv"
    layout = getattr(args, "layout", "single") or "single"
    screenshots = bool(getattr(args, "screenshots", False)) or fmt == "zip"
    if fmt == "zip":
        fmt = "csv"
    only = getattr(args, "only", "all") or "all"
    file_count = getattr(args, "file_count", 1) or 1
    try:
        body, content_type, filename, report = render_export(
            cfg, catalog, locales=locales, namespaces=namespaces,
            fmt=fmt, layout=layout, only=only, screenshots=screenshots,
            file_count=file_count,
            xliff_version=getattr(args, "xliff_version", "1.2") or "1.2",
            bom=bool(getattr(args, "bom", False)),
            approved_only=bool(getattr(args, "approved_only", False)),
        )
    except ValueError as exc:
        print(f"export: {exc}", file=sys.stderr)
        return 1
    report_lines = format_export_report(report)
    packed = content_type == "application/zip"
    out: Path | None = args.out
    if packed and out is None:
        print(
            "export: --out is required for a split export or screenshots "
            "(a .zip file or a directory)",
            file=sys.stderr,
        )
        return 2
    if out is None and fmt == "xlsx":
        print("export: --out is required for xlsx (a binary file)", file=sys.stderr)
        return 2
    if out is None:
        sys.stdout.write(body.decode("utf-8"))
        _write_export_report(args, report, report_lines)
        return 0
    if packed and out.suffix.lower() != ".zip":
        out.mkdir(parents=True, exist_ok=True)
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            zf.extractall(out)
        print(f"export: wrote {out}", file=sys.stderr)
        _write_export_report(args, report, report_lines)
        return 0
    target = out / filename if out.is_dir() else out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    print(f"export: wrote {target}", file=sys.stderr)
    _write_export_report(args, report, report_lines)
    return 0


def _write_export_report(args, report: dict, lines: list[str]) -> None:
    print("\n".join(lines), file=sys.stderr)
    report_path = getattr(args, "report", None)
    if not report_path:
        return
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"report: {report_path}", file=sys.stderr)


def import_cmd(args) -> int:
    cfg = resolve(args.project, args.config)
    paths = args.file if isinstance(args.file, list) else [args.file]
    files: list[dict] = []
    for path in paths:
        raw = path.read_bytes()
        name = path.name
        if name.lower().endswith((".zip", ".xlsx", ".xls")):
            files.append({
                "name": name,
                "base64": base64.b64encode(raw).decode("ascii"),
            })
        else:
            files.append({"name": name, "text": decode_import_bytes(raw)})
    fmt = getattr(args, "format", None) or "csv"
    result_op = op_import(cfg, ImportRequest(
        files=files,
        locales=args.locales,
        fmt=fmt,
        dry_run=bool(args.dry_run),
        model=getattr(args, "model", None) or "import",
    ))
    result = result_op.data
    report_path = getattr(args, "report", None)
    if report_path:
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    lines = result_op.lines or format_import_report(result)
    stream = sys.stdout if result_op.ok else sys.stderr
    print("\n".join(lines), file=stream)
    if report_path:
        print(f"report: {report_path}", file=stream)
    return result_op.exit_code
