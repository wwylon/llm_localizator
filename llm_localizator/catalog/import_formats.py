"""Import-side helpers for translation catalogue handoff."""

from __future__ import annotations

import csv
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .xlsx_exchange import xlsx_to_csv_text
from .xml_safe import xml_fromstring
from ..catalog import Catalog, catalog_for
from ..catalog.io import decode_import_bytes
from ..catalog.state import (
    is_translated_value,
    translation_status,
)
from ..core.standards import get_standard
from ..core.script_checks import foreign_script_hard_gate
from ..core.validate import ValidationFailure, validate_translation_detailed
from ..projects import ContextNotes, ProjectConfig, GlossaryCache
from ..pipeline.recording import provenance_stores, record_candidate
from .export_formats import (
    _fieldnames,
    _expected_width,
    _show,
    _apply_xliff_notes,
    _parse_unit_id,
    _xliff_note_text,
)

_IMPORT_SUFFIXES = {".csv", ".json", ".xliff", ".xlf", ".xlsx"}


def _coverage_snapshot(cfg: ProjectConfig, catalog: Catalog, locales: list[str]) -> list[dict]:
    from ..catalog.state import is_translated_value
    ns_list = cfg.namespaces_for(catalog)
    out = []
    for loc in locales:
        translated = total = 0
        for ns in ns_list:
            source = catalog.load(cfg.source_locale, ns)
            target = catalog.load(loc, ns)
            for key, src in source.items():
                if cfg.is_skipped(ns, key, src):
                    continue
                total += 1
                raw = target.get(key)
                if is_translated_value(src, raw if isinstance(raw, str) else None):
                    translated += 1
        out.append({
            "locale": loc, "before": translated, "after": translated, "total": total,
        })
    return out


def _empty_counters() -> dict:
    return {
        "accepted": 0,
        "unchanged": 0,
        "rejected": 0,
        "skipped": 0,
        "errors": [],
        "changes": [],
        "positional": False,
    }


def _file_result(
    filename: str,
    counters: dict,
    *,
    model: str,
    coverage: list[dict],
    structural: str | None = None,
    applied: bool = False,
) -> dict:
    name = filename or "import"
    file_row = {
        "name": name,
        "accepted": counters["accepted"],
        "unchanged": counters["unchanged"],
        "rejected": counters["rejected"],
        "skipped": counters["skipped"],
        "positional": bool(counters.get("positional")),
        "structural": structural,
    }
    result = {
        "ok": False,
        "accepted": counters["accepted"],
        "unchanged": counters["unchanged"],
        "rejected": counters["rejected"],
        "skipped": counters["skipped"],
        "errors": counters["errors"],
        "changes": counters["changes"],
        "coverage": coverage,
        "files": [file_row],
        "positional": bool(counters.get("positional")),
        "structural": structural,
        "applied": applied,
        "blocked": bool(structural),
        "model": model,
        "provider": "import",
    }
    result["ok"] = _result_ok(result)
    return result


def _result_ok(result: dict) -> bool:
    if result.get("blocked") or result.get("structural"):
        return False
    if result.get("rejected"):
        return False
    if not result.get("accepted"):
        return False
    return True


def _structural(filename: str, message: str, model: str) -> dict:
    counters = _empty_counters()
    return _file_result(filename, counters, model=model, coverage=[], structural=message)


def _strip_bom(text: str) -> str:
    """Drop a UTF-8 BOM, including one that sits after leading blank lines."""
    if text.startswith("﻿"):
        return text[1:]
    index = 0
    while index < len(text) and text[index] in "\r\n":
        index += 1
    if index and text[index:index + 1] == "﻿":
        return text[index + 1:]
    return text


_STATUS_TOKENS = {
    "", "missing", "stale", "untranslated", "intentional", "machine",
    "llm_reviewed", "human", "needs_better_model",
}


