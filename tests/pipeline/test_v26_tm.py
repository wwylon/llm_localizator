"""V26 TM conflict advisory in validate (R-06)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.pipeline.validate import run_validation
from llm_localizator.projects.config import ProjectConfig, ProviderConfig

from ..conftest import write_json


def test_v26_when_live_text_differs_from_high_score_tm(
    project_root: Path, make_catalog,
) -> None:
    write_json(project_root / "messages" / "en" / "app.json", {"a": "Hello friend"})
    write_json(project_root / "messages" / "pl" / "app.json", {"a": "WRONG"})
    cfg = ProjectConfig(
        root=project_root,
        name="v26",
        catalog_path="messages/{locale}/{namespace}.json",
        targets=["pl"],
        provider=ProviderConfig(kind="null"),
        state_dir=project_root / ".state",
        tm_dir=project_root / ".llm-tm",
    )
    tm = TranslationMemory(cfg.tm_root())
    tm.record(
        locale="pl",
        source="Hello friend",
        text="Witaj przyjacielu",
        model="prior",
        quality_score=0.95,
    )
    report = run_validation(cfg, make_catalog(cfg), locales=["pl"])
    v26 = [f for f in report.findings if f.check == "V26"]
    assert len(v26) == 1
    assert v26[0].key == "a"


def test_no_v26_when_live_matches_tm(project_root: Path, make_catalog) -> None:
    write_json(project_root / "messages" / "en" / "app.json", {"a": "Hello friend"})
    write_json(
        project_root / "messages" / "pl" / "app.json",
        {"a": "Witaj przyjacielu"},
    )
    cfg = ProjectConfig(
        root=project_root,
        name="v26ok",
        catalog_path="messages/{locale}/{namespace}.json",
        targets=["pl"],
        provider=ProviderConfig(kind="null"),
        state_dir=project_root / ".state",
        tm_dir=project_root / ".llm-tm",
    )
    TranslationMemory(cfg.tm_root()).record(
        locale="pl",
        source="Hello friend",
        text="Witaj przyjacielu",
        model="prior",
        quality_score=0.95,
    )
    report = run_validation(cfg, make_catalog(cfg), locales=["pl"])
    assert not any(f.check == "V26" for f in report.findings)
