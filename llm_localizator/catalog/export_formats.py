"""Export-side helpers for translation catalogue handoff."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ..catalog import Catalog, StateStore
from ..catalog.scores import ScoreStore
from ..catalog.state import (
    is_translated_value,
    is_verified,
    matches_status_filter,
    split_operator_key,
    translation_status,
)
from ..projects import ContextNotes, ProjectConfig
from ..projects.screenshots import resolve_screenshot_path
from ..catalog.provenance import provider_of
from .xlsx_exchange import XLSX_CONTENT_TYPE

_META_COLUMNS = ["note", "llmNote", "maxChars", "screen", "image", "fullKey"]


def _fieldnames(locales: list[str]) -> list[str]:
    return (
        ["namespace", "key", "source"]
        + list(locales)
        + _META_COLUMNS
        + [f"status_{loc}" for loc in locales]
        + [f"score_{loc}" for loc in locales]
    )


def _expected_width(n_locales: int) -> int:
    return 3 + n_locales + len(_META_COLUMNS) + 2 * n_locales


def _threshold(cfg: ProjectConfig, threshold: float | None, locale: str | None = None) -> float:
    if threshold is not None:
        return float(threshold)
    per_locale = getattr(cfg, "quality_thresholds", None) or {}
    if locale and locale in per_locale:
        return float(per_locale[locale])
    return float(getattr(cfg, "quality_threshold", 0.55))


def _quality(scores: ScoreStore, locale: str, namespace: str, key: str) -> float | None:
    raw = (scores.get(locale, namespace, key) or {}).get("quality_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _namespaces(cfg: ProjectConfig, catalog: Catalog, namespaces: list[str] | None) -> list[str]:
    return namespaces if namespaces is not None else cfg.namespaces_for(catalog)


def _context_fields(cfg: ProjectConfig, notes: ContextNotes, namespace: str, key: str) -> dict[str, str]:
    mc = notes.max_chars(namespace, key)
    screen = notes.screen(namespace, key) or ""
    shot = (
        resolve_screenshot_path(cfg.context_dir, screen=screen, image=notes.image(namespace, key))
        if cfg.context_dir else None
    )
    image = (
        str(shot.relative_to(cfg.context_dir.resolve())).replace("\\", "/")
        if shot else ""
    )
    return {
        "note": notes.note(namespace, key),
        "llmNote": notes.llm_note(namespace, key),
        "maxChars": str(mc) if mc else "",
        "screen": screen,
        "image": image,
        "fullKey": notes.full_key(namespace, key) or "",
    }


def _iter_rows(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str] | None,
    match_locales: list[str] | None,
    only: str,
    threshold: float | None,
):
    """Yield handoff rows. A row is kept when any match-locale passes ``only``."""
    ns_list = _namespaces(cfg, catalog, namespaces)
    targets = list(locales)
    match = list(match_locales or targets)
    notes = ContextNotes(cfg.context_dir)
    state = StateStore(cfg.state_root())
    scores = ScoreStore(cfg.scores_root())
    for ns in ns_list:
        source = catalog.load(cfg.source_locale, ns)
        per_locale = {loc: catalog.load(loc, ns) for loc in targets}
        match_maps = dict(per_locale)
        if any(loc not in match_maps for loc in match):
            for loc in match:
                match_maps.setdefault(loc, catalog.load(loc, ns))
        for key, src in sorted(source.items()):
            if cfg.is_skipped(ns, key, src):
                continue
            if only and only != "all":
                keep = False
                for loc in match:
                    value = match_maps[loc].get(key)
                    entry = state.entry(loc, ns, key)
                    status = translation_status(src, value if isinstance(value, str) else None, entry)
                    if matches_status_filter(
                        only,
                        status=status,
                        provider=provider_of(entry) if entry else None,
                        verified=is_verified(entry),
                        quality_score=_quality(scores, loc, ns, key),
                        threshold=_threshold(cfg, threshold, loc),
                    ):
                        keep = True
                        break
                if not keep:
                    continue
            targets_out: dict[str, str] = {}
            status_out: dict[str, str] = {}
            score_out: dict[str, float | None] = {}
            for loc in targets:
                raw = per_locale[loc].get(key)
                targets_out[loc] = raw if isinstance(raw, str) else ""
                entry = state.entry(loc, ns, key)
                status_out[loc] = translation_status(
                    src, raw if isinstance(raw, str) else None, entry,
                )
                score_out[loc] = _quality(scores, loc, ns, key)
            row = {
                "namespace": ns,
                "key": key,
                "source": src,
                "targets": targets_out,
                "status": status_out,
                "score": score_out,
            }
            row.update(_context_fields(cfg, notes, ns, key))
            yield row


def _csv_safe(value: object) -> str:
    """Neutralize Excel formula injection on export cells.

    Only ``=``, ``+``, ``@``, tab, and CR are genuine injection triggers.
    ``-`` is intentionally excluded: negative numbers and hyphen-prefixed
    translations are legitimate content and must round-trip without corruption.
    """
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "@", "\t", "\r"}:
        return "'" + text
    return text


def _flat_rows(locales: list[str], rows: list[dict]) -> list[dict]:
    """Handoff rows as flat, formula-safe cell dicts (shared by CSV and xlsx)."""
    out = []
    for row in rows:
        flat = {
            "namespace": row["namespace"],
            "key": row["key"],
            "source": _csv_safe(row["source"]),
            "note": _csv_safe(row["note"]),
            "llmNote": _csv_safe(row["llmNote"]),
            "maxChars": row["maxChars"],
            "screen": row["screen"],
            "image": row["image"],
            "fullKey": row["fullKey"],
        }
        for loc in locales:
            flat[loc] = _csv_safe(row["targets"].get(loc, ""))
            flat[f"status_{loc}"] = row["status"].get(loc, "")
            score = row["score"].get(loc)
            flat[f"score_{loc}"] = "" if score is None else str(score)
        out.append(flat)
    return out


def _csv_text(locales: list[str], rows: list[dict]) -> str:
    columns = _fieldnames(locales)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for flat in _flat_rows(locales, rows):
        writer.writerow(flat)
    return buf.getvalue()


def _xlsx_bytes(locales: list[str], rows: list[dict]) -> bytes:
    """One sheet per namespace, same columns as the CSV handoff."""
    from .xlsx_exchange import grid_to_xlsx

    flat = _flat_rows(locales, rows)
    by_ns: dict[str, list[dict]] = {}
    for record in flat:
        by_ns.setdefault(record["namespace"], []).append(record)
    sheets = [(ns or "default", recs) for ns, recs in by_ns.items()]
    return grid_to_xlsx(_fieldnames(locales), sheets)


def _json_text(cfg: ProjectConfig, locales: list[str], rows: list[dict]) -> str:
    payload = {
        "format": "llm-localizator-handoff",
        "version": 1,
        "source_locale": cfg.source_locale,
        "locales": list(locales),
        "rows": [
            {
                "namespace": row["namespace"],
                "key": row["key"],
                "source": row["source"],
                "targets": {loc: row["targets"].get(loc, "") for loc in locales},
                "note": row["note"],
                "status": {loc: row["status"].get(loc, "") for loc in locales},
                "score": {loc: row["score"].get(loc) for loc in locales},
            }
            for row in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _xliff_text(cfg: ProjectConfig, locales: list[str], rows: list[dict]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">',
    ]
    for loc in locales:
        parts.append(
            f"  <file original={quoteattr(cfg.name or 'messages')} "
            f"source-language={quoteattr(cfg.source_locale)} "
            f"target-language={quoteattr(loc)} datatype=\"plaintext\">"
        )
        parts.append("    <body>")
        for row in rows:
            uid = _unit_id(row["namespace"], row["key"])
            meta = " ".join(p for p in (row["note"], row["llmNote"]) if p)
            parts.append(f"      <trans-unit id={quoteattr(uid)}>")
            if meta:
                parts.append(f"        <note>{escape(meta)}</note>")
            parts.append(f"        <source>{escape(row['source'])}</source>")
            parts.append(f"        <target>{escape(row['targets'].get(loc, ''))}</target>")
            parts.append("      </trans-unit>")
        parts.append("    </body>")
        parts.append("  </file>")
    parts.append("</xliff>")
    return "\n".join(parts) + "\n"


def _xliff2_text(cfg: ProjectConfig, locales: list[str], rows: list[dict]) -> str:
    """XLIFF 2.0: one ``file`` per locale; ICU plural messages travel as text."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    for loc in locales:
        parts.append(
            '<xliff version="2.0" xmlns="urn:oasis:names:tc:xliff:document:2.0" '
            f"srcLang={quoteattr(cfg.source_locale)} trgLang={quoteattr(loc)}>"
        )
        parts.append(f"  <file id={quoteattr('f-' + loc)}>")
        for row in rows:
            uid = _unit_id(row["namespace"], row["key"])
            meta = " ".join(p for p in (row["note"], row["llmNote"]) if p)
            parts.append(f"    <unit id={quoteattr(uid)}>")
            if meta:
                parts.append(f"      <notes><note>{escape(meta)}</note></notes>")
            parts.append("      <segment>")
            parts.append(f"        <source>{escape(row['source'])}</source>")
            parts.append(f"        <target>{escape(row['targets'].get(loc, ''))}</target>")
            parts.append("      </segment>")
            parts.append("    </unit>")
        parts.append("  </file>")
        parts.append("</xliff>")
    return "\n".join(parts) + "\n"


