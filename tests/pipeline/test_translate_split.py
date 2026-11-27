"""Phase 3 split of run_translation: behaviour pins for the extracted helpers."""

from __future__ import annotations

from llm_localizator.pipeline import translate as tr

from ..conftest import setup_project


def test_dry_run_builds_no_provider(project_root, make_config, make_catalog, silent, monkeypatch) -> None:
    setup_project(project_root, {"a": "Hello", "b": "World"})
    cfg = make_config(project_root)

    def boom(*_a, **_k):
        raise AssertionError("dry run must not build a provider")

    monkeypatch.setattr(tr, "provider_for_locale", boom)
    result = tr.run_translation(cfg, make_catalog(cfg), None, dry_run=True, report=silent)
    assert result.dry_run and result.total == 2


def test_min_keys_floor_skips_small_locales(make_config, project_root, silent) -> None:
    cfg = make_config(project_root, translate_min_keys=3)
    items = [tr.WorkItem(namespace="app", locale="pl", key=k, source=k) for k in "ab"]
    kept, skipped = tr._apply_min_keys_floor(
        cfg, items, force=False, flagged=False, ignore_min_keys=False, report=silent,
    )
    assert kept == [] and skipped
