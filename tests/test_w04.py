"""Glossary edits, source warnings, lock, and the read-only commands."""

from __future__ import annotations

import json

from llm_localizator.catalog import StateStore, build_catalog, make_entry
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.state import state_key
from llm_localizator.ops.glossary import op_glossary_import
from llm_localizator.ops.source_ops import op_glossary_propose, op_impact, op_pseudo
from llm_localizator.ops.types import GlossaryImportRequest, PseudoRequest
from llm_localizator.pipeline.improve import collect_improve_keys
from llm_localizator.pipeline.recording import record_candidate
from llm_localizator.pipeline.translate import collect_work
from llm_localizator.pipeline.validate import run_validation
from llm_localizator.projects.glossary_edit import mutate_glossary
from llm_localizator.web import build_state
from llm_localizator.web.server import validate_key
from llm_localizator.web.shell import render_shell

from .conftest import setup_project, write_json


def test_glossary_page_keeps_domain_files(tmp_path) -> None:
    root = tmp_path / "glossary"
    root.mkdir()
    play = {
        "owner": "play",
        "doNotTranslate": ["Stayman"],
        "terms": {"board": {"pl": "rozdanie"}},
    }
    (root / "play.json").write_text(json.dumps(play, indent=2) + "\n", encoding="utf-8")
    before = (root / "play.json").read_bytes()
    mutate_glossary(
        root, domain="global", action="add", term="trick", kind="term",
        translations={"pl": "lewa"}, note="card",
    )
    assert (root / "play.json").read_bytes() == before
    saved = json.loads((root / "global.json").read_text(encoding="utf-8"))
    assert saved["terms"]["trick"]["pl"] == "lewa"
    assert saved["terms"]["trick"]["note"] == "card"
    assert "play" not in saved


def test_bad_csv_names_the_path_and_writes_nothing(tmp_path, make_config) -> None:
    gloss = tmp_path / "glossary"
    gloss.mkdir()
    (gloss / "global.json").write_text('{"doNotTranslate": [], "terms": {}}\n', encoding="utf-8")
    (gloss / "play.json").write_text(
        '{"extra": true, "doNotTranslate": [], "terms": {}}\n', encoding="utf-8",
    )
    before_global = (gloss / "global.json").read_bytes()
    before_play = (gloss / "play.json").read_bytes()
    bad = tmp_path / "bad.csv"
    bad.write_text("term,locale,translation,forbidden,note\n,pl,x,,\n", encoding="utf-8")
    cfg = make_config(tmp_path, glossary_path=gloss)
    result = op_glossary_import(cfg, GlossaryImportRequest(file=str(bad)))
    assert not result.ok
    assert str(bad) in result.summary
    assert (gloss / "global.json").read_bytes() == before_global
    assert (gloss / "play.json").read_bytes() == before_play


def test_csv_dry_run_writes_nothing(tmp_path, make_config) -> None:
    gloss = tmp_path / "glossary.json"
    gloss.write_text('{"doNotTranslate": [], "terms": {}}\n', encoding="utf-8")
    before = gloss.read_bytes()
    good = tmp_path / "terms.csv"
    good.write_text(
        "term,locale,translation,forbidden,note\nboard,pl,rozdanie,plyta,card\n",
        encoding="utf-8",
    )
    cfg = make_config(tmp_path, glossary_path=gloss)
    result = op_glossary_import(cfg, GlossaryImportRequest(file=str(good), dry_run=True))
    assert result.ok
    assert result.data["dry_run"] is True
    assert gloss.read_bytes() == before


def test_forbidden_word_needs_no_model(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"board": "Board"}, existing={"board": "rozdanie"})
    write_json(tmp_path / "glossary.json", {
        "doNotTranslate": [],
        "terms": {"board": {"pl": "rozdanie", "pl_forbidden": ["plyta"]}},
    })
    cfg = make_config(tmp_path, glossary_path=tmp_path / "glossary.json")
    result = validate_key(build_state(cfg), "pl", "app", "board", "To jest plyta")
    assert any(item["id"] == "V04" and "plyta" in item["message"] for item in result["errors"])
    # "Board" is a whole label: missing the approved word blocks (ADR-127).
    missing = validate_key(build_state(cfg), "pl", "app", "board", "To jest cos innego")
    assert missing["ok"] is False
    assert any(item["id"] == "V04" and "rozdanie" in item["message"] for item in missing["errors"])


