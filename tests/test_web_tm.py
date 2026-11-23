"""Leverage, concordance, and TMX. No new status word."""

from __future__ import annotations

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.catalog.history import HistoryStore, make_history_event
from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.catalog.tmx import export_tmx
from llm_localizator.core.hash import src_hash
from llm_localizator.ops.status import collect, op_status
from llm_localizator.ops.tm import op_concordance, op_tm_import
from llm_localizator.ops.types import ConcordanceRequest, StatusRequest, TmImportRequest
from llm_localizator.web.shell import render_shell

from .conftest import setup_project

SOURCE = {
    "board": "Board",
    "hello": "Hello",
    "note": "Note",
    "tip": "Tip",
    "gone": "Gone",
    "same": "Hello",
}


def _project(tmp_path, make_config):
    setup_project(tmp_path, SOURCE, existing={
        "board": "Rozdanie",
        "hello": "Cześć",
        "note": "Notatka",
        "tip": "Wskazówka",
        "gone": "Zniknęło",
        "same": "Witaj",
    })
    cfg = make_config(tmp_path)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "board", make_entry("Board", "m", provider="ollama"))
    state.record("pl", "app", "hello", make_entry("Hello", "m", provider="ollama"))
    state.record("pl", "app", "note", make_entry("Note", "human", provider="human"))
    state.record("pl", "app", "tip", make_entry("Tip", "cursor-agent", provider="agent"))
    state.save("pl")
    history = HistoryStore(cfg.history_root())
    history.append("pl", make_history_event(
        namespace="app", key="board", prev=None, next_text="Rozdanie",
        model="m", status="machine", src_sha=src_hash("Board"), trigger="tm-hit",
        provider="ollama",
    ))
    history.append("pl", make_history_event(
        namespace="app", key="hello", prev=None, next_text="Cześć",
        model="m", status="machine", src_sha=src_hash("Hello"), trigger="translate",
        provider="ollama",
    ))
    return cfg


