"""Scan operation."""

from __future__ import annotations

import json
from collections import Counter

from ..catalog.io import atomic_write_text
from .scan_surfaces import mode_of, surface_of, unknown_names
from ..projects import ProjectConfig
from ..scan import scanner_from_config
from .types import OpResult, ScanRequest
from ..projects.paths import project_path


SHOW_LIMIT = 100


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

    surfaces = cfg.scan_surfaces
    wanted = {s.strip() for s in (req.surface or "").split(",") if s.strip()}
    bad = unknown_names(surfaces, wanted)
    if bad:
        return OpResult(
            ok=False, exit_code=64, command="scan",
            summary=f"unknown scan surface(s): {', '.join(bad)}",
            lines=[f"Defined surfaces: {', '.join(sorted(surfaces)) or 'none'} (plus 'other')."],
        )

    rows = []
    ignored = 0
    for h in result.hardcoded:
        name = surface_of(surfaces, h.file)
        mode = mode_of(surfaces, name)
        if wanted and name not in wanted:
            continue
        if mode == "ignore":
            ignored += 1
            continue
        rows.append((h, name, mode))

    hardcoded = [
        {"text": h.text, "file": h.file, "line": h.line, "reason": h.reason,
         "confidence": h.confidence, "surface": name, "mode": mode}
        for h, name, mode in rows
    ]
    by_conf = Counter(h.confidence for h, _, _ in rows)
    by_surface: Counter[str] = Counter(name for _, name, _ in rows)
    to_fix = sum(1 for _, _, mode in rows if mode == "fix")

    lines = [
        f"scanned {result.files_scanned} file(s): {len(result.usages)} key reference(s) "
        f"across {len(result.by_namespace())} namespace(s), "
        f"{len(rows)} hardcoded string(s)",
    ]
    if rows:
        lines.append("by confidence: " + ", ".join(
            f"{c}={by_conf[c]}" for c in ("high", "medium", "low") if by_conf[c]))
    if surfaces or ignored:
        parts = [f"{name} [{mode_of(surfaces, name)}]={n}" for name, n in sorted(by_surface.items())]
        if ignored:
            parts.append(f"ignored surfaces={ignored}")
        lines.append("by surface: " + ", ".join(parts))
        lines.append(f"to fix: {to_fix}; report only: {len(rows) - to_fix}")
    if written:
        lines.append(f"wrote {written} usage artefact(s) to {out_dir}")
    shown = rows[:SHOW_LIMIT]
    for h, name, _ in shown:
        tag = f"[{name}] " if surfaces else ""
        lines.append(f"warn  {h.file}:{h.line}  {tag}{h.text!r} -- {h.reason}")
    if len(rows) > len(shown):
        lines.append(f"... showing the first {len(shown)} of {len(rows)}; "
                     "use --format json (or --surface NAME) to see all of them")

    exit_code = 1 if (req.strict and to_fix) else 0
    return OpResult(
        ok=exit_code == 0,
        exit_code=exit_code,
        command="scan",
        summary=(
            f"{len(rows)} hardcoded string(s), "
            f"{len(result.usages)} usage(s)"
        ),
        lines=lines,
        data={
            "filesScanned": result.files_scanned,
            "usages": len(result.usages),
            "namespaces": sorted(result.by_namespace()),
            "hardcoded": hardcoded,
            "byConfidence": dict(by_conf),
            "bySurface": dict(by_surface),
            "toFix": to_fix,
            "ignoredBySurface": ignored,
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
    from ..scan.base import relative_posix, split_lines

    problems: list[str] = []
    files = {relative_posix(p, scanner.root): p for p in scanner.iter_files()}
    for rel in sorted(set(files) | set(by_file)):
        path = files.get(rel) or scanner.root / rel
        try:
            lines = split_lines(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        problems += [f"{rel}:{p}" for p in lint_directives(lines, by_file.get(rel, []),
                                                           scanner.directive_aliases)]
    return OpResult(
        ok=not problems, exit_code=1 if problems else 0, command="scan",
        summary=f"{len(problems)} directive problem(s)", lines=problems or ["no directive problems"],
        data={"problems": problems},
    )
