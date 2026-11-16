"""glossary-learn and import-review (A6, ADR-135)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from llm_localizator.catalog.history import HistoryEvent, HistoryStore
from llm_localizator.ops.glossary_learn import learn_corrections, op_glossary_learn
from llm_localizator.ops.import_review import decision_text, op_import_review

SOURCE = {
    "a.seed": "Random seed",
    "b.seed": "Seed for this run",
    "c.title": "Settings",
}


def test_learn_needs_the_same_swap_in_two_keys() -> None:
    events = [
        ("a.seed", "Losowe nasienie", "Losowe ziarno", "Random seed"),
        ("b.seed", "Nasienie dla tego biegu", "Ziarno dla tego biegu", "Seed for this run"),
        ("c.title", "Ustawienia", "Ustawienia aplikacji", "Settings"),
    ]
    (p,) = learn_corrections(events)
    assert p["term"] == "seed" and p["approved"] == "ziarno" and p["forbidden"] == ["nasienie"]
    assert p["keys"] == ["a.seed", "b.seed"]
    assert learn_corrections(events[:1]) == []


def test_history_event_with_an_empty_namespace_is_read(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    store.append("pl", HistoryEvent(ts="t", namespace="", key="a.seed", prev="x", next="y",
                                    model="human", status="human", src_sha="s", trigger="set"))
    assert [sk for sk, _e, _r in store.iter_events("pl")] == ["a.seed"]


@pytest.fixture
def consumer(tmp_path: Path, make_config):
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    (tmp_path / "locales" / "pl.json").write_text(json.dumps(
        {"a.seed": "Losowe nasienie", "b.seed": "Nasienie dla tego biegu", "c.title": "Ustawienia"},
        ensure_ascii=False), encoding="utf-8")
    return make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                       targets=["pl"], state_dir=tmp_path / ".state")


def _sheet(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["key", "source", "current", "suggestion", "risk", "score",
                                           "reasons", "decision"])
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in w.fieldnames})
    return path


def test_decision_values() -> None:
    assert decision_text({"decision": "keep"}) is None
    assert decision_text({"decision": ""}) is None
    assert decision_text({"decision": "suggestion", "suggestion": "Ziarno"}) == "Ziarno"
    assert decision_text({"decision": "Moje"}) == "Moje"


def test_import_review_then_learn(consumer, tmp_path: Path) -> None:
    sheet = _sheet(tmp_path / "review.csv", [
        {"key": "a.seed", "current": "Losowe nasienie", "suggestion": "Losowe ziarno",
         "decision": "suggestion"},
        {"key": "b.seed", "current": "Nasienie dla tego biegu", "decision": "Ziarno dla tego biegu"},
        {"key": "c.title", "current": "Ustawienia", "decision": "keep"},
    ])
    dry = op_import_review(consumer, locale="pl", path=sheet, dry_run=True)
    assert dry.ok and dry.data["written"] == ["a.seed", "b.seed"]
    assert "nasienie" in (consumer.root / "locales" / "pl.json").read_text(encoding="utf-8")
    done = op_import_review(consumer, locale="pl", path=sheet)
    assert done.ok, done.lines
    pl = json.loads((consumer.root / "locales" / "pl.json").read_text(encoding="utf-8"))
    assert pl["a.seed"] == "Losowe ziarno" and pl["c.title"] == "Ustawienia"
    learned = op_glossary_learn(consumer, locale="pl", write=True)
    (p,) = learned.data["proposals"]
    assert (p["term"], p["approved"], p["forbidden"]) == ("seed", "ziarno", ["nasienie"])
    assert Path(learned.data["path"]).is_file()


def test_import_review_rejects_a_non_review_csv(consumer, tmp_path: Path) -> None:
    bad = tmp_path / "x.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    assert op_import_review(consumer, locale="pl", path=bad).exit_code == 2