def test_leverage_four_buckets_and_a_missing_key(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    from llm_localizator.catalog import build_catalog

    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    row = collect(cfg, catalog)[0]
    assert row.tm_reused == 1
    assert row.llm_generated == 1
    assert row.human_edited == 1
    assert row.agent_edited == 1
    assert row.imported == 0
    assert row.missing + row.no_record == 2
    lines = op_status(cfg, StatusRequest()).lines
    assert any(line.strip() == "leverage: tm=1 llm=1 human=1 agent=1 imported=0" for line in lines)


def test_concordance_hits_and_keeps_superseded(tmp_path) -> None:
    tm = TranslationMemory(tmp_path / "tm")
    tm.record(locale="pl", source="Board", text="Płyta", model="old")
    tm.record(locale="pl", source="Board", text="Rozdanie", model="new")
    tm.record(locale="pl", source="Hello", text="Cześć board", model="m")
    assert tm.concordance("pl", "  ") == []
    source_hits = tm.concordance("pl", "board", target=False)
    assert {hit.entry.text for hit in source_hits} == {"Płyta", "Rozdanie"}
    marked = [hit for hit in source_hits if hit.superseded]
    assert len(marked) == 1
    assert marked[0].entry.text == "Płyta"
    target_only = tm.concordance("pl", "cześć", source=False)
    assert len(target_only) == 1
    assert target_only[0].entry.source == "Hello"
    assert tm.exact("pl", "Board").text == "Rozdanie"


def test_concordance_lists_sibling_keys(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    result = op_concordance(cfg, ConcordanceRequest(
        locale="pl", query="Hello", namespace="app", key="hello",
    ))
    siblings = {(row["namespace"], row["key"]) for row in result.data["siblings"]}
    assert ("app", "same") in siblings
    assert ("app", "hello") not in siblings


def test_tmx_round_trip_and_dry_run(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    tm = TranslationMemory(cfg.tm_root())
    tm.record(locale="pl", source="Board", text="Rozdanie", model="m", quality_score=0.9)
    xml = export_tmx(tm, "pl", "en")
    assert "Rozdanie" in xml
    assert "xml:lang" in xml or "lang=" in xml
    path = cfg.tm_root() / "pl.jsonl"
    before = path.read_bytes()
    dry = op_tm_import(cfg, TmImportRequest(locale="pl", tmx=xml, dry_run=True))
    assert dry.ok
    assert path.read_bytes() == before
    assert dry.data["counts"]["history"] == 0

    fresh = make_config(tmp_path / "other")
    (tmp_path / "other" / "messages" / "en").mkdir(parents=True)
    imported = op_tm_import(fresh, TmImportRequest(locale="pl", tmx=xml, conflict="always"))
    assert imported.ok
    assert TranslationMemory(fresh.tm_root()).exact("pl", "Board").text == "Rozdanie"


def test_tmx_import_writes_import_history_without_touching_catalogue(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<tmx version="1.4"><header srclang="en"/>'
        '<body><tu>'
        '<prop type="x-quality">0.5</prop>'
        '<tuv xml:lang="en"><seg>Board</seg></tuv>'
        '<tuv xml:lang="pl"><seg>Tablica</seg></tuv>'
        '</tu></body></tmx>'
    )
    from llm_localizator.catalog import build_catalog

    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    before = catalog.load("pl", "app")["board"]
    result = op_tm_import(cfg, TmImportRequest(locale="pl", tmx=xml, conflict="always"))
    assert result.data["counts"]["history"] == 1
    assert catalog.load("pl", "app")["board"] == before
    events = HistoryStore(cfg.history_root()).events_for("pl", "app", "board")
    assert events[-1].trigger == "import"
    assert events[-1].next == "Tablica"


def test_tm_page_does_not_bake_leverage() -> None:
    from pathlib import Path

    html = render_shell("tm")
    js = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "tm.js").read_text(encoding="utf-8")
    assert 'id="page-body"' in html
    assert 'id="tm-sub"' in html
    assert 'id="tm-import-btn"' in html
    assert 'id="tm-export-btn"' in html
    assert "page-head-tm" in html
    assert "/static/tm.js" in html
    assert "W-03 fills this page." not in html
    assert "/api/tm/leverage" in js
    assert "tm-table" in js
    assert "Import TMX" in html
    assert "tm=1" not in html


def test_concordance_payload_includes_match_pct_and_status(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    tm = TranslationMemory(cfg.tm_root())
    tm.record(locale="pl", source="Board", text="Rozdanie", model="m", provider="human", quality_score=0.9)
    tm.record(locale="pl", source="Hello board", text="Cześć", model="m", provider="ollama")
    result = op_concordance(cfg, ConcordanceRequest(locale="pl", query="board"))
    matches = result.data["matches"]
    assert matches
    assert all("matchPct" in hit and "status" in hit for hit in matches)
    human = next(hit for hit in matches if hit["translation"] == "Rozdanie")
    assert human["status"] == "human"
    assert human["matchPct"] == 100
    machine = next(hit for hit in matches if hit["translation"] == "Cześć")
    assert machine["status"] == "machine"
    assert machine["matchPct"] < 100


def test_leverage_payload_includes_tm_entries_and_totals(tmp_path, make_config) -> None:
    from llm_localizator.ops.tm import leverage_payload

    cfg = _project(tmp_path, make_config)
    tm = TranslationMemory(cfg.tm_root())
    tm.record(locale="pl", source="Board", text="Rozdanie", model="m")
    payload = leverage_payload(cfg)
    assert payload["tmEntries"] >= 1
    assert payload["tmLocales"] >= 1
    assert "totals" in payload
    assert payload["totals"]["classified"] == (
        payload["totals"]["tm_reused"]
        + payload["totals"]["llm_generated"]
        + payload["totals"]["human_edited"]
        + payload["totals"]["agent_edited"]
        + payload["totals"]["imported"]
    )

def test_concordance_fuzzy_mode_and_clamp(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    tm = TranslationMemory(cfg.tm_root())
    tm.record(locale="pl", source="Save your changes now", text="Zapisz zmiany", model="m", provider="human")
    tm.record(locale="pl", source="Delete the account", text="Usun konto", model="m")
    sub = op_concordance(cfg, ConcordanceRequest(locale="pl", query="save changes"))
    assert sub.data["matches"] == []  # not a substring
    fuzzy = op_concordance(cfg, ConcordanceRequest(
        locale="pl", query="Save your changes", mode="fuzzy", min_similarity=0.5))
    assert [m["translation"] for m in fuzzy.data["matches"]] == ["Zapisz zmiany"]
    assert 0 < fuzzy.data["matches"][0]["matchPct"] <= 100
    strict = op_concordance(cfg, ConcordanceRequest(
        locale="pl", query="Save", mode="fuzzy", min_similarity=1.0))
    assert strict.data["matches"] == []
    assert not op_concordance(cfg, ConcordanceRequest(locale="pl", query="x", mode="bogus")).ok


def test_concordance_http_clamps_params() -> None:
    from llm_localizator.web.handlers_get import _clamp_float

    assert _clamp_float("9", 0.55, 0.1, 1.0) == 1.0
    assert _clamp_float("-3", 0.55, 0.1, 1.0) == 0.1
    assert _clamp_float("nan", 0.55, 0.1, 1.0) == 0.55
    assert _clamp_float("abc", 0.55, 0.1, 1.0) == 0.55
    assert _clamp_float("", 0.55, 0.1, 1.0) == 0.55