def _looks_like_score(cell: str) -> bool:
    text = (cell or "").strip()
    if not text:
        return True
    try:
        float(text)
    except ValueError:
        return False
    return True


def _positional_row(cells: list[str], locale: str) -> dict | None:
    """Map one headerless row onto export columns.

    A row whose translation or note contains an unquoted comma is wider than
    the export. Continuations of the translation start with whitespace; the
    note, when present, does not. Status and score stay at the end and are
    not imported.
    """
    if len(cells) < 4:
        return None
    expect = _expected_width(1)
    if len(cells) == expect:
        columns = _fieldnames([locale])
        return {columns[i]: cells[i] if i < len(columns) else "" for i in range(len(columns))}
    body = cells
    if (
        len(cells) >= 6
        and _looks_like_score(cells[-1])
        and cells[-2].strip() in _STATUS_TOKENS
    ):
        body = cells[:-2]
    if len(body) < 4:
        return None
    parts = [body[3]]
    note_taken = False
    for cell in body[4:]:
        stripped = (cell or "").strip()
        # Reject rows where a status token appears in an unexpected column: it
        # indicates the file has a different structure than a headerless export.
        if not note_taken and stripped in _STATUS_TOKENS and stripped:
            return None
        if not note_taken and cell[:1].isspace():
            # Continuation of a translation that contained an unquoted comma.
            parts.append(cell)
            continue
        if not note_taken:
            # Note slot: discarded on import because a note and a truncated
            # translation have the same shape without a header column.
            note_taken = True
            continue
        if stripped:
            return None
    return {
        "namespace": cells[0],
        "key": cells[1],
        "source": cells[2],
        locale: ",".join(parts),
    }


def _merge_overflow(
    cells: list[str], header: list[str], locales: list[str] | None, targets_known: set[str],
) -> list[str] | None:
    """Rejoin a translation whose unquoted commas made the row wider than the header.

    Only when exactly one locale column is in play and every extra cell starts with
    whitespace (``", uruchom ..."``), the same rule ``_positional_row`` uses. Anything else is
    ambiguous, so the caller rejects the row instead of guessing.
    """
    cols = list(locales) if locales else [c for c in header if c in targets_known]
    if len(cols) != 1 or cols[0] not in header:
        return None
    j = header.index(cols[0])
    extra = len(cells) - len(header)
    tail = cells[j + 1 : j + 1 + extra]
    if len(tail) != extra or not all(cell[:1].isspace() for cell in tail):
        return None
    return cells[:j] + [",".join(cells[j : j + 1 + extra])] + cells[j + 1 + extra :]


_FORMULA_TRIGGERS = frozenset({"=", "+", "@", "\t", "\r"})


