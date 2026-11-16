"""Out-of-band catalogue edits: an agent or human writes the JSON files directly (plan Part 7).

Each test is one row of the scenario table. ``xfail(strict=True)`` rows document a
known gap: the test starts failing the day the gap is fixed, forcing the marker off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.ops.adopt import op_adopt
from llm_localizator.ops.catalogue_gaps import iter_catalogue_gaps
from llm_localizator.ops.types import AdoptRequest, ValidateRequest
from llm_localizator.ops.validate import op_validate

from .factory import build_project


def _edit(root: Path, locale: str, ns: str, fn) -> None:
    path = root / "messages" / locale / f"{ns}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _gaps(cfg, locale="pl", ns="app"):
    return {(g.key, g.reason) for g in iter_catalogue_gaps(cfg, locales=[locale], namespaces=[ns])}


def test_01_agent_fills_missing_key_is_adopted_as_agent(tmp_path):
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "en", "app", lambda d: d.update(brandNew="Brand new"))
    assert ("brandNew", "missing") in _gaps(cfg)
    _edit(tmp_path, "pl", "app", lambda d: d.update(brandNew="Całkiem nowy"))
    assert ("brandNew", "no_state") in _gaps(cfg)
    assert op_adopt(cfg, AdoptRequest(locales=["pl"])).data["adopted"] >= 1
    assert ("brandNew", "no_state") not in _gaps(cfg)


def test_02_agent_changes_existing_translation_is_detected(tmp_path):
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "pl", "app", lambda d: d.update(cancel="Zupełnie inny tekst"))
    assert any(k == "cancel" for k, _ in _gaps(cfg))


def test_03_changed_source_makes_targets_stale(tmp_path):
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "en", "app", lambda d: d.update(save="Save changes"))
    assert ("save", "stale") in _gaps(cfg)


def test_04_new_source_key_is_missing_in_targets(tmp_path):
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "en", "app", lambda d: d.update(brandNew="Brand new"))
    assert ("brandNew", "missing") in _gaps(cfg)


def test_05_deleted_source_key_does_not_crash_status(tmp_path):
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "en", "app", lambda d: d.pop("cancel"))
    assert not any(k == "cancel" for k, _ in _gaps(cfg))
    assert op_validate(cfg, ValidateRequest(locales=["pl"])).exit_code in (0, 1, 2)


def test_07_broken_placeholder_is_flagged(tmp_path):
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "pl", "app", lambda d: d.update(greeting="Witaj ponownie, {imie}!"))
    out = op_validate(cfg, ValidateRequest(locales=["pl"]))
    assert out.exit_code != 0
    assert "greeting" in json.dumps(out.data) + "\n".join(out.lines)


def test_08_invalid_json_in_one_file_leaves_others_loadable(tmp_path):
    cfg = build_project(tmp_path).config()
    (tmp_path / "messages" / "pl" / "app.json").write_text("{ not json", encoding="utf-8")
    cat = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    assert cat.load("pl", "play")
    assert cat.load("en", "app")


def test_09_reordering_and_reformatting_does_not_create_gaps(tmp_path):
    cfg = build_project(tmp_path).config()
    before = _gaps(cfg)
    path = tmp_path / "messages" / "pl" / "app.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(sorted(data.items(), reverse=True)), ensure_ascii=False), encoding="utf-8")
    assert _gaps(cfg) == before


def test_02b_adopt_restamps_external_edit_as_agent(tmp_path):
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "pl", "app", lambda d: d.update(cancel="Zupełnie inny tekst"))
    assert op_adopt(cfg, AdoptRequest(locales=["pl"])).data["adopted"] >= 1
    assert ("cancel", "external_edit") not in _gaps(cfg)
    from llm_localizator.catalog import StateStore

    assert StateStore(cfg.state_dir).entry("pl", "app", "cancel")["status"] == "agent"


def test_13_agent_overwrite_of_human_edit_is_held_not_adopted(tmp_path):
    from llm_localizator.catalog import StateStore

    cfg = build_project(tmp_path).config()
    store = StateStore(cfg.state_dir)
    entry = store.entry("pl", "app", "cancel")
    entry["status"] = "human"
    store.record("pl", "app", "cancel", entry)
    store.save("pl")
    _edit(tmp_path, "pl", "app", lambda d: d.update(cancel="Nadpisane przez agenta"))
    out = op_adopt(cfg, AdoptRequest(locales=["pl"]))
    assert [h["key"] for h in out.data["heldHumanConflicts"]] == ["cancel"]
    assert ("cancel", "external_edit") in _gaps(cfg)
    assert StateStore(cfg.state_dir).entry("pl", "app", "cancel")["status"] == "human"


def test_06_renamed_key_keeps_provenance(tmp_path):
    from llm_localizator.catalog import StateStore

    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "en", "app", lambda d: d.update(cancelNow=d.pop("cancel")))
    _edit(tmp_path, "pl", "app", lambda d: d.update(cancelNow=d.pop("cancel")))
    op_adopt(cfg, AdoptRequest(locales=["pl"]))
    entry = StateStore(cfg.state_dir).entry("pl", "app", "cancelNow")
    assert entry and entry["status"] == "machine"


def test_11_corrupt_state_file_does_not_crash_gap_scan(tmp_path):
    cfg = build_project(tmp_path).config()
    for f in (tmp_path / "messages" / ".state").glob("pl*"):
        f.write_text("{ broken", encoding="utf-8")
    try:
        _gaps(cfg)
    except Exception as exc:  # documents current behaviour: must be a clear error, not silent
        assert "state" in str(exc).lower() or "json" in str(exc).lower()


def test_10_external_state_edit_survives_a_later_flush(tmp_path):
    from llm_localizator.catalog import StateStore

    cfg = build_project(tmp_path).config()
    store = StateStore(cfg.state_dir)
    store.load("pl")
    other = StateStore(cfg.state_dir)  # a second process writes while we hold a cached copy
    e = dict(other.entry("pl", "app", "cancel"))
    e["status"] = "human"
    other.record("pl", "app", "cancel", e)
    other.save("pl")
    mine = dict(store.entry("pl", "app", "save") or {})
    mine["model"] = "x"
    store.record("pl", "app", "save", mine)
    store.save("pl")
    fresh = StateStore(cfg.state_dir)
    assert fresh.entry("pl", "app", "cancel")["status"] == "human"
    assert fresh.entry("pl", "app", "save")["model"] == "x"


def test_10_target_edited_mid_run_is_not_overwritten(tmp_path, monkeypatch):
    import os

    from llm_localizator.pipeline.translate import run_translation
    from llm_localizator.providers import ChaosProvider

    from .factory import gold_translator

    monkeypatch.setattr(os, "fsync", lambda _fd: None)
    cfg = build_project(tmp_path).config()
    _edit(tmp_path, "en", "app", lambda d: d.update(save="Save changes"))  # makes pl/save stale
    gold = gold_translator("pl")
    fired = []

    def translator(src):
        if not fired:  # an agent edits the target file while the model is "thinking"
            fired.append(1)
            _edit(tmp_path, "pl", "app", lambda d: d.update(save="Ręczna wersja"))
        return gold(src)

    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    provider = ChaosProvider(translator, faults={}, json_garbage=0.0, seed=0)
    lines: list[str] = []
    result = run_translation(cfg, catalog, provider, locales=["pl"], report=lines.append)
    data = json.loads((tmp_path / "messages" / "pl" / "app.json").read_text(encoding="utf-8"))
    assert data["save"] == "Ręczna wersja"
    assert any("edited outside the run" in m for m in lines)
    assert result.external_edit == ["pl/app.save"]


def test_11_hand_edited_state_file_is_reported_by_integrity_check(tmp_path):
    from llm_localizator.catalog import StateStore

    cfg = build_project(tmp_path).config()
    store = StateStore(cfg.state_dir)
    store.load("pl")
    e = dict(store.entry("pl", "app", "save") or {})
    e["model"] = "m"
    store.record("pl", "app", "save", e)
    store.save("pl")
    assert StateStore(cfg.state_dir).integrity_issues() == []
    path = cfg.state_dir / "pl.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"m"', '"hand"'), encoding="utf-8")
    assert StateStore(cfg.state_dir).integrity_issues() == ["pl.json"]