def _text_for(
    cfg: ProjectConfig, fmt: str, locales: list[str], rows: list[dict],
    *, xliff_version: str = "1.2", bom: bool = False,
) -> str:
    if fmt == "xliff":
        render = _xliff2_text if xliff_version == "2.0" else _xliff_text
        return render(cfg, locales, rows)
    if fmt == "json":
        return _json_text(cfg, locales, rows)
    text = _csv_text(locales, rows)
    return "\ufeff" + text if bom else text


def export_csv(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str] | None = None,
    only: str = "all",
    match_locales: list[str] | None = None,
    threshold: float | None = None,
    bom: bool = False,
) -> str:
    """Serialize catalogue rows to CSV text. The header row is required on import.

    ``bom=True`` prefixes a UTF-8 byte-order mark so Excel opens the file as UTF-8.
    """
    text = _csv_text(list(locales), list(_iter_rows(
        cfg, catalog, locales=list(locales), namespaces=namespaces,
        match_locales=match_locales, only=only, threshold=threshold,
    )))
    return "\ufeff" + text if bom else text


def export_json(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str] | None = None,
    only: str = "all",
    match_locales: list[str] | None = None,
    threshold: float | None = None,
) -> str:
    """Handoff JSON. Not a message-catalogue file."""
    return _json_text(cfg, list(locales), list(_iter_rows(
        cfg, catalog, locales=list(locales), namespaces=namespaces,
        match_locales=match_locales, only=only, threshold=threshold,
    )))


