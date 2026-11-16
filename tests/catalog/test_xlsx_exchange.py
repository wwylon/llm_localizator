"""C-045: xlsx handoff and .pot as a read-only source (ADR-98)."""

from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.catalog import xlsx_exchange
from llm_localizator.catalog.export_formats import render_export
from llm_localizator.catalog.import_formats import (
    explode_import_file,
    import_documents,
    load_catalog,
)
from llm_localizator.ops.export_import import op_import
from llm_localizator.ops.types import ImportRequest
from llm_localizator.projects.config import load_config

openpyxl = pytest.importorskip("openpyxl")


def _project(tmp_path):
    toml = "\n".join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "messages/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "",
    ])
    (tmp_path / ".llm-localize.toml").write_text(toml, encoding="utf-8")
    data = {
        "app": ({"a": "One", "b": "=Two"}, {"a": "Eins"}),
        "admin": ({"c": "Three"}, {}),
    }
    for ns, (en, de) in data.items():
        for loc, msgs in (("en", en), ("de", de)):
            d = tmp_path / "messages" / loc
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{ns}.json").write_text(json.dumps(msgs), encoding="utf-8")
    return load_config(tmp_path / ".llm-localize.toml")


def _book(body: bytes):
    return openpyxl.load_workbook(io.BytesIO(body))


def test_export_has_one_sheet_per_namespace(tmp_path):
    cfg = _project(tmp_path)
    body, ctype, filename, _ = render_export(cfg, load_catalog(cfg), locales=["de"], fmt="xlsx")
    assert ctype == xlsx_exchange.XLSX_CONTENT_TYPE and filename.endswith(".xlsx")
    book = _book(body)
    assert sorted(book.sheetnames) == ["admin", "app"]
    header = [c.value for c in book["app"][1]]
    assert header[:4] == ["namespace", "key", "source", "de"]


def test_export_neutralises_formulas(tmp_path):
    cfg = _project(tmp_path)
    body, *_ = render_export(cfg, load_catalog(cfg), locales=["de"], fmt="xlsx")
    ws = _book(body)["app"]
    cells = {ws.cell(r, 2).value: ws.cell(r, 3) for r in range(2, ws.max_row + 1)}
    assert cells["b"].value == "'=Two" and cells["b"].data_type == "s"


def test_round_trip_through_import(tmp_path):
    cfg = _project(tmp_path)
    body, *_ = render_export(cfg, load_catalog(cfg), locales=["de"], fmt="xlsx")
    book = _book(body)
    ws = book["app"]
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, 2).value == "b":
            ws.cell(r, 4).value = "Zwei"
    out = io.BytesIO()
    book.save(out)
    docs, error = explode_import_file("edit.xlsx", raw=out.getvalue())
    assert error is None
    result = import_documents(cfg, load_catalog(cfg), docs, locales=["de"])
    assert result["ok"] and result["accepted"] == 1
    assert load_catalog(cfg).load("de", "app")["b"] == "Zwei"


def test_import_via_op_base64_and_zip(tmp_path):
    cfg = _project(tmp_path)
    body, *_ = render_export(cfg, load_catalog(cfg), locales=["de"], fmt="xlsx")
    book = _book(body)
    book["admin"].cell(2, 4).value = "Drei"
    out = io.BytesIO()
    book.save(out)
    raw = out.getvalue()
    res = op_import(cfg, ImportRequest(
        files=[{"name": "e.xlsx", "base64": base64.b64encode(raw).decode()}],
        locales=["de"], dry_run=True,
    ))
    assert res.ok and res.data["accepted"] == 1
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("inner.xlsx", raw)
    docs, error = explode_import_file("pack.zip", raw=zbuf.getvalue())
    assert error is None and docs[0][0] == "pack.zip:inner.xlsx"


def test_xls_and_corrupt_files_are_refused_clearly():
    docs, error = explode_import_file("old.xls", raw=b"x")
    assert docs == [] and ".xlsx" in error
    docs, error = explode_import_file("bad.xlsx", raw=b"not a workbook")
    assert docs == [] and "bad.xlsx" in error


def test_sheet_with_other_header_is_refused():
    book = openpyxl.Workbook()
    book.active.append(["namespace", "key", "source", "de"])
    other = book.create_sheet("other")
    other.append(["x", "y"])
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(ValueError, match="different header"):
        xlsx_exchange.xlsx_to_csv_text(out.getvalue())


def test_missing_extra_is_a_friendly_error(monkeypatch, tmp_path):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "openpyxl":
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    cfg = _project(tmp_path)
    with pytest.raises(xlsx_exchange.XlsxUnavailable, match="xlsx"):
        render_export(cfg, load_catalog(cfg), locales=["de"], fmt="xlsx")


POT = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

#. Greeting
msgid "Hello"
msgstr ""

msgid "One file"
msgid_plural "%(n)s files"
msgstr[0] ""
msgstr[1] ""
'''


def test_pot_is_a_read_only_source(tmp_path):
    d = tmp_path / "po" / "en"
    d.mkdir(parents=True)
    (d / "app.pot").write_text(POT, encoding="utf-8")
    cat = build_catalog("po", tmp_path, "po/{locale}/{namespace}.po", "en")
    assert cat.namespaces() == ["app"]
    src = cat.load("en", "app")
    assert src["Hello"] == "Hello"
    assert "plural" in src["One file"]
    assert cat.load_entries("en", "app")["Hello"].note == "Greeting"
    with pytest.raises(ValueError, match="read-only"):
        cat.save("en", "app", src)
