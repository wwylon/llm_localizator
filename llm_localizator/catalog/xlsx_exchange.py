"""Excel ``.xlsx`` handoff: the CSV grid in a workbook (C-045, ADR-98).

The workbook holds exactly the columns of the CSV handoff, one sheet per namespace. Import turns
every sheet back into the same CSV text the importer already validates, so rules, reports and
the formula-injection guard are shared with ``import_csv`` and not forked.

``openpyxl`` is an optional extra (``pip install llm_localizator[xlsx]``); the core stays
dependency-light. ``.xls`` (the old binary format) is not read: save it as ``.xlsx`` first.
"""

from __future__ import annotations

import csv
import io
import re

__all__ = [
    "MAX_ROWS", "XLSX_CONTENT_TYPE", "XlsxUnavailable", "grid_to_xlsx", "xlsx_to_csv_text",
]

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ROWS = 100_000
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


class XlsxUnavailable(ValueError):
    """Raised when the optional ``openpyxl`` extra is missing."""


def _openpyxl():
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - exercised through monkeypatch in tests
        raise XlsxUnavailable(
            "xlsx needs the optional 'xlsx' extra: pip install \"llm_localizator[xlsx]\""
        ) from exc
    return openpyxl


def _sheet_title(name: str, taken: set[str]) -> str:
    base = _BAD_SHEET_CHARS.sub("_", name or "default").strip("'") or "default"
    base = base[:31]
    title, n = base, 2
    while title.lower() in taken:
        suffix = f"~{n}"
        title = base[: 31 - len(suffix)] + suffix
        n += 1
    taken.add(title.lower())
    return title


def grid_to_xlsx(columns: list[str], sheets: list[tuple[str, list[dict]]]) -> bytes:
    """A workbook with ``columns`` as the header row of every sheet.

    ``sheets`` is ``(name, records)``; ``records`` are already formula-safe strings. Cells are
    written as text so Excel never evaluates them.
    """
    openpyxl = _openpyxl()
    book = openpyxl.Workbook()
    book.remove(book.active)
    taken: set[str] = set()
    for name, records in sheets or [("default", [])]:
        sheet = book.create_sheet(_sheet_title(name, taken))
        sheet.append(columns)
        for record in records:
            sheet.append([str(record.get(col, "")) for col in columns])
        for row in sheet.iter_rows(min_row=1):
            for cell in row:
                if cell.value is not None:
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def xlsx_to_csv_text(raw: bytes) -> str:
    """CSV text of every sheet (one header row, the sheets' rows appended)."""
    openpyxl = _openpyxl()
    try:
        book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # a corrupt or non-xlsx file
        raise ValueError(f"not a readable .xlsx workbook: {exc}") from exc
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    header: list[str] | None = None
    total = 0
    try:
        for sheet in book.worksheets:
            first = True
            for cells in sheet.iter_rows(values_only=True):
                row = [_cell_text(c) for c in cells]
                while row and not row[-1]:
                    row.pop()
                if not row:
                    continue
                if first:
                    first = False
                    if header is None:
                        header = row
                        writer.writerow(row)
                    elif [c.strip().lower() for c in row] != [c.strip().lower() for c in header]:
                        raise ValueError(
                            f"sheet {sheet.title!r} has a different header from the first sheet"
                        )
                    continue
                total += 1
                if total > MAX_ROWS:
                    raise ValueError(f"workbook has more than {MAX_ROWS} rows")
                writer.writerow(row)
    finally:
        book.close()
    if header is None:
        raise ValueError("workbook is empty")
    return out.getvalue()