def export_xliff(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str] | None = None,
    only: str = "all",
    match_locales: list[str] | None = None,
    threshold: float | None = None,
    version: str = "1.2",
) -> str:
    """Serialize catalogue rows to XLIFF 1.2 (default) or 2.0, one file per locale."""
    if version not in {"1.2", "2.0"}:
        raise ValueError(f"unsupported XLIFF version {version!r}")
    if version == "2.0" and len(locales) != 1:
        raise ValueError("XLIFF 2.0 export takes exactly one target locale")
    render = _xliff2_text if version == "2.0" else _xliff_text
    return render(cfg, list(locales), list(_iter_rows(
        cfg, catalog, locales=list(locales), namespaces=namespaces,
        match_locales=match_locales, only=only, threshold=threshold,
    )))


def _unit_id(namespace: str, key: str) -> str:
    return f"{namespace}.{key}" if namespace else key


def _xliff_note_text(unit) -> str:
    parts = []
    for note in [*unit.findall("{*}note"), *unit.findall("{*}notes/{*}note")]:
        text = "".join(note.itertext()).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _apply_xliff_notes(
    cfg: ProjectConfig,
    result: dict,
    notes_by_key: dict[tuple[str, str], str],
    *,
    dry_run: bool,
) -> None:
    """Store a new translator note. Never replace an existing one or other fields."""
    from ..projects.context import write_context_entry

    accepted = {
        (str(change.get("namespace") or ""), str(change.get("key") or ""))
        for change in result.get("changes") or []
    }
    skipped: list[dict[str, str]] = []
    reader = ContextNotes(cfg.context_dir)
    for (ns, key), text in notes_by_key.items():
        if (ns, key) not in accepted or not text:
            continue
        if cfg.context_dir is None or reader.note(ns, key).strip():
            skipped.append({"namespace": ns, "key": key, "note": text})
            continue
        if not dry_run:
            write_context_entry(cfg.context_dir, ns, key, {"note": text})
    if skipped:
        result["skipped_notes"] = skipped
        if result.get("files"):
            result["files"][0]["skipped_notes"] = skipped


