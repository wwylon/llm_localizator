"""plan_source_key must not treat an unreadable catalogue as empty (ADR-67)."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.ops.apply import plan_source_key


def _cat(tmp_path):
    return build_catalog("json-nested", tmp_path, "messages/{locale}/{namespace}.json", "en")


def test_new_namespace_file_plans_a_fresh_key(tmp_path):
    cat = _cat(tmp_path)
    plan = plan_source_key(cat, "en", "Save changes", "src/Button.tsx")
    assert plan["reuse"] is False and plan["key"]


def test_existing_identical_text_is_reused(tmp_path):
    (tmp_path / "messages" / "en").mkdir(parents=True)
    (tmp_path / "messages" / "en" / "app.json").write_text(
        json.dumps({"save": "Save"}), encoding="utf-8",
    )
    cat = _cat(tmp_path)
    plan = plan_source_key(
        cat, "en", "Save", "app.tsx", override="save", pending={},
    )
    assert plan["key"] == "save" and plan["reuse"] is True


def test_unreadable_catalogue_aborts_instead_of_planning_over_it(tmp_path):
    (tmp_path / "messages" / "en").mkdir(parents=True)
    (tmp_path / "messages" / "en" / "app.json").write_text("{not json", encoding="utf-8")
    cat = _cat(tmp_path)
    with pytest.raises(ValueError, match="not valid JSON"):
        plan_source_key(cat, "en", "Save", "app.tsx", override="save", pending={})
