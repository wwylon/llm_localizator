"""Content tiers (ADR-52): human keys are held, review keys are ticketed, auto is unchanged."""

from __future__ import annotations

import pytest

from llm_localizator.catalog import StateStore
from llm_localizator.catalog.review_queue import ReviewQueue
from llm_localizator.pipeline.tiers import tier_for
from llm_localizator.pipeline.translate import collect_work, run_translation
from llm_localizator.projects import ConfigError
from llm_localizator.projects.config import _content_tiers
from llm_localizator.projects.context import ContextNotes
from llm_localizator.providers import NullProvider

from ..conftest import write_json
from .test_translate import setup_project, tagged


def _cfg(project_root, make_config, tiers):
    setup_project(project_root, {"terms": "Terms of service", "hello": "Hello"}, namespace="legal")
    setup_project(project_root, {"tagline": "Fast and friendly", "save": "Save"}, namespace="app")
    return make_config(
        project_root, context_dir=project_root / "context", quality_tiers=tiers,
    )


def test_tier_resolution_order(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config, {"legal": "human", "app.tagline": "review", "*": "auto"})
    write_json(project_root / "context" / "app.json", {"save": {"tier": "human"}})
    notes = ContextNotes(cfg.context_dir)
    assert tier_for(cfg, notes, "legal", "terms") == "human"
    assert tier_for(cfg, notes, "app", "tagline") == "review"
    assert tier_for(cfg, notes, "app", "other") == "auto"
    assert tier_for(cfg, notes, "app", "save") == "human"  # per-key override beats the globs


def test_recursive_glob_matches_the_namespace_and_its_children(project_root, make_config) -> None:
    cfg = make_config(project_root, quality_tiers={"legal/**": "human"})
    notes = ContextNotes(None)
    assert tier_for(cfg, notes, "legal", "x") == "human"
    assert tier_for(cfg, notes, "legal/privacy", "x") == "human"
    assert tier_for(cfg, notes, "legalese", "x") == "auto"


def test_human_keys_are_held_not_translated_and_ticketed_once(
    project_root, make_config, make_catalog, silent,
) -> None:
    cfg = _cfg(project_root, make_config, {"legal": "human"})
    catalog = make_catalog(cfg)
    held: list = []
    work = collect_work(
        cfg, catalog, StateStore(cfg.state_root()), locales=["pl"],
        namespaces=["app", "legal"], held=held,
    )
    assert {i.namespace for i in work} == {"app"}
    assert {i.key for i in held} == {"terms", "hello"}

    for _ in range(2):
        run_translation(cfg, make_catalog(cfg), NullProvider(handler=tagged), report=silent)
    tickets = ReviewQueue(cfg.review_root()).open_tickets("pl")
    assert sorted(t.key for t in tickets if t.reason == "tier:human") == ["hello", "terms"]
    assert "legal" not in make_catalog(cfg).load("pl", "legal") or not make_catalog(cfg).load("pl", "legal")


def test_review_keys_are_translated_and_ticketed(
    project_root, make_config, make_catalog, silent,
) -> None:
    cfg = _cfg(project_root, make_config, {"app.tagline": "review"})
    result = run_translation(cfg, make_catalog(cfg), NullProvider(handler=tagged), report=silent)
    assert result.written >= 2
    assert make_catalog(cfg).load("pl", "app")["tagline"].startswith("[xx]")
    tickets = ReviewQueue(cfg.review_root()).open_tickets("pl")
    assert [(t.key, t.reason) for t in tickets] == [("tagline", "tier:review")]


def test_dry_run_creates_no_tickets(project_root, make_config, make_catalog, silent) -> None:
    cfg = _cfg(project_root, make_config, {"legal": "human", "app.tagline": "review"})
    run_translation(cfg, make_catalog(cfg), NullProvider(handler=tagged), dry_run=True, report=silent)
    assert ReviewQueue(cfg.review_root()).open_tickets("pl") == []


def test_a_bad_tier_value_is_rejected() -> None:
    with pytest.raises(ConfigError):
        _content_tiers({"legal": "manual"}, "cfg.toml")
    assert _content_tiers({"legal/**": "human"}, "cfg.toml") == {"legal/**": "human"}