def _parse_unit_id(unit_id: str, namespaces: set[str] | None = None) -> tuple[str, str]:
    return split_operator_key(unit_id, namespaces)


_BUNDLE_README = """\
llm-localizator translator handoff bundle
====================================

handoff.csv (or .json / .xliff)
  Strings to translate. Keep the header row — a file without it is imported
  only when you select exactly one locale and the columns are still in export
  order. status_* and score_* are reference only; do not edit them.
  A verified_at column, if present, is not applied on import and is not written.
  In a CSV, wrap every field that contains a comma in double quotes. Never
  escape a comma with a backslash: text after an unquoted comma is not part of
  the field. A row with more cells than the header is rejected, not shortened.

screenshots/
  UI images referenced by the image column. Open alongside the row.

Return the edited file via Operations → import, or:
  llm-localizator import <project> handoff.csv --locales pl --localized-by NAME
"""


def _bundle_screenshots(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    namespaces: list[str] | None = None,
) -> list[tuple[str, Path]]:
    """Unique (zip_arcname, source_path) pairs for screenshots in a bundle."""
    if not cfg.context_dir:
        return []
    ns_list = _namespaces(cfg, catalog, namespaces)
    notes = ContextNotes(cfg.context_dir)
    root = cfg.context_dir.resolve()
    seen: set[str] = set()
    out: list[tuple[str, Path]] = []
    for ns in ns_list:
        for key, src in catalog.load(cfg.source_locale, ns).items():
            if cfg.is_skipped(ns, key, src if isinstance(src, str) else None):
                continue
            screen_id = notes.screen(ns, key)
            shot = resolve_screenshot_path(
                cfg.context_dir, screen=screen_id, image=notes.image(ns, key),
            )
            if not shot:
                continue
            rel = str(shot.relative_to(root)).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            out.append((rel, shot))
    return out


def _ext(fmt: str) -> str:
    return {"csv": "csv", "json": "json", "xliff": "xliff", "xlsx": "xlsx"}.get(fmt, "csv")


def _parse_file_count(value) -> int:
    if value is None or value is False or value == "":
        return 1
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("file count must be a whole number") from exc
    if count < 1:
        raise ValueError("file count must be at least 1")
    return count


def _chunk_rows(rows: list[dict], requested: int) -> list[list[dict]]:
    """Split ``rows`` into ``requested`` contiguous chunks.

    The remainder goes on the earlier chunks. Empty chunks are dropped, and
    the count is capped at the number of rows. No rows still yields one empty
    chunk so the download stays a valid handoff.
    """
    if not rows:
        return [rows]
    count = min(requested, len(rows))
    base, extra = divmod(len(rows), count)
    out: list[list[dict]] = []
    index = 0
    for i in range(count):
        size = base + (1 if i < extra else 0)
        out.append(rows[index:index + size])
        index += size
    return out


def _split_sort_key(row: dict, locales: list[str], layout: str):
    ns = row.get("namespace") or ""
    key = row.get("key") or ""
    if layout != "per-locale":
        return (0, ns, key)
    rank = len(locales)
    source = row.get("source") or ""
    targets = row.get("targets") or {}
    for i, loc in enumerate(locales):
        if not is_translated_value(source, targets.get(loc)):
            rank = i
            break
    return (rank, ns, key)


def _row_ident(row: dict) -> str:
    ns = row.get("namespace") or ""
    key = row.get("key") or ""
    return f"{ns}.{key}" if ns else key