def _parse_csv_table(
    text: str,
    locales: list[str] | None,
    targets_known: set[str],
) -> tuple[list[tuple[int, dict]], list[str], bool, bool, str | None]:
    """Return rows, locales, positional flag, repaired flag, structural error."""
    text = _strip_bom(text)
    parsed: list[tuple[int, list[str]]] = []
    for line_no, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        # Undo export's formula-injection guard so a round trip is lossless.
        row = [
            cell[1:] if cell[:1] == "'" and cell[1:2] in _FORMULA_TRIGGERS else cell
            for cell in row
        ]
        parsed.append((line_no, row))
    while parsed and not any((cell or "").strip() for cell in parsed[0][1]):
        parsed.pop(0)
    if not parsed:
        return [], [], False, False, "empty file"
    header = [(cell or "").strip() for cell in parsed[0][1]]
    header_lower = [c.lower() for c in header]
    if "namespace" in header_lower and "key" in header_lower:
        rows: list[tuple[int, dict]] = []
        for line_no, cells in parsed[1:]:
            if not any((cell or "").strip() for cell in cells):
                continue
            merged = None
            if len(cells) > len(header):
                merged = _merge_overflow(cells, header, locales, targets_known)
                if merged is None:
                    rows.append((line_no, {
                        "__error__": (
                            f"row has {len(cells)} cells but the header has {len(header)}: "
                            "quote every field that contains a comma"
                        ),
                    }))
                    continue
            use = merged if merged is not None else cells
            data = {
                header[i]: (use[i] if i < len(use) else "")
                for i in range(len(header))
            }
            if merged is not None:
                data["__merged__"] = True
            rows.append((line_no, data))
        resolved = list(locales) if locales else [col for col in header if col in targets_known]
        if not resolved:
            return [], [], False, False, "select the locale this file is for"
        return rows, resolved, False, False, None

    if not locales or len(locales) != 1:
        return [], [], True, False, (
            "this file has no header; select exactly one locale "
            "(the language of the translation column)"
        )
    data_rows = [row for row in parsed if any((cell or "").strip() for cell in row[1])]
    if not data_rows:
        return [], [], True, False, "empty file"
    widths = {len(row[1]) for row in data_rows}
    expect = _expected_width(1)
    rows = []
    repaired = False
    for line_no, cells in data_rows:
        if len(cells) != expect:
            repaired = True
        data = _positional_row(cells, locales[0])
        if data is None:
            return [], [], True, False, (
                f"line {line_no} has {len(cells)} columns and could not be mapped "
                f"to a one-locale export (expected {expect}, or a translation "
                "whose extra commas are unquoted)"
            )
        rows.append((line_no, data))
    return rows, list(locales), True, repaired and widths != {expect}, None


def _max_chars(row: dict) -> int | None:
    raw = str(row.get("maxChars") or "").strip()
    return int(raw) if raw.isdigit() else None


def _consume_rows(
    cfg: ProjectConfig,
    catalog: Catalog,
    rows: list[tuple[int, dict]],
    locales: list[str],
    *,
    filename: str,
    model: str,
    trigger: str,
    dry_run: bool,
    positional: bool,
) -> dict:
    glossary_cache = GlossaryCache(
        cfg.glossary_path,
        shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )
    notes = ContextNotes(cfg.context_dir)
    stores = provenance_stores(cfg)
    state, history, scores = stores.state, stores.history, stores.scores
    counters = _empty_counters()
    counters["positional"] = positional
    pending: dict[tuple[str, str], dict[str, str]] = {}
    overlay: dict[tuple[str, str, str], str] = {}
    coverage = _coverage_snapshot(cfg, catalog, locales)
    by_loc = {row["locale"]: row for row in coverage}
    name = filename or "import"

    row_sources: dict[str, dict] = {}  # catalogue is not saved mid-loop: load each file once
    row_existing: dict[tuple[str, str], dict] = {}
    for line_no, row in rows:
        if row.get("__error__"):
            counters["rejected"] += 1
            counters["errors"].append({"file": name, "line": line_no, "error": row["__error__"]})
            continue
        ns = str(row.get("namespace") or "").strip()
        key = str(row.get("key") or "").strip()
        if ns not in row_sources:
            row_sources[ns] = catalog.load(cfg.source_locale, ns)
        source_map = row_sources[ns]
        if key not in source_map:
            counters["skipped"] += 1
            counters["errors"].append({
                "file": name, "line": line_no, "key": key, "error": "unknown key",
            })
            continue
        src = source_map[key]
        for loc in locales:
            raw = row.get(loc)
            if raw is None or not str(raw).strip():
                continue
            value = str(raw).strip()
            if "\\," in value and "\\" not in str(src):
                value = value.replace("\\,", ",")  # an escaped comma from an agent-written CSV
            if (loc, ns) not in row_existing:
                row_existing[(loc, ns)] = catalog.load(loc, ns)
            current = overlay.get((loc, ns, key), row_existing[(loc, ns)].get(key))
            if isinstance(current, str) and current.strip() == value:
                counters["unchanged"] += 1
                continue
            glossary = glossary_cache.get(
                cfg.glossary_domains_for(ns, key_domain=notes.domain(ns, key)),
            )
            ok, failures = validate_translation_detailed(
                src, value, loc, glossary, max_chars=_max_chars(row),
                standard=get_standard(getattr(cfg, "catalog_standard", None)),
            )
            blocking = [f for f in failures if f.severity == "error"]
            gate = foreign_script_hard_gate(value, loc) if ok and not blocking else None
            if gate:
                failures = [*failures, ValidationFailure("V21", gate)]
                blocking = [failures[-1]]
            if not ok or blocking:
                counters["rejected"] += 1
                counters["errors"].append({
                    "file": name, "line": line_no, "locale": loc, "key": key,
                    "errors": [{"id": f.id, "message": f.message} for f in failures],
                })
                continue
            prev_entry = state.entry(loc, ns, key)
            prev_text = current if isinstance(current, str) else None
            was = is_translated_value(src, prev_text)
            now = is_translated_value(src, value)
            if loc in by_loc:
                by_loc[loc]["after"] += int(now) - int(was)
            counters["changes"].append({
                "file": name,
                "locale": loc,
                "namespace": ns,
                "key": key,
                "previous": prev_text or "",
                "next": value,
                "previous_status": translation_status(src, prev_text, prev_entry),
                "status": "imported",
                "model": model,
                "kind": "updated" if was else "new",
            })
            counters["accepted"] += 1
            overlay[(loc, ns, key)] = value
            if dry_run:
                continue
            pending.setdefault((loc, ns), {})[key] = value

    if not dry_run and pending:
        _write_pending(
            cfg, catalog, pending, state=state, history=history, scores=scores,
            model=model, trigger=trigger,
        )
    return _file_result(
        name, counters, model=model, coverage=coverage,
        applied=not dry_run and bool(pending),
    )


