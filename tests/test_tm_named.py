"""Several read-only shared TMs and one write target (C-030, ADR-95)."""

from __future__ import annotations

from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.projects.config import load_config
from llm_localizator.web.project_config import project_config_view, save_project_config

from tests.test_w07 import _toml


def test_earlier_shared_memory_wins_and_all_are_searched(tmp_path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    TranslationMemory(a).record(locale="pl", source="Hello", text="Czesc A", model="m")
    TranslationMemory(b).record(locale="pl", source="Hello", text="Czesc B", model="m")
    TranslationMemory(b).record(locale="pl", source="Goodbye", text="Pa", model="m")
    tm = TranslationMemory(tmp_path / "own", shared=[a, b])
    assert tm.exact("pl", "Hello").text == "Czesc A"
    assert tm.exact("pl", "Goodbye").text == "Pa"
    assert tm.exact("pl", "Nothing") is None
    near = tm.near("pl", "Hello there", min_overlap=0.2)
    assert {e.text for e, _ in near} >= {"Czesc A"}
    assert not (a / "x").exists()


def test_single_path_shared_still_works(tmp_path) -> None:
    a = tmp_path / "a"
    TranslationMemory(a).record(locale="pl", source="Hello", text="Czesc", model="m")
    assert TranslationMemory(tmp_path / "own", shared=a).exact("pl", "Hello").text == "Czesc"


def test_approve_also_writes_to_the_write_target_only(tmp_path) -> None:
    shared, target = tmp_path / "shared", tmp_path / "client"
    TranslationMemory(shared).record(locale="pl", source="x", text="y", model="m")
    before = (shared / "pl.jsonl").read_text(encoding="utf-8")
    tm = TranslationMemory(tmp_path / "own", shared=[shared], write_to=target)
    tm.approve(locale="pl", source="Save", text="Zapisz")
    assert TranslationMemory(target).exact("pl", "Save").verified
    assert TranslationMemory(tmp_path / "own").exact("pl", "Save").text == "Zapisz"
    assert (shared / "pl.jsonl").read_text(encoding="utf-8") == before
    tm.record(locale="pl", source="Raw", text="Surowy", model="m")
    assert TranslationMemory(target).exact("pl", "Raw") is None


def test_config_roundtrip_with_several_shared_and_a_write_target(tmp_path) -> None:
    path = _toml(tmp_path)
    cfg = load_config(path)
    result = save_project_config(cfg, tm_shared="tms/common, tms/clientA", tm_write="tms/clientA")
    assert result["ok"] is True
    loaded = load_config(path)
    assert [p.name for p in loaded.tm_shared_all()] == ["common", "clientA"]
    assert loaded.tm_write.name == "clientA"
    view = project_config_view(loaded)
    assert view["tmShared"] == "tms/common, tms/clientA" and view["tmWrite"] == "tms/clientA"
    assert loaded.open_tm().write_to == loaded.tm_write