def _collect_rows(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str] | None,
    match_locales: list[str] | None,
    only: str,
    threshold: float | None,
) -> list[dict]:
    return list(_iter_rows(
        cfg, catalog, locales=locales, namespaces=namespaces,
        match_locales=match_locales, only=only, threshold=threshold,
    ))


def _export_groups(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    fmt: str,
    layout: str,
    locales: list[str],
    namespaces: list[str] | None,
    only: str,
    threshold: float | None,
    file_count: int,
) -> list[tuple[str, list[str], list[dict]]]:
    """``(filename, locale columns, rows)`` for each handoff file."""
    ext = _ext(fmt)
    targets = list(locales)
    if file_count > 1:
        rows = _collect_rows(
            cfg, catalog, locales=targets, namespaces=namespaces,
            match_locales=targets, only=only, threshold=threshold,
        )
        rows.sort(key=lambda row: _split_sort_key(row, targets, layout))
        chunks = _chunk_rows(rows, file_count)
        width = max(2, len(str(len(chunks))))
        return [
            (f"handoff-{i:0{width}d}.{ext}", targets, chunk)
            for i, chunk in enumerate(chunks, start=1)
        ]
    if layout == "per-locale":
        return [
            (
                f"{loc}.{ext}",
                [loc],
                _collect_rows(
                    cfg, catalog, locales=[loc], namespaces=namespaces,
                    match_locales=[loc], only=only, threshold=threshold,
                ),
            )
            for loc in targets
        ]
    if layout == "per-namespace":
        return [
            (
                f"{ns or 'default'}.{ext}",
                targets,
                _collect_rows(
                    cfg, catalog, locales=targets, namespaces=[ns],
                    match_locales=targets, only=only, threshold=threshold,
                ),
            )
            for ns in _namespaces(cfg, catalog, namespaces)
        ]
    rows = _collect_rows(
        cfg, catalog, locales=targets, namespaces=namespaces,
        match_locales=targets, only=only, threshold=threshold,
    )
    return [(f"handoff.{ext}", targets, rows)]


def _build_export_report(
    *,
    fmt: str,
    layout: str,
    only: str,
    locales: list[str],
    requested: int,
    groups: list[tuple[str, list[str], list[dict]]],
    screenshot_files: list[str],
    packed: bool,
) -> dict:
    files: list[dict] = []
    by_locale: dict[str, dict] = {}
    by_namespace: dict[str, int] = {}
    keys: list[dict] = []
    total = 0
    for name, locs, rows in groups:
        ns_counts: dict[str, int] = {}
        for row in rows:
            ns = row.get("namespace") or "(default)"
            ns_counts[ns] = ns_counts.get(ns, 0) + 1
            by_namespace[ns] = by_namespace.get(ns, 0) + 1
            total += 1
            statuses = {loc: row["status"].get(loc, "") for loc in locs}
            keys.append({
                "file": name,
                "namespace": row.get("namespace") or "",
                "key": row.get("key") or "",
                "source": row.get("source") or "",
                "targets": {loc: row["targets"].get(loc, "") for loc in locs},
                "status": statuses,
                "score": {loc: row["score"].get(loc) for loc in locs},
            })
            source = row.get("source") or ""
            for loc in locs:
                bucket = by_locale.setdefault(loc, {"filled": 0, "empty": 0, "statuses": {}})
                if is_translated_value(source, row["targets"].get(loc)):
                    bucket["filled"] += 1
                else:
                    bucket["empty"] += 1
                status = row["status"].get(loc) or "missing"
                bucket["statuses"][status] = bucket["statuses"].get(status, 0) + 1
        files.append({
            "name": name,
            "rows": len(rows),
            "locales": list(locs),
            "namespaces": ns_counts,
            "first": _row_ident(rows[0]) if rows else "",
            "last": _row_ident(rows[-1]) if rows else "",
        })
    return {
        "format": fmt,
        "layout": layout,
        "only": only or "all",
        "locales": list(locales),
        "requested_files": requested,
        "file_count": len(files),
        "rows": total,
        "files": files,
        "by_locale": by_locale,
        "by_namespace": by_namespace,
        "keys": keys,
        "screenshots": len(screenshot_files),
        "screenshot_files": screenshot_files,
        "packed": packed,
    }


def _show(text: str) -> str:
    return '"' + str(text).replace('"', '\\"') + '"'


