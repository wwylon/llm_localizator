"""Translate with a provider that fails like small local models do (ChaosProvider).

Two promises: no hard-class defect ever reaches the catalogue, and the soft retry (ADR-57)
leaves fewer soft defects than running without it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import ChaosProvider

from .factory import build_project, gold_translator
from .scorecard import all_findings

@pytest.fixture(autouse=True)
def _no_fsync(monkeypatch):
    """Every flush fsyncs; on Windows that is ~0.5 s each and dominates this file's runtime."""
    import os

    monkeypatch.setattr(os, "fsync", lambda _fd: None)


HARD = {"V02", "V04", "V05", "V27", "V32", "V39"}
FAULTS = {
    "cjk_bleed": 0.10, "truncate": 0.10, "latin_leftover": 0.10, "drop_placeholder": 0.08,
    "echo_source": 0.08, "extra_prose": 0.08, "empty": 0.04,
}


def _run(root: Path, locale: str, seed: int, *, soft_retry: bool) -> dict:
    project = build_project(root, locales=[locale])
    shutil.rmtree(root / "messages" / locale)
    (root / "messages" / ".state" / f"{locale}.json").unlink()
    cfg = project.config()
    cfg.translate_soft_retry = soft_retry
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    provider = ChaosProvider(
        gold_translator(locale), faults=FAULTS, json_garbage=0.15, seed=seed,
    )
    run_translation(cfg, catalog, provider, locales=[locale], report=lambda _m: None)
    rows = [f for f in all_findings(project) if f.locale == locale]
    return {
        "hard": [f for f in rows if f.check in HARD or "unexpected script" in f.message],
        "soft": [f for f in rows if f.check in {"V21", "V33"} and "unexpected script" not in f.message],
        "injected": len(provider.injected),
    }


@pytest.mark.slow
@pytest.mark.parametrize("locale", ["ar", "pl"])
def test_no_hard_defect_reaches_the_catalogue(tmp_path, locale) -> None:
    for seed in range(4):
        out = _run(tmp_path / f"s{seed}", locale, seed, soft_retry=True)
        assert out["injected"] > 0
        assert out["hard"] == [], [(f.check, f.key, f.message) for f in out["hard"]]


@pytest.mark.slow
def test_soft_retry_leaves_fewer_soft_defects(tmp_path) -> None:
    on = off = 0
    for seed in range(6):
        on += len(_run(tmp_path / f"on{seed}", "ar", seed, soft_retry=True)["soft"])
        off += len(_run(tmp_path / f"off{seed}", "ar", seed, soft_retry=False)["soft"])
    assert off > 0, "the chaos run injected no soft defects"
    assert on < off, f"soft retry did not help: {on} with it, {off} without"
