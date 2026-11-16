import zipfile
import io

from llm_localizator.catalog.export_formats import export_bundle, export_csv
from llm_localizator.catalog.import_formats import import_csv

from ..conftest import write_json
from ..pipeline.test_translate import setup_project


def test_csv_round_trip(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    text = export_csv(cfg, catalog, locales=["pl"])
    assert "greet" in text
    assert "Cześć" in text
    assert "verified_at" not in text.splitlines()[0]
    result = import_csv(cfg, catalog, text.replace("Cześć", "Witaj"), locales=["pl"])
    assert result["accepted"] == 1
    assert catalog.load("pl", "app")["greet"] == "Witaj"


def test_xliff_round_trip(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    from llm_localizator.catalog.export_formats import export_xliff
    from llm_localizator.catalog.import_formats import import_xliff

    text = export_xliff(cfg, catalog, locales=["pl"])
    assert "<xliff" in text and "greet" in text
    result = import_xliff(cfg, catalog, text.replace("Cześć", "Witaj"), locales=["pl"])
    assert result["accepted"] == 1
    assert catalog.load("pl", "app")["greet"] == "Witaj"


def test_xliff_quotes_unit_id_attributes(project_root, make_config, make_catalog) -> None:
    setup_project(
        project_root,
        {'say"hi': 'Hello "there"'},
        existing={'say"hi': "Cześć"},
    )
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    from llm_localizator.catalog.export_formats import export_xliff
    from xml.etree import ElementTree as ET

    text = export_xliff(cfg, catalog, locales=["pl"])
    # Unescaped quote must not terminate a double-quoted attribute early.
    assert 'id="app.say"hi"' not in text
    root = ET.fromstring(text)
    ns = {"x": "urn:oasis:names:tc:xliff:document:1.2"}
    units = root.findall(".//x:trans-unit", ns)
    assert len(units) == 1
    assert units[0].get("id") == 'app.say"hi'


def test_headerless_csv_imports_one_locale(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    text = export_csv(cfg, catalog, locales=["pl"])
    body = "\n".join(text.splitlines()[1:]) + "\n"
    body = body.replace("Cześć", "Witaj")
    result = import_csv(cfg, catalog, body, locales=["pl"], filename="deepseek.csv")
    assert result["ok"] is True
    assert result["positional"] is True
    assert catalog.load("pl", "app")["greet"] == "Witaj"
    assert any("headerless CSV" in w for w in result.get("warnings") or [])


def test_headerless_rejoins_unquoted_commas(project_root, make_config, make_catalog) -> None:
    setup_project(
        project_root,
        {"greet": "Hello, world", "bye": "Goodbye"},
        existing={"greet": "Cześć", "bye": "Pa"},
    )
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    text = (
        "app,greet,\"Hello, world\",Witaj, świecie,,,,,,,llm_reviewed,0.9\n"
        "app,bye,Goodbye,Pa,Notatka dla tłumacza,,,,,llm_reviewed,0.8\n"
    )
    result = import_csv(cfg, catalog, text, locales=["pl"])
    assert result["ok"] is True
    assert catalog.load("pl", "app")["greet"] == "Witaj, świecie"
    assert catalog.load("pl", "app")["bye"] == "Pa"
    assert result["files"][0]["repaired"] is True
    assert any("rejoined" in w for w in result.get("warnings") or [])
    assert any("headerless" in w for w in result.get("warnings") or [])


def test_headerless_csv_rejects_several_locales(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root, targets=["pl", "de"])
    catalog = make_catalog(cfg)
    text = export_csv(cfg, catalog, locales=["pl"])
    body = "\n".join(text.splitlines()[1:]) + "\n"
    result = import_csv(cfg, catalog, body, locales=["pl", "de"])
    assert result["ok"] is False
    assert result["structural"]
    assert catalog.load("pl", "app")["greet"] == "Cześć"


def test_ragged_csv_is_structural(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    result = import_csv(cfg, catalog, "a,b,c,d\n1,2\n", locales=["pl"])
    assert result["ok"] is False
    assert "column" in result["structural"]
    assert catalog.load("pl", "app")["greet"] == "Cześć"


def test_verified_at_in_file_is_not_applied(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog import StateStore

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    text = (
        "namespace,key,source,pl,note,llmNote,maxChars,screen,image,fullKey,"
        "verified_at,status_pl,score_pl\n"
        "app,greet,Hello,Witaj,,,,,,,2020-01-01T00:00:00Z,,\n"
    )
    result = import_csv(cfg, catalog, text, locales=["pl"])
    assert result["accepted"] == 1
    entry = StateStore(cfg.state_root()).entry("pl", "app", "greet")
    assert not (entry or {}).get("verified_at")


def test_unchanged_keeps_score_changed_drops_it(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog import ScoreStore, StateStore

    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"},
                  existing={"greet": "Cześć", "bye": "Pa"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "greet", score=0.42, signals=[], text="Cześć")
    scores.record("pl", "app", "bye", score=0.7, signals=[], text="Pa")
    scores.save("pl")
    text = (
        "namespace,key,source,pl\n"
        "app,greet,Hello,Cześć\n"
        "app,bye,Goodbye,Do widzenia\n"
    )
    result = import_csv(cfg, catalog, text, locales=["pl"], model="deepseek")
    assert result["unchanged"] == 1
    assert result["accepted"] == 1
    fresh = ScoreStore(cfg.scores_root())
    assert fresh.get("pl", "app", "greet")["quality_score"] == 0.42
    assert fresh.get("pl", "app", "bye") is None
    change = result["changes"][0]
    assert change["previous"] == "Pa"
    assert change["next"] == "Do widzenia"
    assert change["status"] == "imported"
    entry = StateStore(cfg.state_root()).entry("pl", "app", "bye")
    assert entry["model"] == "deepseek"
    assert entry["provider"] == "import"
    assert entry["status"] == "imported"


def test_coverage_counts_new_translations(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    text = "namespace,key,source,pl\napp,greet,Hello,Witaj\n"
    result = import_csv(cfg, catalog, text, locales=["pl"])
    cov = result["coverage"][0]
    assert cov["before"] == 0
    assert cov["after"] == 1
    assert cov["total"] == 2
    assert result["changes"][0]["kind"] == "new"


def test_json_round_trip(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog.export_formats import export_json
    from llm_localizator.catalog.import_formats import import_json
    import json

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    payload = json.loads(export_json(cfg, catalog, locales=["pl"]))
    payload["rows"][0]["targets"]["pl"] = "Witaj"
    result = import_json(cfg, catalog, json.dumps(payload), locales=["pl"])
    assert result["accepted"] == 1
    assert catalog.load("pl", "app")["greet"] == "Witaj"


def test_untranslated_filter_is_per_locale(project_root, make_config, make_catalog) -> None:
    import io
    import zipfile
    from llm_localizator.catalog import StateStore, make_entry
    from llm_localizator.catalog.export_formats import render_export

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    write_json(project_root / "messages" / "de" / "app.json", {"greet": "Hello"})
    cfg = make_config(project_root, targets=["pl", "de"])
    state = StateStore(cfg.state_root())
    state.record("pl", "app", "greet", make_entry("Hello", "m", "machine"))
    state.record("de", "app", "greet", make_entry("Hello", "m", "machine"))
    state.save("pl")
    state.save("de")
    catalog = make_catalog(cfg)
    both = export_csv(cfg, catalog, locales=["pl", "de"], only="untranslated")
    assert "greet" in both
    body, _ctype, _name, _report = render_export(
        cfg, catalog, locales=["pl", "de"], fmt="csv",
        layout="per-locale", only="untranslated",
    )
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        pl = zf.read("pl.csv").decode("utf-8")
        de = zf.read("de.csv").decode("utf-8")
    assert "greet" not in pl
    assert "greet" in de


def test_multi_file_import_and_bad_sibling(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog.import_formats import import_documents

    setup_project(
        project_root, {"a": "A", "b": "B"}, existing={"a": "a", "b": "b"},
    )
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    good = "namespace,key,source,pl\napp,a,A,AA\n"
    bad = import_documents(
        cfg, catalog,
        [("a.csv", good), ("b.json", "{")],
        locales=["pl"],
    )
    assert bad["ok"] is False
    assert bad["blocked"] is True
    assert catalog.load("pl", "app")["a"] == "a"
    ok = import_documents(
        cfg, catalog,
        [
            ("a.csv", good),
            ("b.csv", "namespace,key,source,pl\napp,b,B,BB\n"),
        ],
        locales=["pl"],
        model="deepseek",
    )
    assert ok["accepted"] == 2
    assert catalog.load("pl", "app") == {"a": "AA", "b": "BB"}


def test_export_bundle_includes_csv_and_screenshots(
    project_root, make_config, make_catalog,
) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    ctx = project_root / "i18n" / "context"
    shots = ctx / "screenshots"
    shots.mkdir(parents=True)
    (shots / "table.png").write_bytes(b"\x89PNG\r\n")
    (ctx / "app.json").write_text(
        '{"greet": {"note": "label", "screen": "table"}}',
        encoding="utf-8",
    )
    cfg = make_config(project_root, context_dir=ctx)
    catalog = make_catalog(cfg)
    data = export_bundle(cfg, catalog, locales=["pl"])
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "handoff.csv" in names
        assert "README.txt" in names
        assert "screenshots/table.png" in names
        csv_text = zf.read("handoff.csv").decode("utf-8")
    assert "image" in csv_text.splitlines()[0]
    assert "screenshots/table.png" in csv_text
    assert "export-report.json" in names


def test_export_file_count_splits_rows(project_root, make_config, make_catalog) -> None:
    import json
    from llm_localizator.catalog.export_formats import render_export

    setup_project(project_root, {"a": "A", "b": "B", "c": "C", "d": "D"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    body, ctype, name, report = render_export(
        cfg, catalog, locales=["pl"], fmt="csv", file_count=2,
    )
    assert ctype == "application/zip"
    assert name.endswith("-handoff.zip")
    assert report["rows"] == 4
    assert report["requested_files"] == 2
    assert [item["rows"] for item in report["files"]] == [2, 2]
    assert report["by_locale"]["pl"]["empty"] == 4
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        names = set(zf.namelist())
        assert {"handoff-01.csv", "handoff-02.csv", "export-report.json"} <= names
        first = zf.read("handoff-01.csv").decode("utf-8").splitlines()
        second = zf.read("handoff-02.csv").decode("utf-8").splitlines()
        packed = json.loads(zf.read("export-report.json").decode("utf-8"))
    assert first[0].startswith("namespace,key,source,")
    assert len(first) == 3 and len(second) == 3
    keys = {line.split(",")[1] for line in first[1:] + second[1:]}
    assert keys == {"a", "b", "c", "d"}
    assert packed["rows"] == 4


def test_export_file_count_caps_when_fewer_rows(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog.export_formats import format_export_report, render_export

    setup_project(project_root, {"only": "One"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    body, ctype, _name, report = render_export(
        cfg, catalog, locales=["pl"], fmt="csv", file_count=4,
    )
    assert ctype.startswith("text/csv")
    assert body.startswith(b"namespace,key,source,")
    assert report["requested_files"] == 4
    assert report["file_count"] == 1
    assert report["packed"] is False
    text = "\n".join(format_export_report(report))
    assert "asked for 4 files; wrote 1" in text
    assert "only" in text


def test_export_report_status_mix(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog import StateStore, make_entry
    from llm_localizator.catalog.export_formats import render_export

    setup_project(
        project_root,
        {"greet": "Hello", "bye": "Goodbye"},
        existing={"greet": "Cześć", "bye": "Goodbye"},
    )
    cfg = make_config(project_root)
    state = StateStore(cfg.state_root())
    state.record("pl", "app", "greet", make_entry("Hello", "m", "machine"))
    state.record("pl", "app", "bye", make_entry("Goodbye", "m", "machine"))
    state.save("pl")
    catalog = make_catalog(cfg)
    _body, _ctype, _name, report = render_export(
        cfg, catalog, locales=["pl"], fmt="csv",
    )
    pl = report["by_locale"]["pl"]
    assert pl["filled"] == 1
    assert pl["empty"] == 1
    assert pl["statuses"]["machine"] == 1
    assert pl["statuses"]["untranslated"] == 1
    assert report["files"][0]["namespaces"]["app"] == 2
    assert {item["key"] for item in report["keys"]} == {"greet", "bye"}


def test_merge_coverage_clamps_negative_delta_and_sums_totals() -> None:
    from llm_localizator.catalog.import_formats import _merge_coverage

    merged = _merge_coverage([
        [{"locale": "pl", "before": 5, "after": 3, "total": 10}],
        [{"locale": "pl", "before": 3, "after": 4, "total": 10}],
    ])
    row = merged[0]
    assert row["before"] == 5
    assert row["after"] == 6
    assert row["total"] == 20


def test_headerless_extra_cells_are_structural(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    text = "app,greet,Hello,Hello,world,extra\n"
    result = import_csv(cfg, catalog, text, locales=["pl"])
    assert result["ok"] is False
    assert "line" in result["structural"]
    assert catalog.load("pl", "app")["greet"] == "Cześć"


def test_import_appends_history_after_state(project_root, make_config, make_catalog) -> None:
    from unittest.mock import patch

    from llm_localizator.catalog.history import HistoryStore

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    seen = {}
    real = HistoryStore.append

    def wrapped(self, locale, event):
        assert catalog.load("pl", "app")["greet"] == "Witaj"
        raw = (cfg.state_dir / "pl.json").read_text(encoding="utf-8")
        assert "app.greet" in raw
        seen["ok"] = True
        return real(self, locale, event)

    with patch.object(HistoryStore, "append", wrapped):
        result = import_csv(
            cfg, catalog,
            "namespace,key,source,pl\napp,greet,Hello,Witaj\n",
            locales=["pl"],
        )
    assert result["ok"] is True
    assert seen["ok"] is True


def test_xliff_imports_a_new_note(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog.export_formats import export_xliff
    from llm_localizator.catalog.import_formats import import_xliff
    from llm_localizator.projects.context import ContextNotes

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    ctx = project_root / "context"
    cfg = make_config(project_root, context_dir=ctx)
    catalog = make_catalog(cfg)
    text = export_xliff(cfg, catalog, locales=["pl"])
    text = text.replace(
        "</source>",
        "</source>\n        <note>button label</note>",
        1,
    )
    result = import_xliff(cfg, catalog, text.replace("Cześć", "Witaj"), locales=["pl"])
    assert result["accepted"] == 1
    assert ContextNotes(ctx).note("app", "greet") == "button label"
    assert "skipped_notes" not in result


def test_xliff_keeps_an_existing_note(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog.export_formats import export_xliff
    from llm_localizator.catalog.import_formats import import_xliff
    from llm_localizator.projects.context import ContextNotes, write_context_entry

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    ctx = project_root / "context"
    write_context_entry(ctx, "app", "greet", {"note": "keep me", "llmNote": "short"})
    cfg = make_config(project_root, context_dir=ctx)
    catalog = make_catalog(cfg)
    text = export_xliff(cfg, catalog, locales=["pl"])
    text = text.replace("<note>keep me short</note>", "")
    text = text.replace("</source>", "</source>\n        <note>other</note>", 1)
    result = import_xliff(cfg, catalog, text.replace("Cześć", "Witaj"), locales=["pl"])
    assert result["accepted"] == 1
    notes = ContextNotes(ctx)
    assert notes.note("app", "greet") == "keep me"
    assert notes.llm_note("app", "greet") == "short"
    assert result["skipped_notes"][0]["note"] == "other"


def test_import_decodes_utf16_and_unescapes_formula_guard() -> None:
    from llm_localizator.catalog.import_formats import _parse_csv_table
    from llm_localizator.catalog.io import decode_import_bytes

    raw = "namespace,key,pl\napp,a,'=SUM\n".encode("utf-16")
    rows, _loc, *_ = _parse_csv_table(decode_import_bytes(raw), ["pl"], {"pl"})
    assert rows[0][1]["pl"] == "=SUM"


def test_xliff_import_keeps_inline_markup_text(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    from llm_localizator.catalog.import_formats import import_xliff

    doc = (
        '<?xml version="1.0"?><xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">'
        '<file source-language="en" target-language="pl" datatype="plaintext"><body>'
        '<trans-unit id="app.greet"><source>Hello</source>'
        '<target>Witaj <g id="1">świecie</g> teraz</target></trans-unit>'
        "</body></file></xliff>"
    )
    result = import_xliff(cfg, catalog, doc, locales=["pl"])
    assert result["accepted"] == 1
    assert catalog.load("pl", "app")["greet"] == "Witaj świecie teraz"


def test_csv_import_loads_each_catalogue_file_once(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {k: k.upper() for k in "abcdef"}, existing={})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    calls: list[tuple] = []
    real = catalog.load

    def counting(locale, namespace=None):
        calls.append((locale, namespace))
        return real(locale, namespace)

    catalog.load = counting
    body = "namespace,key,pl\napp,a,Aa\napp,b,Bb\napp,c,Cc\n"
    result = import_csv(cfg, catalog, body, locales=["pl"])
    assert result["accepted"] >= 1
    # per-file loads per pass, not per row (dry-run + apply + merge)
    assert calls.count(("pl", "app")) <= 3
    assert calls.count((cfg.source_locale, "app")) <= 3


def test_xliff2_round_trip_with_plural_and_notes(project_root, make_config, make_catalog) -> None:
    import pytest

    from llm_localizator.catalog.export_formats import export_xliff
    from llm_localizator.catalog.import_formats import import_xliff

    plural = "{n, plural, one {# plik} few {# pliki} many {# plików} other {# pliku}}"
    setup_project(project_root, {"files": "{n, plural, one {# file} other {# files}}"},
                  existing={"files": plural})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    text = export_xliff(cfg, catalog, locales=["pl"], version="2.0")
    assert 'version="2.0"' in text and 'trgLang="pl"' in text and "<unit " in text
    edited = text.replace("# pliku}", "# plikuu}")
    result = import_xliff(cfg, catalog, edited)
    assert result["accepted"] == 1
    assert "# plikuu" in catalog.load("pl", "app")["files"]
    with pytest.raises(ValueError):
        export_xliff(cfg, catalog, locales=["pl", "de"], version="2.0")
    with pytest.raises(ValueError):
        export_xliff(cfg, catalog, locales=["pl"], version="3.0")


def test_xliff2_import_reads_multi_segment_units_and_notes(
    project_root, make_config, make_catalog,
) -> None:
    from llm_localizator.catalog.import_formats import import_xliff

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    doc = (
        '<xliff version="2.0" xmlns="urn:oasis:names:tc:xliff:document:2.0" '
        'srcLang="en" trgLang="pl"><file id="f1"><unit id="app.greet">'
        "<notes><note>Casual greeting</note></notes>"
        "<segment><source>Hel</source><target>Wit</target></segment>"
        "<segment><source>lo</source><target>aj</target></segment>"
        "</unit></file></xliff>"
    )
    result = import_xliff(cfg, catalog, doc)
    assert result["accepted"] == 1
    assert catalog.load("pl", "app")["greet"] == "Witaj"


def test_csv_bom_option_round_trips(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cześć"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    plain = export_csv(cfg, catalog, locales=["pl"])
    with_bom = export_csv(cfg, catalog, locales=["pl"], bom=True)
    assert not plain.startswith("﻿")
    assert with_bom == "﻿" + plain
    result = import_csv(cfg, catalog, with_bom.replace("Cześć", "Witaj"), locales=["pl"])
    assert result["accepted"] == 1


def test_render_export_xliff2_and_bom_options(project_root, make_config, make_catalog) -> None:
    import pytest as _pytest

    from llm_localizator.catalog.export_formats import render_export

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cze"})
    write_json(project_root / "messages" / "de" / "app.json", {"greet": "Hallo"})
    cfg = make_config(project_root, targets=["pl", "de"])
    catalog = make_catalog(cfg)
    body, *_ = render_export(cfg, catalog, locales=["pl"], fmt="xliff", xliff_version="2.0")
    assert b'version="2.0"' in body and b'trgLang="pl"' in body
    body, *_ = render_export(cfg, catalog, locales=["pl"], fmt="csv", bom=True)
    assert body.startswith(bytes([0xEF, 0xBB, 0xBF]))
    with _pytest.raises(ValueError):
        render_export(cfg, catalog, locales=["pl", "de"], fmt="xliff", xliff_version="2.0")
    body, ctype, *_ = render_export(cfg, catalog, locales=["pl", "de"], fmt="xliff",
                                    xliff_version="2.0", layout="per-locale")
    assert ctype == "application/zip"


def test_import_crash_leaves_a_blocking_flush_journal(project_root, make_config, make_catalog, monkeypatch) -> None:
    import pytest as _pytest

    from llm_localizator.catalog import import_formats as imf
    from llm_localizator.catalog.flush_journal import FlushJournal, flush_block_message

    setup_project(project_root, {"a": "A"}, existing={"a": "a"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    doc = [("a.csv", "namespace,key,source,pl\napp,a,A,AA\n")]
    assert imf.import_documents(cfg, catalog, doc, locales=["pl"])["ok"]
    assert FlushJournal(cfg.state_root()).read() is None  # cleared on success

    real = imf.import_csv

    def crash(*a, **kw):
        if not kw.get("dry_run"):
            raise OSError("disk gone")
        return real(*a, **kw)

    monkeypatch.setattr(imf, "import_csv", crash)
    with _pytest.raises(OSError):
        imf.import_documents(cfg, catalog, doc, locales=["pl"])
    assert flush_block_message(cfg.state_root())


def test_xliff12_file_has_required_original_attribute(project_root, make_config, make_catalog) -> None:
    from llm_localizator.catalog.export_formats import export_xliff

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Cze"})
    cfg = make_config(project_root)
    text = export_xliff(cfg, make_catalog(cfg), locales=["pl"])
    assert "<file original=" in text