def _write_pending(
    cfg: ProjectConfig,
    catalog: Catalog,
    pending: dict[tuple[str, str], dict[str, str]],
    *,
    state,
    history,
    scores,
    model: str,
    trigger: str,
) -> None:
    touched: set[str] = set()
    pending_history: list = []
    source_map_cache: dict[str, dict] = {}
    for (loc, ns), updates in pending.items():
        if ns not in source_map_cache:
            source_map_cache[ns] = catalog.load(cfg.source_locale, ns)
        source_map = source_map_cache[ns]
        existing = catalog.load(loc, ns)
        for key, value in updates.items():
            src = source_map[key]
            prev_entry = state.entry(loc, ns, key) or {}
            verified_at = prev_entry.get("verified_at")
            verified_by = prev_entry.get("verified_by")
            previous = existing.get(key)
            record_candidate(
                state=state, scores=scores, history=history,
                locale=loc, namespace=ns, key=key, source=src,
                previous=previous if isinstance(previous, str) else None,
                text=value, model=model, quality_score=0.0,
                quality_signals=[], trigger=trigger, status="imported",
                provider="import", record_score=False,
                pending_history=pending_history,
            )
            if isinstance(verified_at, str) and verified_at.strip():
                entry = state.entry(loc, ns, key) or {}
                entry["verified_at"] = verified_at
                if verified_by:
                    entry["verified_by"] = verified_by
                state.record(loc, ns, key, entry)
        catalog.write(loc, ns, updates, source=source_map, existing=existing)
        touched.add(loc)
    for loc in touched:
        state.save(loc)
        scores.save(loc)
    for loc, event in pending_history:
        history.append(loc, event)
    for loc in {locale for locale, _event in pending_history}:
        history.compact(loc)


