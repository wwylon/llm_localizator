"""End-to-end translation against the null provider.

No Ollama, no network, no GPU. Covers the edge cases observed in bridge's live
catalogue, each of which was previously untested.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.catalog import StateStore
from llm_localizator.pipeline.translate import (
    WorkItem,
    _order_locales,
    _shorten,
    run_translation,
)
from llm_localizator.providers import CompletionRequest, NullProvider

from ..conftest import setup_project, tagged, write_json


@pytest.fixture
def provider() -> NullProvider:
    return NullProvider(handler=tagged)


# ---- basic flow ------------------------------------------------------------

def test_translates_and_writes(project_root, make_config, make_catalog, provider, silent) -> None:
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)

    result = run_translation(cfg, catalog, provider, report=silent)

    assert result.written == 2
    assert catalog.load("pl", "app") == {"greet": "[xx] Hello", "bye": "[xx] Goodbye"}
    runs = list((cfg.state_root() / "_runs").glob("*.json"))
    assert runs, "run manifest should be written"
    import json
    row = json.loads(runs[0].read_text(encoding="utf-8"))
    assert row["command"] == "translate"
    assert row.get("wall_s") is not None
    assert row["metrics"].get("keys_per_s", 0) > 0


def test_state_is_recorded_with_iso_timestamp(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root)
    run_translation(cfg, make_catalog(cfg), provider, report=silent)

    entry = StateStore(cfg.state_dir).entry("pl", "app", "greet")
    assert entry is not None
    assert entry["model"] == "testmodel"
    # F-003: never the literal string "now" again.
    assert entry["translated_at"] not in ("now", "bootstrap")
    assert entry["translated_at"].endswith("Z")


def test_second_run_is_a_noop(project_root, make_config, make_catalog, provider, silent) -> None:
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)

    run_translation(cfg, catalog, provider, report=silent)
    calls_after_first = provider.call_count
    second = run_translation(cfg, catalog, provider, report=silent)

    assert second.total == 0
    assert provider.call_count == calls_after_first, "no provider calls on an up-to-date run"


def test_frozen_locales_skipped_unless_explicit(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"}, locale="pl")
    setup_project(project_root, {"greet": "Hello"}, locale="de")
    cfg = make_config(project_root, targets=["pl", "de"], frozen=["de"])
    catalog = make_catalog(cfg)

    result = run_translation(cfg, catalog, provider, report=silent)
    assert result.written == 1
    assert catalog.load("pl", "app")["greet"] == "[xx] Hello"
    assert "greet" not in catalog.load("de", "app")

    forced = run_translation(cfg, catalog, provider, locales=["de"], report=silent)
    assert forced.written == 1
    assert catalog.load("de", "app")["greet"] == "[xx] Hello"


def test_edited_source_marks_only_that_key_stale(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"a": "Alpha", "b": "Beta"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    run_translation(cfg, catalog, provider, report=silent)

    setup_project(project_root, {"a": "Alpha CHANGED", "b": "Beta"})
    result = run_translation(cfg, catalog, provider, report=silent)

    assert result.total == 1
    assert result.written == 1


def test_dry_run_writes_nothing(project_root, make_config, make_catalog, provider, silent) -> None:
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)

    result = run_translation(cfg, catalog, provider, dry_run=True, report=silent)

    assert result.total == 1
    assert result.written == 0
    assert provider.call_count == 0
    assert not catalog.path_for("pl", "app").exists()
    # A dry run writes nothing by definition; that is success, not failure.
    # CI uses --dry-run as a preflight check and would break on a non-zero exit.
    assert result.exit_code == 0


def test_force_retranslates_everything(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"a": "Alpha"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    run_translation(cfg, catalog, provider, report=silent)
    result = run_translation(cfg, catalog, provider, force=True, report=silent)
    assert result.total == 1


def test_skip_keys_are_never_translated(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"brand": "Bridge", "greet": "Hello"})
    cfg = make_config(project_root, skip_keys={"brand"})
    result = run_translation(cfg, make_catalog(cfg), provider, report=silent)
    assert result.total == 1


def test_skip_namespaces_are_not_overridden_by_namespace(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    """``admin`` skips ``admin/users``. ``--namespace`` does not put it back."""
    setup_project(project_root, {"signIn": "Sign in"}, namespace="admin/users")
    setup_project(project_root, {"home": "Home"}, namespace="nav")
    cfg = make_config(project_root, skip_namespaces={"admin"})
    result = run_translation(
        cfg, make_catalog(cfg), provider, report=silent, namespaces=["admin/users"],
    )
    assert result.total == 0
    assert make_catalog(cfg).load("pl", "admin/users") == {}


# ---- edge cases observed in the live bridge catalogue ----------------------

def test_locale_missing_a_namespace_file_is_created(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    """de has no courses.json; the file must be created, not skipped."""
    setup_project(project_root, {"a": "Alpha"}, namespace="courses")
    cfg = make_config(project_root, targets=["de"])
    catalog = make_catalog(cfg)
    assert not catalog.path_for("de", "courses").exists()

    run_translation(cfg, catalog, provider, report=silent)

    assert catalog.path_for("de", "courses").exists()
    assert catalog.load("de", "courses") == {"a": "[xx] Alpha"}


def test_locale_with_empty_state_translates_everything(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    """cs/es/ru/tr sit in the roster with 3-byte {} state files (F-007)."""
    setup_project(project_root, {"a": "Alpha", "b": "Beta"})
    cfg = make_config(project_root, targets=["cs"])
    (cfg.state_dir).mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "cs.json").write_text("{}", encoding="utf-8")

    result = run_translation(cfg, make_catalog(cfg), provider, report=silent)
    assert result.total == 2
    assert result.written == 2


def test_orphan_key_is_pruned_on_write(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"a": "Alpha"},
                  existing={"a": "stary", "removed": "sierota"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)

    run_translation(cfg, catalog, provider, force=True, report=silent)

    assert "removed" not in catalog.load("pl", "app")


def test_untranslated_key_falls_back_to_source_on_disk(
    project_root, make_config, make_catalog, silent
) -> None:
    """A provider failure must still leave a structurally complete file."""
    setup_project(project_root, {"a": "Alpha", "b": "Beta"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    # Fails the batch, then fails every per-key retry too.
    provider = NullProvider(fail_on="Translate")

    result = run_translation(cfg, catalog, provider, report=silent)

    assert result.written == 0
    assert len(result.skipped) == 2


def test_needs_context_is_not_a_provider_error(
    project_root, make_config, make_catalog, provider
) -> None:
    """High-risk keys with no note are blocked, not counted as provider failures."""
    lines: list[str] = []
    setup_project(project_root, {"danger": "Delete the account"})
    cfg = make_config(project_root)

    result = run_translation(
        cfg, make_catalog(cfg), provider, report=lines.append,
    )

    assert result.written == 0
    assert result.blocked == ["pl/app.danger"]
    assert result.skipped == []
    assert provider.call_count == 0
    assert any("blocked (needs_context)" in line for line in lines)
    assert not any("provider errors" in line for line in lines)


# ---- pivot ordering --------------------------------------------------------

def test_pivot_reference_is_ordered_before_its_variant() -> None:
    from llm_localizator.projects.config import ProjectConfig

    cfg = ProjectConfig(root=Path("."), name="x",
                        targets=["pt-BR", "pl", "pt-PT"],
                        pivots={"pt-BR": "pt-PT"})
    ordered = _order_locales(cfg, cfg.targets)
    assert ordered.index("pt-PT") < ordered.index("pt-BR")


def test_pivot_cycle_does_not_hang() -> None:
    from llm_localizator.projects.config import ProjectConfig

    cfg = ProjectConfig(root=Path("."), name="x",
                        targets=["a", "b"], pivots={"a": "b", "b": "a"})
    assert sorted(_order_locales(cfg, cfg.targets)) == ["a", "b"]


def test_pivot_value_reaches_the_prompt(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    write_json(project_root / "messages" / "pt-PT" / "app.json", {"greet": "Olá"})
    cfg = make_config(project_root, targets=["pt-BR"], pivots={"pt-BR": "pt-PT"})
    provider = NullProvider(handler=tagged)

    run_translation(cfg, make_catalog(cfg), provider, report=silent)

    assert any("Olá" in c.prompt for c in provider.calls), "pivot reference must be in the prompt"


# ---- validation and rejection ---------------------------------------------

def test_masked_placeholder_numbers_are_accepted(
    project_root, make_config, make_catalog, silent
) -> None:
    from llm_localizator.pipeline.placeholder_mask import mask_bare_placeholders

    source = "{players} players"
    masked, mapping = mask_bare_placeholders(source)
    token = next(iter(mapping))
    setup_project(project_root, {"liveStats": source})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)

    def handler(request):
        if request.schema:
            return json.dumps([f"{token} graczy"])
        return f"{token} graczy"

    provider = NullProvider(handler=handler)
    result = run_translation(cfg, catalog, provider, force=True, report=silent)

    assert result.written == 1
    assert catalog.load("pl", "app")["liveStats"] == "{players} graczy"


def test_decomposed_translation_preserves_bare_placeholders(
    project_root, make_config, make_catalog, silent
) -> None:
    source = (
        "Session total: NS {ns} · EW {ew} "
        "({boards, plural, one {# board} other {# boards}})"
    )
    boards_pl = (
        "{boards, plural, one {# rozdanie} few {# rozdania} "
        "many {# rozdań} other {# rozdań}}"
    )
    setup_project(project_root, {"streamRunningTotal": source}, namespace="play")
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)

    def handler(request: CompletionRequest) -> str:
        prompt = request.prompt
        if "ICU fragment" in prompt and "{boards, plural" in prompt:
            return boards_pl
        if "Session total: NS" in prompt:
            return "Suma sesji: NS "
        if " · EW " in prompt:
            return " · EW "
        return ""

    provider = NullProvider(handler=handler)
    result = run_translation(cfg, catalog, provider, force=True, report=silent)

    assert result.written == 1
    out = catalog.load("pl", "play")["streamRunningTotal"]
    assert "{ns}" in out and "{ew}" in out and "{boards, plural" in out
    assert "Suma sesji" in out


def test_rejected_translation_keeps_the_existing_value(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello {name}"}, existing={"greet": "Witaj {name}"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    # Drops the placeholder -> must be rejected.
    provider = NullProvider(handler=lambda r: json.dumps(["Witaj"]) if r.schema else "Witaj")

    result = run_translation(cfg, catalog, provider, force=True, report=silent)

    assert result.written == 0
    assert len(result.rejected) == 1
    assert result.exit_code == 1
    assert catalog.load("pl", "app")["greet"] == "Witaj {name}", "previous value survives"


def test_rejection_leaves_state_untouched_so_the_key_retries(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello {name}"})
    cfg = make_config(project_root)
    provider = NullProvider(handler=lambda r: json.dumps(["Witaj"]) if r.schema else "Witaj")

    run_translation(cfg, make_catalog(cfg), provider, report=silent)

    store = StateStore(cfg.state_dir)
    assert store.entry("pl", "app", "greet") is None


# ---- batching and checkpointing -------------------------------------------

def test_batch_size_controls_request_count(
    project_root, make_config, make_catalog, silent
) -> None:
    # Strings must be ≥4 words so they stay in batch mode (short labels go single).
    setup_project(
        project_root,
        {f"k{i}": f"This is longer source value number {i}" for i in range(10)},
    )
    cfg = make_config(project_root)
    provider = NullProvider(handler=tagged)

    run_translation(cfg, make_catalog(cfg), provider, batch_size=5, report=silent)

    # Two batch translate calls plus one back-translation per key.
    assert provider.call_count == 12


def test_batch_failure_falls_back_to_per_key(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(
        project_root,
        {"a": "Alpha string for batching tests", "b": "Beta string for batching tests"},
    )
    cfg = make_config(project_root)

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            if "Alpha" in request.prompt:
                return "Alpha string for batching tests"
            if "Beta" in request.prompt:
                return "Beta string for batching tests"
            return request.prompt.strip().splitlines()[-1].replace("[xx] ", "")
        if request.schema is not None:
            return "not a json array at all"
        return "[xx] single"

    provider = NullProvider(handler=handler)
    result = run_translation(cfg, make_catalog(cfg), provider, report=silent)

    assert result.written == 2
    # Failed batch + per-key singles + back-translation scoring per key.
    assert provider.call_count == 9


def test_state_is_flushed_after_each_batch(
    project_root, make_config, make_catalog, silent
) -> None:
    """Checkpointing bounds loss to one in-flight batch if the process is killed."""
    setup_project(
        project_root,
        {f"k{i}": f"This is longer source value number {i}" for i in range(4)},
    )
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    seen: list[int] = []

    def handler(request: CompletionRequest) -> str:
        if request.schema is not None:
            path = cfg.state_dir / "pl.json"
            seen.append(len(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else 0)
        return tagged(request)

    run_translation(cfg, catalog, NullProvider(handler=handler), batch_size=2, report=silent)

    assert seen == [0, 2], "the second batch must start with the first already persisted"


def test_min_keys_skips_tiny_backlog_without_provider_calls(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    cfg = make_config(project_root, translate_min_keys=50)
    before = provider.call_count
    result = run_translation(cfg, make_catalog(cfg), provider, report=silent)
    assert result.total == 0
    assert result.written == 0
    assert result.exit_code == 0
    assert provider.call_count == before


def test_min_keys_bypassed_by_force(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root, translate_min_keys=50)
    result = run_translation(cfg, make_catalog(cfg), provider, force=True, report=silent)
    assert result.written == 1
    assert result.exit_code == 0


def test_min_keys_bypassed_by_ignore_min_keys(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    cfg = make_config(project_root, translate_min_keys=50)
    result = run_translation(
        cfg, make_catalog(cfg), provider, ignore_min_keys=True, report=silent,
    )
    assert result.written == 1
    assert result.exit_code == 0


def test_min_keys_skips_only_the_small_locale(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    from llm_localizator.core.hash import src_hash

    source = {"a": "A", "b": "B", "c": "C", "d": "D"}
    setup_project(project_root, source, existing={"a": "już", "b": "już", "c": "C", "d": "D"})
    cfg = make_config(project_root, targets=["pl", "de"], translate_min_keys=3)
    store = StateStore(cfg.state_dir)
    for key in ("a", "b"):
        store.record("pl", "app", key, {
            "src_sha": src_hash(source[key]),
            "status": "machine",
            "model": "testmodel",
        })
    store.save("pl")
    catalog = make_catalog(cfg)
    result = run_translation(cfg, catalog, provider, report=silent)
    assert catalog.load("de", "app")["a"] == "[xx] A"
    assert catalog.load("pl", "app")["c"] == "C"
    assert result.written == 4


def test_min_keys_dry_run_still_lists_backlog(
    project_root, make_config, make_catalog, provider, silent
) -> None:
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    cfg = make_config(project_root, translate_min_keys=50)
    lines: list[str] = []
    result = run_translation(
        cfg, make_catalog(cfg), provider, dry_run=True, report=lines.append,
    )
    assert result.total == 2
    assert result.exit_code == 0
    assert any("Would translate 2" in line for line in lines)


def test_consecutive_rejects_abort_run(
    project_root, make_config, make_catalog, silent
) -> None:
    """Junk output trips the circuit breaker before burning the whole backlog."""
    setup_project(
        project_root,
        {f"k{i}": f"Button label {i}" for i in range(5)},
    )
    cfg = make_config(
        project_root,
        translate_min_keys=0,
        translate_max_consecutive_rejects=3,
    )
    # Extra placeholders → validate_candidate rejects.
    bad = "{done} {missing} {stale} invented"

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            return "Button label"
        if request.schema is not None:
            from llm_localizator.providers.null import _numbered_lines
            n = len(_numbered_lines(request.prompt))
            return json.dumps([bad] * n)
        return bad

    provider = NullProvider(handler=handler)
    result = run_translation(
        cfg, make_catalog(cfg), provider, batch_size=1, report=silent,
    )
    assert result.aborted
    assert result.exit_code == 1
    assert len(result.rejected) >= 3
    assert result.written == 0


def test_dual_candidate_keeps_higher_scoring_secondary(
    project_root, make_config, make_catalog, silent
) -> None:
    """prefer_secondary runs a second model; history records both candidates."""
    from llm_localizator.catalog.history import HistoryStore
    from llm_localizator.projects.config import LocaleRole

    # Multi-word source so BT overlap affects the score (short labels skip it).
    # Not a high-risk pattern string — those need context notes or --force.
    source = "Please confirm your selection"
    setup_project(project_root, {"greet": source})
    cfg = make_config(
        project_root,
        models={"default": "primary"},
        roles={
            "pl": LocaleRole(
                primary="primary",
                secondary="secondary",
                prefer_secondary=True,
            ),
        },
    )

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            line = request.prompt.strip().splitlines()[-1]
            if line.startswith("[secondary] "):
                return source
            return "zzz totally unrelated nonsense words"
        tag = request.model or "primary"
        if request.schema is not None:
            from llm_localizator.providers.null import _numbered_lines
            return json.dumps(
                [f"[{tag}] {s}" for s in _numbered_lines(request.prompt)],
                ensure_ascii=False,
            )
        return f"[{tag}] " + request.prompt.strip().splitlines()[-1]

    provider = NullProvider(handler=handler)
    catalog = make_catalog(cfg)
    result = run_translation(cfg, catalog, provider, report=silent)
    assert result.written == 1
    assert catalog.load("pl", "app")["greet"] == f"[secondary] {source}"

    entry = StateStore(cfg.state_dir).entry("pl", "app", "greet")
    assert entry is not None
    assert entry["model"] == "secondary"

    hist = HistoryStore(cfg.history_root()).latest("pl", "app", "greet")
    assert hist is not None
    assert hist.candidates is not None
    assert len(hist.candidates) == 2
    models = {c["model"] for c in hist.candidates}
    assert models == {"primary", "secondary"}


def test_secondary_model_is_warmed_once_not_per_item(
    project_root, make_config, make_catalog, silent
) -> None:
    from llm_localizator.projects.config import LocaleRole

    sources = {f"k{i}": f"Please confirm selection number {i}" for i in range(4)}
    setup_project(project_root, sources)
    cfg = make_config(
        project_root, models={"default": "primary"},
        roles={"pl": LocaleRole(primary="primary", secondary="secondary", prefer_secondary=True)},
    )

    def handler(request: CompletionRequest) -> str:
        tag = request.model or "primary"
        if request.schema is not None:
            from llm_localizator.providers.null import _numbered_lines
            return json.dumps([f"[{tag}] {s}" for s in _numbered_lines(request.prompt)])
        return f"[{tag}] " + request.prompt.strip().splitlines()[-1]

    warmed: list[str] = []

    class Counting(NullProvider):
        def ensure_ready(self, model, *, report=None):
            warmed.append(model)

    run_translation(cfg, make_catalog(cfg), Counting(handler=handler), report=silent)
    assert warmed.count("secondary") <= 1


# ---- shorten acceptance gate -----------------------------------------------

class _EmptyNotes:
    def note(self, namespace: str, key: str) -> str:
        return ""


def _run_shorten(make_config, project_root, handler, *, source: str, prior: str,
                 locale: str = "pl", max_chars: int = 20, check_html=None):
    warnings: list[str] = []
    cfg = make_config(project_root)
    item = WorkItem(namespace="app", locale=locale, key="label", source=source)
    out = _shorten(
        NullProvider(handler=handler),
        item,
        prior,
        "Polish" if locale == "pl" else locale,
        max_chars,
        "testmodel",
        cfg,
        "",
        _EmptyNotes(),
        "informal",
        warnings.append,
        glossary={},
        check_html=check_html,
    )
    return out, warnings


def test_shorten_rejects_unexpected_script(project_root, make_config) -> None:
    prior = "Anuluj przycisk tekst"
    bad = "取消按钮文字"

    def handler(request: CompletionRequest) -> str:
        return bad

    out, warnings = _run_shorten(
        make_config, project_root, handler, source="Cancel button", prior=prior,
    )
    assert out == prior
    assert any("shorten rejected" in w for w in warnings)


def test_shorten_rejects_broken_icu(project_root, make_config) -> None:
    source = "{count} items"
    prior = "{count} pozycji za długich"
    bad = "pozycji"  # missing placeholder

    def handler(request: CompletionRequest) -> str:
        return bad

    out, warnings = _run_shorten(
        make_config, project_root, handler, source=source, prior=prior,
    )
    assert out == prior
    assert any("shorten rejected" in w for w in warnings)


def test_shorten_rejects_html_damage(project_root, make_config) -> None:
    source = "<b>Save</b>"
    prior = "<b>Zapisz teraz dłużej</b>"
    bad = "Zapisz"  # dropped tags

    def handler(request: CompletionRequest) -> str:
        return bad

    out, warnings = _run_shorten(
        make_config, project_root, handler, source=source, prior=prior,
        check_html=True,
    )
    assert out == prior
    assert any("shorten rejected" in w for w in warnings)


def test_shorten_accepts_valid_short_text(project_root, make_config) -> None:
    prior = "Anuluj tę operację teraz"
    good = "Anuluj"

    def handler(request: CompletionRequest) -> str:
        return good

    out, warnings = _run_shorten(
        make_config, project_root, handler, source="Cancel", prior=prior,
        max_chars=10,
    )
    assert out == good
    assert not any("shorten rejected" in w for w in warnings)
