"""Why one source line was or was not reported by the hardcoded-string scanner (M6, ADR-154).

``llm-localizator explain-scan app/views.py:42`` walks the same steps as a scan, for one file: path skip rules and
``[scan] exclude``, file type, minified/unreadable files, the file's scanner, brand names and ignore directives. For a
line with no hit, each quoted literal on it gets the first filter that rejects it (translation call, API/enum token,
not prose). People use it to understand a report; agents use the JSON to decide between a fix and a directive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["ExplainScanRequest", "op_explain_scan", "explain_line"]

_QUOTED = re.compile(r"""(["'`])((?:\\.|(?!\1)[^\\\n])*)\1""")


@dataclass
class ExplainScanRequest:
    target: str = ""            # ``path:line`` (``path`` alone explains every hit in the file)
    adapter: str | None = None


def _split_target(target: str) -> tuple[str, int | None]:
    m = re.fullmatch(r"(.+?):(\d+)", target.strip())
    if m:
        return m.group(1), int(m.group(2))
    return target.strip(), None


def _literal_verdict(text: str, line: str) -> str:
    from ..scan.literals import _ROUTED_ARG
    from ..scan.negatives import is_non_ui_literal
    from ..scan.prose import is_prose

    if any(text == (m.group(2) or m.group(4)) for m in _ROUTED_ARG.finditer(line)):
        return "inside a translation call: already routed"
    if not text.strip() or not any(ch.isalpha() for ch in text):
        return "no letters: not text"
    if is_non_ui_literal(text):
        return "API/enum token, CSS, SQL or path data (negatives filter)"
    if not is_prose(text):
        return "not prose: one word, an identifier or a key (reported only in a known UI position)"
    return "prose, but no rule for this position reported it (not a known UI sink, or a log/debug call)"


def explain_line(cfg: ProjectConfig, rel: str, line: int | None, adapter: str | None = None) -> dict:
    """Machine-readable explanation for *rel* (relative to the project root) and optional 1-based *line*."""
    from ..core.languages import language_for_suffix
    from ..scan import scanner_from_config
    from ..scan.base import ScanResult, drop_brand_hits, path_is_skipped, read_source_lines
    from ..scan.usage_calls import EXTRA_ROUTED

    root = Path(cfg.root)
    path = (root / rel).resolve()
    out: dict = {"file": rel, "line": line, "steps": [], "hits": [], "literals": []}
    steps = out["steps"]
    try:
        rel = path.relative_to(root.resolve()).as_posix()
        out["file"] = rel
    except ValueError:
        steps.append({"step": "path", "verdict": "outside the project root"})
        return out
    if not path.is_file():
        steps.append({"step": "path", "verdict": "no such file"})
        return out
    scanner = scanner_from_config(cfg, adapter)
    src_dirs = [d for d in scanner.src_dirs if d in (".", "") or rel == d or rel.startswith(d.rstrip("/") + "/")]
    if not src_dirs:
        steps.append({"step": "src_dirs", "verdict": f"not under [scan] src_dirs {list(scanner.src_dirs)}"})
        return out
    if path_is_skipped(path, exclude=scanner.exclude, unskip=scanner.unskip, root=root):
        steps.append({"step": "skip", "verdict": "skipped: docs/tests/tooling folder or [scan] exclude ([scan] unskip "
                                                 "brings soft-skipped folders back)"})
        return out
    lang = language_for_suffix(path.suffix)
    if lang is None and path.suffix.lower() not in (".txt", ".yml", ".yaml"):
        steps.append({"step": "language", "verdict": f"no scanner reads {path.suffix or 'extension-less'} files"})
        return out
    steps.append({"step": "language", "verdict": lang.id if lang else path.suffix.lower()[1:]})
    result = ScanResult()
    lines = read_source_lines(path, result, rel)
    if lines is None:
        steps.append({"step": "read", "verdict": (result.skipped or result.unreadable or ["unreadable"])[-1]})
        return out
    token = EXTRA_ROUTED.set(frozenset(scanner.t_functions))
    try:
        scanner.scan_file(path, lines, result)
        if lang is not None and lang.detector == "literal" and not result.hardcoded:
            from ..scan.literals import scan_literal_file

            scan_literal_file(scanner, path, lines, result)
    finally:
        EXTRA_ROUTED.reset(token)
    raw = list(result.hardcoded)
    drop_brand_hits(result, root)
    branded = [h for h in raw if h not in result.hardcoded]
    kept = list(result.hardcoded)
    suppressed: list = []
    if scanner.apply_directives:
        from ..scan.directives import apply_directives

        kept, _ = apply_directives(lines, kept, scanner.directive_aliases, rel)
        suppressed = [h for h in result.hardcoded if h not in kept]
    for hit, state in [*((h, "reported") for h in kept), *((h, "brand name: dropped") for h in branded),
                       *((h, "suppressed by an ignore directive") for h in suppressed)]:
        if line is None or hit.line == line:
            out["hits"].append({"line": hit.line, "text": hit.text, "confidence": hit.confidence,
                                "reason": hit.reason, "state": state})
    if line is not None and 1 <= line <= len(lines):
        source = lines[line - 1]
        out["source"] = source.strip()
        hit_texts = {h["text"] for h in out["hits"]}
        for m in _QUOTED.finditer(source):
            text = m.group(2)
            if text and text not in hit_texts:
                out["literals"].append({"text": text, "verdict": _literal_verdict(text, source)})
    return out


def op_explain_scan(cfg: ProjectConfig, req: ExplainScanRequest) -> OpResult:
    if not req.target.strip():
        return OpResult(False, 2, "explain-scan", "give a file, or file:line", data={})
    rel, line = _split_target(req.target)
    try:
        data = explain_line(cfg, rel, line, req.adapter)
    except ValueError as exc:   # unknown adapter
        return OpResult(False, 2, "explain-scan", str(exc), data={})
    lines = [f"{data['file']}:{data['line']}" if data["line"] else data["file"]]
    lines += [f"  {s['step']}: {s['verdict']}" for s in data["steps"]]
    if data.get("source"):
        lines.append(f"  source: {data['source']}")
    for hit in data["hits"]:
        why = hit["reason"] or ("prose literal outside any known UI sink" if hit["confidence"] == "low" else "")
        lines.append(f"  hit L{hit['line']} [{hit['confidence']}] {hit['text']!r}: {hit['state']}" + (f" - {why}" if why else ""))
    for lit in data["literals"]:
        lines.append(f"  not reported {lit['text']!r}: {lit['verdict']}")
    if not data["hits"] and not data["literals"] and len(data["steps"]) <= 1:
        lines.append("  no quoted text on this line" if data.get("source") is not None else "  nothing reported")
    reported = sum(1 for h in data["hits"] if h["state"] == "reported")
    summary = f"{reported} reported hit(s)" if data["steps"] and data["steps"][-1]["step"] == "language" else (
        data["steps"][-1]["verdict"] if data["steps"] else "")
    return OpResult(True, 0, "explain-scan", summary, lines=lines, data=data)