def import_csv(
    cfg: ProjectConfig,
    catalog: Catalog,
    text: str,
    *,
    locales: list[str] | None = None,
    dry_run: bool = False,
    model: str = "import",
    filename: str = "",
) -> dict:
    """Merge CSV edits into catalogues with validation."""
    model = (model or "import").strip() or "import"
    rows, resolved, positional, repaired, error = _parse_csv_table(
        text, locales, set(cfg.targets),
    )
    if error:
        return _structural(filename, error, model)
    result = _consume_rows(
        cfg, catalog, rows, resolved, filename=filename, model=model,
        trigger="import", dry_run=dry_run, positional=positional,
    )
    warnings: list[str] = list(result.get("warnings") or [])
    if positional:
        warnings.append(
            "headerless CSV: columns mapped by position; pass exactly one "
            "--locales value for the translation column"
        )
    if repaired:
        warnings.append(
            "headerless CSV: unquoted commas in translations were rejoined; "
            "a translator note that starts with a space may be misparsed"
        )
        if result.get("files"):
            result["files"][0]["repaired"] = True
    if any(row.get("__merged__") for _line, row in rows):
        warnings.append(
            "CSV: unquoted commas in a translation were rejoined; quote fields that contain commas"
        )
        if result.get("files"):
            result["files"][0]["repaired"] = True
    if warnings:
        result["warnings"] = warnings
    return result


