"""Flagged-mode translation.

Ported from bridge's ``test_i18n_flags.py``. The original mocked *both*
``call_ollama`` and ``call_ollama_batch`` with positional lambdas, because the
pipeline tries a batch first and falls back per key. Injecting a provider
removes that duplication and the signature-drift hazard (ADR-5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.catalog import StateStore
from llm_localizator.cli.cmd_translate import _flagged_keys
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import NullProvider

from ..conftest import write_json
from .test_translate import setup_project, tagged


def write_flags(path: Path, rows: list[dict | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def provider() -> NullProvider:
    return NullProvider(handler=tagged)


# ---- parsing ---------------------------------------------------------------

def test_no_flags_file_is_empty(project_root, make_config) -> None:
    cfg = make_config(project_root, flags_path=project_root / "nope.jsonl")
    assert _flagged_keys(cfg) == {}


def test_loads_valid_jsonl(project_root, make_config) -> None:
    path = project_root / "flags.jsonl"
    write_flags(path, [
        {"namespace": "app", "key": "greet", "locale": "pl"},
        {"namespace": "app", "key": "bye", "locale": "pl"},
        {"namespace": "nav", "key": "home", "locale": "ar"},
    ])
    cfg = make_config(project_root, flags_path=path)
    assert _flagged_keys(cfg) == {"pl": {"app.greet", "app.bye"}, "ar": {"nav.home"}}


def test_skips_blank_and_malformed_lines(project_root, make_config) -> None:
    path = project_root / "flags.jsonl"
    write_flags(path, [
        {"namespace": "app", "key": "greet", "locale": "pl"},
        "",
        "{not valid json",
        {"namespace": "app"},  # incomplete -- no key, no locale
    ])
    cfg = make_config(project_root, flags_path=path)
    assert _flagged_keys(cfg) == {"pl": {"app.greet"}}


# ---- end to end ------------------------------------------------------------

def test_only_flagged_key_is_retranslated(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"},
                  existing={"greet": "stare", "bye": "stare"})
    path = project_root / "flags.jsonl"
    write_flags(path, [{"namespace": "app", "key": "greet", "locale": "pl"}])
    cfg = make_config(project_root, flags_path=path)
    catalog = make_catalog(cfg)

    result = run_translation(
        cfg, catalog, provider, only_keys=_flagged_keys(cfg), report=silent,
    )

    assert result.written == 1
    data = catalog.load("pl", "app")
    assert data["greet"] == "[xx] Hello"
    assert data["bye"] == "stare", "unflagged key must be left alone"


def test_flagged_key_is_retranslated_even_when_state_is_current(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    """The whole point of flagging: the hash matches, but a human said it's wrong."""
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    run_translation(cfg, catalog, provider, report=silent)
    assert StateStore(cfg.state_dir).entry("pl", "app", "greet") is not None

    path = project_root / "flags.jsonl"
    write_flags(path, [{"namespace": "app", "key": "greet", "locale": "pl"}])
    cfg.flags_path = path

    result = run_translation(
        cfg, catalog, provider, only_keys=_flagged_keys(cfg), report=silent,
    )
    assert result.total == 1


