"""``merge_for_write`` -- the load-bearing rebuild rules.

These four behaviours are what keep every locale structurally aligned with the
source. They were an undocumented implementation detail of bridge's
``flush_changes``; here they are a tested contract.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from llm_localizator.catalog import JsonNestedCatalog

TEMPLATE = "messages/{locale}/{namespace}.json"


def catalog(root: Path) -> JsonNestedCatalog:
    return JsonNestedCatalog(root, TEMPLATE, "en")


def test_fresh_translation_wins(tmp_path: Path) -> None:
    c = catalog(tmp_path)
    merged = c.merge_for_write({"a": "A"}, {"a": "old"}, {"a": "new"})
    assert merged == {"a": "new"}


def test_existing_translation_is_preserved(tmp_path: Path) -> None:
    c = catalog(tmp_path)
    merged = c.merge_for_write({"a": "A", "b": "B"}, {"a": "kept"}, {"b": "fresh"})
    assert merged == {"a": "kept", "b": "fresh"}


def test_untranslated_key_falls_back_to_source(tmp_path: Path) -> None:
    """A missing translation renders the source rather than an empty string."""
    c = catalog(tmp_path)
    merged = c.merge_for_write({"a": "A", "b": "B"}, {}, {})
    assert merged == {"a": "A", "b": "B"}


def test_orphan_key_absent_from_source_is_dropped(tmp_path: Path) -> None:
    """This is how deleting an English string prunes every locale."""
    c = catalog(tmp_path)
    merged = c.merge_for_write({"a": "A"}, {"a": "kept", "gone": "obsolete"}, {})
    assert merged == {"a": "kept"}
    assert "gone" not in merged


def test_key_set_always_equals_source_key_set(tmp_path: Path) -> None:
    c = catalog(tmp_path)
    source = {"a": "A", "b": "B", "c": "C"}
    merged = c.merge_for_write(source, {"a": "x", "zz": "orphan"}, {"c": "y"})
    assert set(merged) == set(source)


def test_round_trip_through_disk_preserves_nesting(tmp_path: Path) -> None:
    c = catalog(tmp_path)
    flat = {"tactics.claim": "Claim", "tactics.concede": "Concede", "top": "Top"}
    c.save("pl", "play", flat)
    assert c.load("pl", "play") == flat

    raw = (tmp_path / "messages" / "pl" / "play.json").read_text(encoding="utf-8")
    assert '"tactics"' in raw, "nested shape must be restored on disk, not flattened"


def test_missing_file_loads_as_empty(tmp_path: Path) -> None:
    assert catalog(tmp_path).load("pl", "nope") == {}


def test_namespaces_are_discovered_from_source_locale(tmp_path: Path) -> None:
    c = catalog(tmp_path)
    for ns in ("play", "auth", "nav"):
        c.save("en", ns, {"k": "v"})
    assert c.namespaces() == ["auth", "nav", "play"]


def test_namespace_walk_skips_vendor_and_cache_dirs(tmp_path: Path) -> None:
    c = catalog(tmp_path)
    c.save("en", "app", {"k": "v"})
    vendor = tmp_path / "messages" / "en" / "node_modules" / "pkg.json"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("{}\n", encoding="utf-8")
    cached = tmp_path / "messages" / "en" / "__pycache__" / "x.json"
    cached.parent.mkdir()
    cached.write_text("{}\n", encoding="utf-8")
    assert c.namespaces() == ["app"]


@pytest.mark.slow
def test_load_cache_keeps_at_most_256_paths(tmp_path: Path) -> None:
    c = catalog(tmp_path)
    for i in range(300):
        c.save("en", f"n{i}", {"k": str(i)})
        assert c.load("en", f"n{i}") == {"k": str(i)}
    assert len(c._cache) <= 256
    assert c.load("en", "n299") == {"k": "299"}