def test_missing_approved_term_in_a_sentence_is_a_warning(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"board": "Show the board"}, existing={"board": "Pokaż rozdanie"})
    write_json(tmp_path / "glossary.json", {
        "doNotTranslate": [],
        "terms": {"board": {"pl": "rozdanie", "pl_forbidden": ["plyta"]}},
    })
    cfg = make_config(tmp_path, glossary_path=tmp_path / "glossary.json")
    missing = validate_key(build_state(cfg), "pl", "app", "board", "Pokaż coś innego")
    assert missing["ok"] is True
    assert any(item["id"] == "V13" for item in missing["errors"])


def test_locked_key_is_skipped_and_the_state_key_stays(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"hello": "Hello", "other": "Other"}, existing={
        "hello": "Czesc", "other": "Inne",
    })
    cfg = make_config(tmp_path)
    state = StateStore(cfg.state_dir)
    locked = make_entry("Hello", "m")
    locked["locked"] = True
    state.record("pl", "app", "hello", locked)
    state.record("pl", "app", "other", make_entry("Other", "m"))
    state.save("pl")
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    work = collect_work(
        cfg, catalog, state, locales=["pl"], namespaces=["app"], force=True,
        only_keys={"pl": {state_key("app", "hello"), state_key("app", "other")}},
    )
    assert state_key("app", "hello") == "app.hello"
    assert "hello" not in {item.key for item in work}
    assert "other" in {item.key for item in work}
    scores = ScoreStore(cfg.scores_root())
    scores.record("pl", "app", "hello", score=0.1, signals=[], text="Czesc")
    scores.record("pl", "app", "other", score=0.1, signals=[], text="Inne")
    improved = collect_improve_keys(
        cfg, catalog, state, scores, locales=["pl"], namespaces=["app"], limit=10,
    )
    assert "hello" not in {row[2] for row in improved}
    record_candidate(
        state=state, scores=scores, history=HistoryStore(cfg.history_root()),
        locale="pl", namespace="app", key="hello", source="Hello", previous="Czesc",
        text="Witaj", model="human", quality_score=1, quality_signals=[],
        trigger="web-edit", status="human", provider="human",
    )
    assert state.entry("pl", "app", "hello")["locked"] is True


def test_source_warnings_fire_once_and_stay_quiet(tmp_path, make_config) -> None:
    setup_project(tmp_path, {
        "a": "Hello",
        "b": "Hello",
        "count": "You have {n}",
        "html": "Hello <b>there</b>",
        "plain": "Good evening",
        "clean": "Good morning",
    }, existing={
        "a": "Czesc", "b": "Witaj", "count": "Masz {n}",
        "html": "Czesc <b>tam</b>", "plain": "Dobry wieczor", "clean": "Dzien dobry",
    })
    write_json(tmp_path / "context" / "app.json", {"clean": {"note": "greeting", "html": False}})
    cfg = make_config(tmp_path, context_dir=tmp_path / "context")
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    report = run_validation(cfg, catalog)
    v18 = [item for item in report.findings if item.check == "V18"]
    v19 = [item for item in report.findings if item.check == "V19"]
    v20 = [item for item in report.findings if item.check == "V20"]
    assert len(v18) == 1
    assert "a" in v18[0].message and "b" in v18[0].message
    assert [item.key for item in v19] == ["count"]
    assert [item.key for item in v20] == ["html"]
    assert "plain" not in {item.key for item in v19}
    assert "clean" not in {item.key for item in v19 + v20}

    brace = make_config(
        tmp_path, context_dir=tmp_path / "context", catalog_standard="brace",
    )
    brace_report = run_validation(brace, catalog)
    assert any(item.check == "V19" and item.key == "count" for item in brace_report.findings)
    assert any(item.check == "V20" and item.key == "html" for item in brace_report.findings)


def test_propose_is_stable_and_writes_nothing(tmp_path, make_config) -> None:
    source = {f"k{i}": "trick taken now" for i in range(4)}
    setup_project(tmp_path, source)
    cfg = make_config(tmp_path)
    before = sorted(path.name for path in tmp_path.rglob("*") if path.is_file())
    first = op_glossary_propose(cfg)
    second = op_glossary_propose(cfg)
    assert first.lines == second.lines
    assert any(line.startswith("trick taken\t") for line in first.lines)
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == before