def test_rejected_translation_is_not_written(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello {name}"}, existing={"greet": "Witaj {name}"})
    path = project_root / "flags.jsonl"
    write_flags(path, [{"namespace": "app", "key": "greet", "locale": "pl"}])
    cfg = make_config(project_root, flags_path=path)
    catalog = make_catalog(cfg)
    provider = NullProvider(handler=lambda r: json.dumps(["Witaj"]) if r.schema else "Witaj")

    result = run_translation(
        cfg, catalog, provider, only_keys=_flagged_keys(cfg), report=silent,
    )

    assert result.written == 0 and len(result.rejected) == 1
    assert catalog.load("pl", "app")["greet"] == "Witaj {name}"


def test_flags_for_another_locale_are_ignored(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    path = project_root / "flags.jsonl"
    write_flags(path, [{"namespace": "app", "key": "greet", "locale": "ar"}])
    cfg = make_config(project_root, targets=["pl"], flags_path=path)

    result = run_translation(
        cfg, make_catalog(cfg), provider, only_keys=_flagged_keys(cfg), report=silent,
    )
    assert result.total == 0


def test_flag_resolve_removes_identity(tmp_path: Path) -> None:
    from llm_localizator.catalog import FlagStore

    path = tmp_path / "flags.jsonl"
    store = FlagStore(path)
    assert store.append({"locale": "pl", "namespace": "app", "key": "greet", "reason": "x"})
    assert store.append({"locale": "pl", "namespace": "app", "key": "greet", "reason": "dup"}) is False
    assert "app.greet" in store.grouped()["pl"]
    assert store.resolve("pl", "app", "greet") is True
    assert store.grouped() == {}
    assert store.resolve("pl", "app", "greet") is False


def test_resolve_flushed_skips_flags_opened_this_run() -> None:
    from llm_localizator.catalog import FlagStore
    from llm_localizator.pipeline.translate import _resolve_flushed_flags

    store = FlagStore(None)
    # No path: resolve is a no-op; we still exercise the skip filter.
    _resolve_flushed_flags(
        store, None, [("pl", "app", "greet")],
        skip={("pl", "app", "greet")},
    )


def test_low_score_flag_survives_flush(
    project_root, make_config, make_catalog, silent,
) -> None:
    """A full sweep must not clear the low-score flag it just wrote (Wave 0.1)."""
    from llm_localizator.catalog import FlagStore
    from llm_localizator.providers import CompletionRequest

    source = "Hello dear friend from the application"
    write_json(project_root / "messages" / "en" / "app.json", {"greet": source})
    flags_path = project_root / "flags.jsonl"
    cfg = make_config(
        project_root,
        flags_path=flags_path,
        quality_thresholds={"pl": 0.99},
    )
    catalog = make_catalog(cfg)

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            if "JSON array" in request.prompt:
                return json.dumps(["Something unrelated entirely"])
            return "Something unrelated entirely"
        return "Witaj drogi przyjacielu z aplikacji"

    result = run_translation(
        cfg, catalog, NullProvider(handler=handler), force=True, report=silent,
    )
    assert result.flagged_low_score, "expected an in-memory low-score flag"
    store = FlagStore(flags_path)
    assert "app.greet" in store.grouped().get("pl", set()), (
        "low-score flag must remain on disk after flush"
    )


def test_flagged_retranslate_clears_prior_flag_when_score_is_ok(
    project_root, make_config, make_catalog, provider, silent,
) -> None:
    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "stare"})
    path = project_root / "flags.jsonl"
    write_flags(path, [{"namespace": "app", "key": "greet", "locale": "pl", "reason": "old"}])
    cfg = make_config(project_root, flags_path=path, quality_thresholds={"pl": 0.01})
    catalog = make_catalog(cfg)

    result = run_translation(
        cfg, catalog, provider, only_keys=_flagged_keys(cfg), report=silent,
    )
    assert result.written == 1
    from llm_localizator.catalog import FlagStore
    assert FlagStore(path).grouped() == {}


def test_flagged_skips_verified_unless_force(
    project_root, make_config, make_catalog, provider, silent,
) -> None:
    from llm_localizator.catalog import make_entry
    from llm_localizator.catalog.state import now_iso

    setup_project(project_root, {"greet": "Hello"}, existing={"greet": "Witaj"})
    path = project_root / "flags.jsonl"
    write_flags(path, [{"namespace": "app", "key": "greet", "locale": "pl"}])
    cfg = make_config(project_root, flags_path=path)
    catalog = make_catalog(cfg)
    store = StateStore(cfg.state_dir)
    entry = make_entry("Hello", "m")
    entry["verified_at"] = now_iso()
    store.record("pl", "app", "greet", entry)
    store.save("pl")

    result = run_translation(
        cfg, catalog, provider, only_keys=_flagged_keys(cfg), report=silent,
    )
    assert result.total == 0
    assert catalog.load("pl", "app")["greet"] == "Witaj"

    result = run_translation(
        cfg, catalog, provider, only_keys=_flagged_keys(cfg), force=True, report=silent,
    )
    assert result.total == 1