def format_export_report(report: dict, *, key_limit: int = 40) -> list[str]:
    """Lines for the Operations log and the CLI. The JSON report stays complete."""
    files = report.get("files") or []
    lines = [
        f"exported {report.get('rows', 0)} row(s) in {len(files)} file(s) "
        f"({report.get('format') or 'csv'}, filter {report.get('only') or 'all'})",
    ]
    requested = int(report.get("requested_files") or 1)
    if requested > 1 and requested != len(files):
        lines.append(
            f"asked for {requested} files; wrote {len(files)} "
            "(not enough rows for more)"
        )
    locales = report.get("locales") or []
    if locales:
        lines.append("locales: " + ", ".join(locales))
    if report.get("layout") and report.get("layout") != "single" and requested <= 1:
        lines.append(f"split: {report['layout']}")
    for loc, info in (report.get("by_locale") or {}).items():
        lines.append(
            f"{loc}: {info.get('filled', 0)} filled, {info.get('empty', 0)} empty"
        )
        bits = ", ".join(
            f"{name} {count}"
            for name, count in sorted((info.get("statuses") or {}).items())
            if count
        )
        if bits:
            lines.append(f"  status: {bits}")
    namespaces = report.get("by_namespace") or {}
    if namespaces:
        ranked = sorted(namespaces.items(), key=lambda item: (-item[1], item[0]))
        shown = ranked[:12]
        bit = ", ".join(f"{name} {count}" for name, count in shown)
        extra = len(ranked) - len(shown)
        if extra > 0:
            bit += f" (+{extra} more)"
        lines.append("namespaces: " + bit)
    for item in files:
        span = ""
        first = item.get("first") or ""
        last = item.get("last") or ""
        if first and last and first != last:
            span = f" ({first} … {last})"
        elif first:
            span = f" ({first})"
        ns_counts = item.get("namespaces") or {}
        ns_bit = ""
        if ns_counts:
            ranked = sorted(ns_counts.items(), key=lambda pair: (-pair[1], pair[0]))
            shown = ", ".join(f"{name} {count}" for name, count in ranked[:6])
            extra = len(ranked) - min(6, len(ranked))
            if extra > 0:
                shown += f" (+{extra} more)"
            ns_bit = f" — {shown}"
        lines.append(f"{item.get('name')}: {item.get('rows', 0)} rows{span}{ns_bit}")
    for item in (report.get("keys") or [])[:key_limit]:
        ns = item.get("namespace") or ""
        ident = f"{ns}.{item.get('key')}" if ns else str(item.get("key") or "")
        statuses = item.get("status") or {}
        bits = " ".join(f"{loc}={statuses.get(loc, '')}" for loc in statuses)
        file_bit = f"{item.get('file')} " if len(files) > 1 and item.get("file") else ""
        lines.append(f"  {file_bit}{ident} [{bits}] {_show(item.get('source') or '')}")
    extra_keys = len(report.get("keys") or []) - key_limit
    if extra_keys > 0:
        lines.append(f"… and {extra_keys} more keys in the report download")
    shots = int(report.get("screenshots") or 0)
    if shots:
        lines.append(f"screenshots: {shots}")
    if report.get("packed"):
        lines.append("export-report.json is inside the zip")
    return lines


def _filter_export_keys(groups, keys: list[str]):
    wanted = set(keys)
    kept_groups = []
    for name, locs, rows in groups:
        kept = []
        for row in rows:
            ns = row.get("namespace") or ""
            key = row.get("key") or ""
            ident = f"{ns}.{key}" if ns else key
            if ident in wanted or key in wanted:
                kept.append(row)
        if kept:
            kept_groups.append((name, locs, kept))
    return kept_groups


def blank_unapproved(cfg, groups, *, approved_only=False):
    """Blank target cells that are not approved under ``[delivery] require`` (C-007).

    ``approved_only`` without a configured level means ``verified``.
    """
    from .approval import approval_checker

    ok = approval_checker(cfg, force=approved_only)
    out = []
    for name, locs, rows in groups:
        new_rows = []
        for row in rows:
            targets = {
                loc: (v if v and ok(loc, row["namespace"], row["key"]) else "")
                for loc, v in row["targets"].items()
            }
            new_rows.append({**row, "targets": targets})
        out.append((name, locs, new_rows))
    return out


