"""Scan operation."""

from __future__ import annotations

import json

from ..catalog.io import atomic_write_text
from ..projects import ProjectConfig
from ..scan import scanner_from_config
from .types import OpResult, ScanRequest
from ..projects.paths import project_path


def op_scan(cfg: ProjectConfig, req: ScanRequest) -> OpResult:
    adapter = req.adapter or cfg.scan_adapter
    if not adapter:
        return OpResult(
            ok=False,
            exit_code=64,
            command="scan",
            summary="no scan adapter configured",
            lines=["Set [scan] adapter in .llm-localize.toml or pass adapter."],
        )
    if not cfg.scan_src_dirs:
        return OpResult(
            ok=False,
            exit_code=64,
            command="scan",
            summary="no [scan] src_dirs configured",
            lines=[],
        )

    scanner = scanner_from_config(cfg, adapter)
    if req.lint_directives:
        return _lint(cfg, scanner)
    result = scanner.scan()

    out_dir = project_path(cfg.root, req.out_dir) or cfg.scan_out_root()
    written = 0
    if out_dir and not req.no_write:
        out_dir.mkdir(parents=True, exist_ok=True)
        for namespace, keys in result.by_namespace().items():
            path = out_dir / f"{namespace}.json"
            atomic_write_text(path, json.dumps(keys, ensure_ascii=False, indent=2) + "\n")
            written += 1

    hardcoded = [
        {"text": h.text, "file": h.file, "line": h.line, "reason": h.reason}
        for h in result.hardcoded
    ]
    lines = [
        f"scanned {result.files_scanned} file(s): {len(result.usages)} key reference(s) "
        f"across {len(result.by_namespace())} namespace(s), "
        f"{len(result.hardcoded)} hardcoded string(s)",
    ]
    if written:
        lines.append(f"wrote {written} usage artefact(s) to {out_dir}")
    for h in result.hardcoded[:100]:
        lines.append(f"warn  {h.file}:{h.line}  {h.text!r} -- {h.reason}")

    exit_code = 1 if (req.strict and result.hardcoded) else 0
    return OpResult(
        ok=exit_code == 0,
        exit_code=exit_code,
        command="scan",
        summary=(
            f"{len(result.hardcoded)} hardcoded string(s), "
            f"{len(result.usages)} usage(s)"
        ),
        lines=lines,
        data={
            "filesScanned": result.files_scanned,
            "usages": len(result.usages),
            "namespaces": sorted(result.by_namespace()),
            "hardcoded": hardcoded,
            "artefactsWritten": written,
        },
    )


def _lint(cfg: ProjectConfig, scanner) -> OpResult:
    """Report stale or malformed in-code directives (ADR-106). Exit 1 when any."""
    from ..scan.directives import lint_directives

    scanner.apply_directives = False
    result = scanner.scan()
    by_file: dict[str, list] = {}
    for hit in result.hardcoded:
        by_file.setdefault(hit.file, []).append(hit)
    problems: list[str] = []
    files = {p.relative_to(scanner.root).as_posix(): p for p in scanner.iter_files()}
    for rel in sorted(set(files) | set(by_file)):
        path = files.get(rel) or scanner.root / rel
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        problems += [f"{rel}:{p}" for p in lint_directives(lines, by_file.get(rel, []),
                                                           scanner.directive_aliases)]
    return OpResult(
        ok=not problems, exit_code=1 if problems else 0, command="scan",
        summary=f"{len(problems)} directive problem(s)", lines=problems or ["no directive problems"],
        data={"problems": problems},
    )