def import_json(
    cfg: ProjectConfig,
    catalog: Catalog,
    text: str,
    *,
    locales: list[str] | None = None,
    dry_run: bool = False,
    model: str = "import",
    filename: str = "",
) -> dict:
    """Merge a handoff JSON document or a bare array of rows."""
    model = (model or "import").strip() or "import"
    name = filename or "import"
    try:
        data = json.loads(_strip_bom(text) or "null")
    except json.JSONDecodeError as exc:
        return _structural(name, f"not valid JSON: {exc.msg}", model)
    file_locales: list[str] | None = None
    if isinstance(data, dict):
        rows = data.get("rows")
        if isinstance(data.get("locales"), list):
            file_locales = [str(item) for item in data["locales"]]
        if not isinstance(rows, list):
            return _structural(name, "JSON is not a handoff document or an array of rows", model)
    elif isinstance(data, list):
        rows = data
    else:
        return _structural(name, "JSON is not a handoff document or an array of rows", model)

    known = set(cfg.targets)
    resolved = list(locales) if locales else []
    if not resolved and file_locales:
        resolved = [loc for loc in file_locales if loc in known]
    if not resolved:
        found: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            targets = row.get("targets") if isinstance(row.get("targets"), dict) else {}
            for loc in list(targets) + [key for key in row if key in known]:
                if loc in known and loc not in found:
                    found.append(loc)
        resolved = found
    if not resolved:
        return _structural(name, "select the locale this file is for", model)

    table: list[tuple[int, dict]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return _structural(name, f"row {index} is not an object", model)
        targets = row.get("targets") if isinstance(row.get("targets"), dict) else {}
        item = {
            "namespace": str(row.get("namespace") or ""),
            "key": str(row.get("key") or ""),
            "source": str(row.get("source") or ""),
        }
        for loc in resolved:
            raw = targets.get(loc, row.get(loc, ""))
            item[loc] = "" if raw is None else str(raw)
        table.append((index, item))
    return _consume_rows(
        cfg, catalog, table, resolved, filename=name, model=model,
        trigger="import-json", dry_run=dry_run, positional=False,
    )


def _file_target(file_el, root_target: str = "") -> str:
    """Target locale of a 1.2 ``file`` element, or the 2.0 root ``trgLang``."""
    return (
        file_el.get("target-language") or file_el.get("target_language")
        or file_el.get("trgLang") or root_target or ""
    )


def import_xliff(
    cfg: ProjectConfig,
    catalog: Catalog,
    text: str,
    *,
    locales: list[str] | None = None,
    dry_run: bool = False,
    model: str = "import",
    filename: str = "",
) -> dict:
    """Merge XLIFF targets into catalogues with validation."""
    model = (model or "import").strip() or "import"
    name = filename or "import"
    try:
        root = xml_fromstring(_strip_bom(text))
    except ET.ParseError as exc:
        return _structural(name, f"not valid XLIFF: {exc}", model)
    version = (root.get("version") or "").strip()
    v2 = version.startswith("2")
    root_target = (root.get("trgLang") or "") if v2 else ""
    known = set(cfg.targets)
    files = root.findall(".//{*}file")
    if not files:
        return _structural(name, "not an XLIFF document", model)
    if locales:
        resolved = list(locales)
    else:
        resolved = []
        for file_el in files:
            loc = _file_target(file_el, root_target)
            if loc in known and loc not in resolved:
                resolved.append(loc)
        if not resolved:
            return _structural(name, "select the locale this file is for", model)
    rows: list[tuple[int, dict]] = []
    notes_by_key: dict[tuple[str, str], str] = {}
    try:
        known_ns = {n for n in catalog.namespaces() if n}
    except Exception:  # noqa: BLE001 - namespace discovery is best effort
        known_ns = set()
    for file_el in files:
        loc = _file_target(file_el, root_target)
        if loc not in resolved:
            continue
        unit_tag = "{*}unit" if v2 else "{*}trans-unit"
        for index, unit in enumerate(file_el.findall(f".//{unit_tag}"), start=1):
            uid = unit.get("id") or ""
            # A catalogue without namespaces: a dotted id is one nested key.
            ns, key = _parse_unit_id(uid, known_ns) if known_ns else ("", uid.strip())
            # itertext keeps text around inline markup (<g>, <x/>, <ph>).
            target_els = (
                [seg.find("{*}target") for seg in unit.findall("{*}segment")]
                if v2 else [unit.find("{*}target")]
            )
            value = "".join(
                "".join(t.itertext()) for t in target_els if t is not None
            )
            rows.append((index, {"namespace": ns, "key": key, loc: value}))
            note = _xliff_note_text(unit)
            if note:
                notes_by_key[(ns, key)] = note
    if not rows and not any(
        _file_target(file_el, root_target) in resolved for file_el in files
    ):
        return _structural(
            name, "XLIFF target-language does not match the selected locale", model,
        )
    result = _consume_rows(
        cfg, catalog, rows, resolved, filename=name, model=model,
        trigger="import-xliff", dry_run=dry_run, positional=False,
    )
    _apply_xliff_notes(cfg, result, notes_by_key, dry_run=dry_run)
    return result


def detect_format(name: str, text: str, explicit: str | None = None) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in {".xliff", ".xlf"}:
        return "xliff"
    if suffix == ".json":
        return "json"
    if suffix in {".csv", ".xlsx"}:  # a workbook is converted to CSV text on the way in
        return "csv"
    if explicit in {"csv", "xliff", "json"}:
        return explicit
    stripped = _strip_bom(text).lstrip()
    if stripped.startswith("<"):
        return "xliff"
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    return "csv"


def explode_import_file(
    name: str,
    *,
    text: str | None = None,
    raw: bytes | None = None,
) -> tuple[list[tuple[str, str]], str | None]:
    """Expand one upload into ``(filename, text)`` documents."""
    lower = name.lower()
    if lower.endswith(".zip"):
        data = raw if raw is not None else (text or "").encode("utf-8")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            return [], f"{name}: not a zip file"
        docs: list[tuple[str, str]] = []
        uncompressed = 0
        entries = 0
        for info in archive.infolist():
            entries += 1
            if entries > 100:
                return [], f"{name}: zip has more than 100 entries"
            uncompressed += info.file_size
            if uncompressed > 32 * 1024 * 1024:
                return [], f"{name}: zip uncompressed size exceeds 32 MiB"
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue
            base = Path(info.filename).name
            if not base or base.startswith("."):
                continue
            if Path(base).suffix.lower() not in _IMPORT_SUFFIXES:
                continue
            payload = archive.read(info)
            if len(payload) > 8 * 1024 * 1024:
                return [], f"{name}: {base} exceeds 8 MiB"
            label = f"{name}:{base}"
            if Path(base).suffix.lower() == ".xlsx":
                try:
                    docs.append((label, xlsx_to_csv_text(payload)))
                except ValueError as exc:
                    return [], f"{label}: {exc}"
                continue
            docs.append((label, decode_import_bytes(payload)))
        if not docs:
            return [], f"{name}: zip contains no csv, json, xlsx, or xliff files"
        return docs, None
    if lower.endswith(".xls"):
        return [], f"{name}: the old .xls format is not read; save it as .xlsx and import that"
    if lower.endswith(".xlsx"):
        data = raw if raw is not None else (text or "").encode("latin-1", "ignore")
        try:
            return [(name, xlsx_to_csv_text(data))], None
        except ValueError as exc:
            return [], f"{name}: {exc}"
    return [(name, text or "")], None


def _merge_coverage(groups: list[list[dict]]) -> list[dict]:
    acc: dict[str, dict] = {}
    for group in groups:
        for cov in group:
            loc = cov["locale"]
            delta = max(0, cov["after"] - cov["before"])
            if loc not in acc:
                acc[loc] = {
                    "locale": loc, "before": cov["before"],
                    "after": cov["before"] + delta, "total": cov["total"],
                }
            else:
                acc[loc]["after"] += delta
                acc[loc]["total"] += cov["total"]
    return list(acc.values())


def merge_import_results(
    parts: list[dict],
    *,
    model: str,
    applied: bool,
    blocked: bool,
) -> dict:
    files = [row for part in parts for row in part.get("files") or []]
    errors = [err for part in parts for err in part.get("errors") or []]
    changes = [change for part in parts for change in part.get("changes") or []]
    structural_bits = [
        f"{row['name']}: {row['structural']}" for row in files if row.get("structural")
    ]
    result = {
        "ok": False,
        "accepted": sum(part.get("accepted", 0) for part in parts),
        "unchanged": sum(part.get("unchanged", 0) for part in parts),
        "rejected": sum(part.get("rejected", 0) for part in parts),
        "skipped": sum(part.get("skipped", 0) for part in parts),
        "errors": errors,
        "changes": changes,
        "coverage": _merge_coverage([part.get("coverage") or [] for part in parts]),
        "files": files,
        "positional": any(part.get("positional") for part in parts),
        "structural": "; ".join(structural_bits) if structural_bits else None,
        "applied": applied and not blocked,
        "blocked": blocked,
        "model": model,
        "provider": "import",
    }
    result["ok"] = False if blocked else _result_ok(result)
    return result


def import_documents(
    cfg: ProjectConfig,
    catalog: Catalog,
    documents: list[tuple[str, str]],
    *,
    locales: list[str] | None = None,
    dry_run: bool = False,
    model: str = "import",
    fmt: str | None = None,
) -> dict:
    """Import several documents. A structural error writes nothing."""
    from ..catalog.flush_journal import flush_block_message

    model = (model or "import").strip() or "import"
    blocked_flush = flush_block_message(cfg.state_root())
    if blocked_flush:
        return _structural("", blocked_flush, model)
    if not documents:
        return _structural("", "no file to import", model)

    def run(probe: bool) -> list[dict]:
        out = []
        explicit = fmt if len(documents) == 1 else None
        for name, text in documents:
            kind = detect_format(name, text, explicit)
            kwargs = dict(
                locales=locales, dry_run=probe, model=model, filename=name,
            )
            if kind == "xliff":
                out.append(import_xliff(cfg, catalog, text, **kwargs))
            elif kind == "json":
                out.append(import_json(cfg, catalog, text, **kwargs))
            else:
                out.append(import_csv(cfg, catalog, text, **kwargs))
        return out

    planned = run(True)
    blocked = any(
        row.get("structural")
        for part in planned
        for row in part.get("files") or []
    )
    if blocked or dry_run:
        return merge_import_results(planned, model=model, applied=False, blocked=blocked)
    # Journal the multi-store write (catalogue, state, history): a crash part
    # way leaves a blocking intent, so later mutators stop until acknowledged.
    from ..catalog.flush_journal import FlushIntent, FlushJournal
    from ..catalog.state import now_iso

    journal = FlushJournal(cfg.state_root())
    previous = journal.read()  # a translate "progress" record must survive
    journal.begin(FlushIntent(
        run_id=f"import:{model}", started_at=now_iso(),
        locales=list(locales or []), phase="catalog",
        pending_keys=sum(int(part.get("accepted") or 0) for part in planned),
    ))
    applied = run(False)
    if previous:
        journal._write(previous)
    else:
        journal.clear()
    return merge_import_results(applied, model=model, applied=True, blocked=False)


def format_import_report(
    result: dict,
    *,
    error_limit: int = 50,
    change_limit: int = 100,
) -> list[str]:
    """Lines for the Operations log and the CLI. The JSON report stays complete."""
    lines: list[str] = []
    for row in result.get("files") or []:
        if row.get("structural"):
            lines.append(f"{row.get('name') or 'import'}: {row['structural']}")
            continue
        bit = (
            f"{row.get('name') or 'import'}: "
            f"{row.get('accepted', 0)} written, {row.get('unchanged', 0)} unchanged, "
            f"{row.get('rejected', 0)} rejected, {row.get('skipped', 0)} skipped"
        )
        if row.get("positional"):
            bit += " (columns mapped by position; header was missing)"
        if row.get("repaired"):
            bit += " (unquoted commas in translations were rejoined)"
        lines.append(bit)
    for warning in result.get("warnings") or []:
        lines.append(f"warning: {warning}")
    for cov in result.get("coverage") or []:
        delta = cov["after"] - cov["before"]
        sign = f"+{delta}" if delta >= 0 else str(delta)
        lines.append(
            f"{cov['locale']}: {cov['before']}/{cov['total']} translated → "
            f"{cov['after']}/{cov['total']} ({sign})"
        )
    changes = result.get("changes") or []
    new_n = sum(1 for change in changes if change.get("kind") == "new")
    updated_n = sum(1 for change in changes if change.get("kind") == "updated")
    lines.append(
        f"new {new_n}, updated {updated_n}, "
        f"model {result.get('model') or 'import'}, provider import"
    )
    for change in changes[:change_limit]:
        ns = change.get("namespace") or ""
        ident = f"{ns}.{change.get('key')}" if ns else str(change.get("key") or "")
        lines.append(
            f"{change.get('locale')} {ident}: {_show(change.get('previous') or '')} → "
            f"{_show(change.get('next') or '')} "
            f"({change.get('previous_status')} → {change.get('status')})"
        )
    if len(changes) > change_limit:
        lines.append(f"… and {len(changes) - change_limit} more in the report download")
    errors = result.get("errors") or []
    for err in errors[:error_limit]:
        lines.append(_format_error(err))
    if len(errors) > error_limit:
        lines.append(f"… and {len(errors) - error_limit} more errors in the report download")
    if result.get("blocked"):
        lines.append("nothing written — fix the files above and import again")
    elif not result.get("applied"):
        lines.append("dry-run — nothing written")
    return lines


def _format_error(err: dict) -> str:
    where = err.get("file") or ""
    line = err.get("line")
    key = err.get("key") or ""
    loc = err.get("locale") or ""
    prefix = " ".join(part for part in (
        where,
        f"line {line}" if line else "",
        loc,
        key,
    ) if part)
    if err.get("error"):
        return f"{prefix}: {err['error']}" if prefix else str(err["error"])
    messages = []
    for item in err.get("errors") or []:
        if isinstance(item, dict):
            messages.append(item.get("message") or item.get("id") or "")
        else:
            messages.append(str(item))
    detail = "; ".join(m for m in messages if m) or "rejected"
    return f"{prefix}: {detail}" if prefix else detail


def load_catalog(cfg: ProjectConfig):
    """Build the catalogue the export/import ops use."""
    return catalog_for(cfg)
