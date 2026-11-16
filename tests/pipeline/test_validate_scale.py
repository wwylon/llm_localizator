"""Scale guards and glossary caching for validate."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog.import_formats import import_csv
from llm_localizator.pipeline.validate import (
    SEMANTIC_FULL_CATALOG_MAX_KEYS,
    run_validation,
)
from llm_localizator.projects.context import GlossaryCache
from llm_localizator.web.translator import by_target_index, resolve_text

from ..conftest import write_json
from ..pipeline.test_translate import setup_project

CONFIG = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]

[state]
dir = "messages/.state"
"""


@pytest.fixture
def app(tmp_path: Path):
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {
        "greet": "Hello {name}",
    })
    write_json(tmp_path / "messages" / "pl" / "app.json", {
        "greet": "Witaj {name}",
    })
    from llm_localizator.projects import load_config
    from llm_localizator.web import build_state
    return build_state(load_config(tmp_path / ".llm-localize.toml"))


def test_glossary_cache_dedupes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    def _track(path, *, domains=None, shared=None):
        calls.append((path, domains, shared))
        return {"terms": {}, "doNotTranslate": []}

    monkeypatch.setattr(
        "llm_localizator.projects.context.effective_glossary_for", _track,
    )
    cache = GlossaryCache(tmp_path / "glossary.json")
    cache.get(["games"])
    cache.get(["games"])
    cache.get(["billing"])
    assert len(calls) == 2


def test_semantic_refused_on_full_large_catalog(
    project_root, make_config, make_catalog, monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = {f"k{i}": f"v{i}" for i in range(SEMANTIC_FULL_CATALOG_MAX_KEYS + 1)}
    setup_project(project_root, keys, existing={})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    report = run_validation(cfg, catalog, check_semantic=True)
    assert report.scope_error
    assert "semantic validation refused" in report.scope_error


def test_semantic_allowed_when_namespace_scoped(
    project_root, make_config, make_catalog, monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = {f"k{i}": f"v{i}" for i in range(SEMANTIC_FULL_CATALOG_MAX_KEYS + 1)}
    setup_project(project_root, keys, existing={})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    report = run_validation(
        cfg, catalog, namespace="app", check_semantic=True,
    )
    assert report.scope_error is None


def test_import_csv_batches_namespace_save(
    project_root, make_config, make_catalog,
) -> None:
    setup_project(
        project_root,
        {"a": "A", "b": "B", "c": "C"},
        existing={"a": "a", "b": "b", "c": "c"},
    )
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    saves: list[tuple[str, str]] = []
    orig_save = catalog.save

    def _counting_save(locale, ns, messages):
        saves.append((locale, ns))
        return orig_save(locale, ns, messages)

    catalog.save = _counting_save  # type: ignore[method-assign]
    csv_text = (
        "namespace,key,source,pl\n"
        "app,a,A,AA\n"
        "app,b,B,BB\n"
        "app,c,C,CC\n"
    )
    result = import_csv(cfg, catalog, csv_text, locales=["pl"])
    assert result["accepted"] == 3
    assert saves == [("pl", "app")]


def test_by_target_index_cached(app) -> None:
    idx1 = by_target_index(app, "pl")
    idx2 = by_target_index(app, "pl")
    assert idx1 is idx2
    hits = resolve_text(app, "pl", "Witaj {name}")["candidates"]
    assert hits and hits[0]["key"] == "greet"
