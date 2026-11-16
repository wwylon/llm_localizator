"""Fidelity round-trips: go-i18n extra fields/order, android plural prefix/suffix."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.catalog import build_catalog


def _go(tmp: Path):
    return build_catalog("go-i18n", tmp, "{locale}/{namespace}.json", "en")


def _android(tmp: Path):
    return build_catalog("android-xml", tmp, "values-{locale}/{namespace}.xml", "en")


GO_RAW = [
    {"id": "zeta", "description": "last alpha", "hash": "sha1-1", "translation": "Zeta {{.N}}"},
    {"id": "alpha", "translation": "Alpha"},
    {
        "id": "items",
        "description": "count of items",
        "hash": "sha1-2",
        "translation": {"one": "One item", "other": "{{.Count}} items"},
    },
    {"id": "flat", "description": "top-level plurals", "one": "One", "other": "Many", "hash": "h"},
    {"id": "mid", "translation": "Mid"},
]


def _write_go(tmp: Path) -> Path:
    p = tmp / "en" / "app.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(GO_RAW, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def test_go_i18n_unchanged_save_preserves_everything(tmp_path: Path) -> None:
    p = _write_go(tmp_path)
    cat = _go(tmp_path)
    cat.save("en", "app", cat.load("en", "app"))
    assert json.loads(p.read_text(encoding="utf-8")) == GO_RAW
    before = p.read_bytes()
    cat.save("en", "app", cat.load("en", "app"))
    assert p.read_bytes() == before


def test_go_i18n_changed_value_keeps_extra_fields_and_order(tmp_path: Path) -> None:
    p = _write_go(tmp_path)
    cat = _go(tmp_path)
    msgs = cat.load("en", "app")
    msgs["zeta"] = "Nowa zeta"
    msgs["flat"] = json.dumps({"one": "Jeden", "other": "Wiele"})
    msgs["brand_new"] = "New"
    cat.save("en", "app", msgs)
    out = json.loads(p.read_text(encoding="utf-8"))
    assert [e["id"] for e in out] == ["zeta", "alpha", "items", "flat", "mid", "brand_new"]
    by = {e["id"]: e for e in out}
    assert by["zeta"] == {**GO_RAW[0], "translation": "Nowa zeta"}
    assert by["items"] == GO_RAW[2]
    assert by["flat"]["description"] == "top-level plurals"
    assert by["flat"]["one"] == "Jeden" and by["flat"]["other"] == "Wiele"
    assert cat.load("en", "app") == msgs
    before = p.read_bytes()
    cat.save("en", "app", cat.load("en", "app"))
    assert p.read_bytes() == before


def test_go_i18n_replacing_plural_translation_keeps_description(tmp_path: Path) -> None:
    p = _write_go(tmp_path)
    cat = _go(tmp_path)
    msgs = cat.load("en", "app")
    msgs["items"] = json.dumps({"one": "Jedna", "few": "Kilka", "other": "Wiele"})
    cat.save("en", "app", msgs)
    e = next(x for x in json.loads(p.read_text(encoding="utf-8")) if x["id"] == "items")
    assert e["description"] == "count of items" and e["hash"] == "sha1-2"
    assert e["translation"] == {"one": "Jedna", "few": "Kilka", "other": "Wiele"}


def test_go_i18n_fresh_file_still_sorted(tmp_path: Path) -> None:
    cat = _go(tmp_path)
    cat.save("en", "app", {"b": "B", "a": "A"})
    out = json.loads(cat.path_for("en", "app").read_text(encoding="utf-8"))
    assert [e["id"] for e in out] == ["a", "b"]


ICU = "You have {count, plural, one {# item} other {# items}} left"


def test_android_plural_prefix_suffix_roundtrip(tmp_path: Path) -> None:
    cat = _android(tmp_path)
    msgs = {"plain": "It's fine", "left": ICU}
    cat.save("en", "app", msgs)
    assert cat.load("en", "app") == msgs
    p = cat.path_for("en", "app")
    before = p.read_bytes()
    cat.save("en", "app", cat.load("en", "app"))
    assert p.read_bytes() == before
    assert cat.load("en", "app") == msgs


def test_android_plural_prefix_suffix_with_exact_branch(tmp_path: Path) -> None:
    cat = _android(tmp_path)
    msg = "-- {n, plural, =0 {none} one {# x} other {# xs}} -- <b>&"
    cat.save("en", "app", {"k": msg})
    assert cat.load("en", "app") == {"k": msg}
    p = cat.path_for("en", "app")
    before = p.read_bytes()
    cat.save("en", "app", cat.load("en", "app"))
    assert p.read_bytes() == before


def test_android_bare_plural_has_no_extra_marker(tmp_path: Path) -> None:
    cat = _android(tmp_path)
    cat.save("en", "app", {"k": "{n, plural, one {# a} other {# b}}"})
    assert "llm-localizator" not in cat.path_for("en", "app").read_text(encoding="utf-8")