def render_export(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str] | None = None,
    fmt: str = "csv",
    layout: str = "single",
    only: str = "all",
    threshold: float | None = None,
    screenshots: bool = False,
    file_count: int = 1,
    keys: list[str] | None = None,
    xliff_version: str = "1.2",
    bom: bool = False,
    approved_only: bool = False,
) -> tuple[bytes, str, str, dict]:
    """Return ``(body, content_type, filename, report)`` for a handoff download.

    ``file_count`` of 1 keeps ``layout`` (one file, or one per locale or
    namespace). More than 1 divides the selected rows into that many handoff
    files and packs a zip. ``fmt=zip`` is the old screenshot bundle: CSV plus
    screenshots. The handoff document itself stays clean; the report is a
    separate object (and ``export-report.json`` inside a zip).
    """
    if fmt == "zip":
        fmt = "csv"
        screenshots = True
    if fmt not in {"csv", "xliff", "json", "xlsx"}:
        raise ValueError(f"unknown export format {fmt!r}")
    if fmt == "xlsx":
        from .xlsx_exchange import _openpyxl

        _openpyxl()  # fail before any work when the extra is missing
    if layout not in {"single", "per-locale", "per-namespace"}:
        raise ValueError(f"unknown export layout {layout!r}")
    if xliff_version not in {"1.2", "2.0"}:
        raise ValueError(f"unsupported XLIFF version {xliff_version!r}")
    requested = _parse_file_count(file_count)
    targets = list(locales or cfg.targets)
    if not targets:
        raise ValueError("select at least one locale")
    groups = _export_groups(
        cfg, catalog, fmt=fmt, layout=layout, locales=targets,
        namespaces=namespaces, only=only, threshold=threshold,
        file_count=requested,
    )
    if keys:
        groups = _filter_export_keys(groups, keys)
    if not groups:
        raise ValueError("nothing to export")
    if approved_only or getattr(cfg, "delivery_require", "none") != "none":
        groups = blank_unapproved(cfg, groups, approved_only=approved_only)
    if fmt == "xliff" and xliff_version == "2.0" and any(len(g[1]) != 1 for g in groups):
        raise ValueError("XLIFF 2.0 holds one target locale per file: use layout per-locale")
    shots = (
        _bundle_screenshots(cfg, catalog, namespaces=namespaces) if screenshots else []
    )
    pack = screenshots or len(groups) > 1
    report = _build_export_report(
        fmt=fmt, layout=layout, only=only, locales=targets,
        requested=requested, groups=groups,
        screenshot_files=[arc for arc, _path in shots],
        packed=pack,
    )
    if fmt == "xlsx":
        parts = [(name, _xlsx_bytes(locs, rows)) for name, locs, rows in groups]
    else:
        parts = [
            (name, _text_for(cfg, fmt, locs, rows, xliff_version=xliff_version, bom=bom))
            for name, locs, rows in groups
        ]
    stem = cfg.name or "handoff"
    if not pack:
        ctype = {
            "csv": "text/csv; charset=utf-8",
            "json": "application/json; charset=utf-8",
            "xliff": "application/xliff+xml; charset=utf-8",
            "xlsx": XLSX_CONTENT_TYPE,
        }[fmt]
        body = parts[0][1]
        return (body if isinstance(body, bytes) else body.encode("utf-8")), ctype, f"{stem}-{parts[0][0]}", report

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts:
            zf.writestr(name, text)
        zf.writestr(
            "export-report.json",
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        if screenshots:
            zf.writestr("README.txt", _BUNDLE_README)
            for arc, path in shots:
                zf.write(path, arcname=arc)
    return buf.getvalue(), "application/zip", f"{stem}-handoff.zip", report


def export_bundle(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str],
    namespaces: list[str] | None = None,
    only: str = "all",
) -> bytes:
    """ZIP with handoff CSV, README, and screenshot files for translators."""
    body, _, _, _ = render_export(
        cfg, catalog, locales=locales, namespaces=namespaces,
        fmt="csv", layout="single", only=only, screenshots=True,
    )
    return body