def test_impact_lists_only_stale_locales(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"hello": "Hello", "same": "Hello", "other": "Other"})
    cfg = make_config(tmp_path, targets=["pl", "de"])
    state = StateStore(cfg.state_dir)
    stale = make_entry("Hello old", "m")
    state.record("pl", "app", "hello", stale)
    state.record("de", "app", "hello", make_entry("Hello", "m"))
    state.save("pl")
    state.save("de")
    result = op_impact(cfg)
    text = "\n".join(result.lines)
    assert "app.hello stale: pl" in text
    assert "de" not in text
    assert "app.other" not in text
    assert "1 keys share this source" in text


def test_pseudo_leaves_the_source_catalogue(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"greet": "Hello {name}"})
    cfg = make_config(tmp_path)
    source = tmp_path / "messages" / "en" / "app.json"
    before = source.read_bytes()
    state_before = sorted(path.name for path in cfg.state_dir.rglob("*")) if cfg.state_dir.exists() else []
    refused = op_pseudo(cfg, PseudoRequest(locale="pl"))
    assert not refused.ok
    result = op_pseudo(cfg, PseudoRequest(locale="en-XA"))
    assert result.ok
    assert source.read_bytes() == before
    written = json.loads((tmp_path / "messages" / "en-XA" / "app.json").read_text(encoding="utf-8"))
    assert "{name}" in written["greet"]
    assert written["greet"].startswith("⟦")
    after = sorted(path.name for path in cfg.state_dir.rglob("*")) if cfg.state_dir.exists() else []
    assert after == state_before


def test_pseudo_xxxx_marker_locale(tmp_path, make_config) -> None:
    setup_project(tmp_path, {"greet": "Hello {name}"})
    cfg = make_config(tmp_path)
    result = op_pseudo(cfg, PseudoRequest(locale="en-XX"))
    assert result.ok
    assert result.data.get("style") == "xxxx"
    written = json.loads((tmp_path / "messages" / "en-XX" / "app.json").read_text(encoding="utf-8"))
    assert written["greet"] == "XXXXX {name}"
    assert len(written["greet"]) == len("Hello {name}")


def test_glossary_shell_is_filled() -> None:
    html = render_shell("glossary")
    assert "/static/glossary.js" in html
    assert "W-04 fills this page." not in html
    assert 'id="glossary-sub"' in html
    assert "page-head-glossary" in html
    assert 'id="glossary-head-actions"' in html


def test_glossary_payload_lists_active_locales(tmp_path, make_config) -> None:
    from llm_localizator.projects.glossary_edit import glossary_payload

    gloss = tmp_path / "glossary.json"
    write_json(gloss, {"doNotTranslate": [], "terms": {}})
    cfg = make_config(
        tmp_path,
        glossary_path=gloss,
        targets=["pl", "ar", "cs"],
        frozen=["cs"],
    )
    payload = glossary_payload(cfg)
    assert payload["ok"]
    assert payload["locales"] == ["pl", "ar", "cs"]
    assert payload["activeLocales"] == ["pl", "ar"]
    assert payload["frozenLocales"] == ["cs"]


def test_glossary_page_js_matches_design_contract() -> None:
    """Content structure from design/2 glossary.dc.html + locale column picker."""
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "llm_localizator" / "web" / "static" / "glossary.js"
    ).read_text(encoding="utf-8")
    assert "glossary-banner" in text
    assert "injected into every LLM translation prompt" in text
    assert "ll.glossary.visibleLocales." in text
    assert "visibleLocales" in text
    assert "activeLocales" in text
    assert "glossary-locale-picker" in text
    assert "glossary-locale-cell" in text
    assert "glossary-locale-note" in text
    assert "glossary-forbidden-tag" in text
    assert "notes:" in text or "notesMap" in text
    assert "Forbidden alternatives" not in text
    assert "glossary-modal" in text
    assert "glossary-modal-table" in text
    assert "Show all" in text
    assert "/api/ops/glossary-export" in text
    assert "/api/ops/glossary-import" in text
    assert "dry_run: true" in text
    assert "↓ Export CSV" in text
    assert "↑ Import CSV" in text
    assert "+ Add term" in text
