"""Pins observable behaviour of run_translation before it is split (Wave 4).

These assert outcomes (catalogue, state, history, call counts), never internals,
so the refactor may move code freely as long as these stay green.
"""

from __future__ import annotations

import pytest

from llm_localizator.catalog import StateStore
from llm_localizator.catalog.history import HistoryStore
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import NullProvider

from ..conftest import setup_project, tagged


@pytest.fixture
def provider() -> NullProvider:
    return NullProvider(handler=tagged)


def _project(root, make_config, make_catalog, *, targets=("pl",), **overrides):
    setup_project(root, {"a": "Alpha", "b": "Beta", "c": "Gamma"})
    setup_project(root, {"x": "Xray"}, namespace="extra")
    cfg = make_config(root, targets=list(targets), **overrides)
    return cfg, make_catalog(cfg)


def test_multiple_namespaces_are_all_written(project_root, make_config, make_catalog, provider, silent) -> None:
    cfg, cat = _project(project_root, make_config, make_catalog)
    result = run_translation(cfg, cat, provider, report=silent)
    assert result.written == 4
    assert cat.load("pl", "app") == {"a": "[xx] Alpha", "b": "[xx] Beta", "c": "[xx] Gamma"}
    assert cat.load("pl", "extra") == {"x": "[xx] Xray"}


def test_every_written_key_has_state_and_history(project_root, make_config, make_catalog, provider, silent) -> None:
    cfg, cat = _project(project_root, make_config, make_catalog)
    run_translation(cfg, cat, provider, report=silent)
    state = StateStore(cfg.state_dir)
    hist = HistoryStore(cfg.history_root())
    for ns, key in [("app", "a"), ("app", "b"), ("app", "c"), ("extra", "x")]:
        assert state.entry("pl", ns, key) is not None
        assert hist.latest("pl", ns, key) is not None


def test_dry_run_writes_nothing_and_calls_nothing(project_root, make_config, make_catalog, provider, silent) -> None:
    cfg, cat = _project(project_root, make_config, make_catalog)
    result = run_translation(cfg, cat, provider, dry_run=True, report=silent)
    assert result.dry_run is True and result.written == 0
    assert provider.call_count == 0
    assert cat.load("pl", "app") == {}


def test_two_locales_each_get_their_own_output(project_root, make_config, make_catalog, provider, silent) -> None:
    cfg, cat = _project(project_root, make_config, make_catalog, targets=("pl", "de"))
    result = run_translation(cfg, cat, provider, report=silent)
    assert result.written == 8
    assert set(cat.load("de", "app")) == {"a", "b", "c"}


def test_batch_size_does_not_change_the_result(project_root, make_config, make_catalog, silent) -> None:
    outputs = []
    for size in (1, 2, 50):
        root = project_root / f"b{size}"
        root.mkdir()
        cfg, cat = _project(root, make_config, make_catalog)
        run_translation(cfg, cat, NullProvider(handler=tagged), batch_size=size, report=silent)
        outputs.append((cat.load("pl", "app"), cat.load("pl", "extra")))
    assert outputs[0] == outputs[1] == outputs[2]


def test_changed_source_is_retranslated_only_for_that_key(project_root, make_config, make_catalog, provider, silent) -> None:
    cfg, cat = _project(project_root, make_config, make_catalog)
    run_translation(cfg, cat, provider, report=silent)
    setup_project(project_root, {"a": "Alpha", "b": "Beta CHANGED", "c": "Gamma"})
    before = provider.call_count
    result = run_translation(cfg, cat, provider, report=silent)
    assert result.written == 1
    assert provider.call_count > before
    assert cat.load("pl", "app")["b"] == "[xx] Beta CHANGED"
    assert cat.load("pl", "app")["a"] == "[xx] Alpha"


def test_provider_failure_does_not_corrupt_existing_translations(project_root, make_config, make_catalog, silent) -> None:
    cfg, cat = _project(project_root, make_config, make_catalog)
    run_translation(cfg, cat, NullProvider(handler=tagged), report=silent)
    setup_project(project_root, {"a": "Alpha", "b": "Beta2", "c": "Gamma"})

    def boom(request):
        raise RuntimeError("provider down")

    try:
        run_translation(cfg, cat, NullProvider(handler=boom), report=silent)
    except Exception:
        pass
    after = cat.load("pl", "app")
    assert after["a"] == "[xx] Alpha" and after["c"] == "[xx] Gamma"
