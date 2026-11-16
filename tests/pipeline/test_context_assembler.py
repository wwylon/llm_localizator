"""LocalePolicy and ContextAssembler unit tests (audit A1)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.core.locale_policy import LocalePolicy
from llm_localizator.pipeline.context_assembler import (
    assemble_context,
    context_completeness,
    rank_tm_near,
)
from llm_localizator.pipeline.ensemble import risk_level
from llm_localizator.pipeline.gates import hard_gates_ok, scorer_version
from llm_localizator.pipeline.run_manifest import RunManifest, config_fingerprint
from llm_localizator.projects.config import ProjectConfig, ProviderConfig


def test_locale_policy_cjk() -> None:
    policy = LocalePolicy.for_locale("zh")
    assert policy.script == "cjk"
    assert policy.direction == "ltr"
    assert "CJK" in policy.script_rule()
    assert "Cyrillic" in policy.script_rule()


def test_locale_policy_arabic_rtl() -> None:
    policy = LocalePolicy.for_locale("ar")
    assert policy.script == "arabic"
    assert policy.direction == "rtl"
    assert "zero" in policy.plural_categories


def test_context_completeness_high_risk() -> None:
    missing = context_completeness(
        "Delete account", note="", screen=None, high_risk=True,
    )
    assert "missing_note" in missing
    assert "missing_screen" in missing


def test_rank_tm_near_prefers_verified(tmp_path: Path) -> None:
    tm = TranslationMemory(tmp_path)
    tm.record(
        locale="pl", source="Cancel now", text="Anuluj maszynowo",
        model="m", verified=False, quality_score=0.9,
    )
    tm.record(
        locale="pl", source="Cancel please", text="Anuluj",
        model="human", verified=True, quality_score=1.0,
    )
    hits = tm.near("pl", "Cancel", limit=5, min_overlap=0.1)
    ranked = rank_tm_near(hits, limit=2)
    assert ranked
    assert ranked[0][0].verified is True


def test_assemble_context_trace() -> None:
    pkg = assemble_context(
        source="Save",
        locale="pl",
        namespace="ui",
        key="save",
        context="toolbar button",
        screen="editor",
        file_examples=[("Cancel", "Anuluj")],
        high_risk=False,
    )
    assert pkg.examples
    assert any(i.kind == "example" for i in pkg.items)
    assert any(t.startswith("example:") for t in pkg.trace)


def test_run_manifest_writes(tmp_path: Path) -> None:
    m = RunManifest.start(
        command="translate",
        locales=["pl"],
        model="test",
        config_hash=config_fingerprint({"a": 1}),
    )
    m.bump("written", 3)
    path = m.write(tmp_path)
    assert path.exists()
    assert "written" in path.read_text(encoding="utf-8")


def test_hard_gates_and_scorer_version() -> None:
    ok, reason = hard_gates_ok("Hello", "Cześć", "pl", {})
    assert ok and reason is None
    bad, reason = hard_gates_ok("{n} items", "pozycje", "pl", {})
    assert not bad and reason
    assert scorer_version("lqs") == "lqs-1"
    assert scorer_version("bt") == "bt-1"


def test_risk_level_bands() -> None:
    cfg = ProjectConfig(
        root=Path("."),
        name="t",
        source_locale="en",
        catalog_format="json-nested",
        catalog_path="m/{locale}/{namespace}.json",
        targets=["pl"],
        models={"default": "m"},
        provider=ProviderConfig(kind="null"),
        domain="test",
    )
    assert risk_level("Delete account permanently", cfg) == "high"
    assert risk_level("OK", cfg) == "medium"
    assert risk_level("Welcome to the tournament lobby tonight", cfg) == "low"
