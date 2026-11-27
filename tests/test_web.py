"""The web interface's data layer and save path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.projects import load_config
from llm_localizator.web import build_state, findings, messages, overview, save
from llm_localizator.web.server import (
    verify_key, overview_lite, overview_stats, message_row,
    _coverage_bucket, _registered_project_names, _load_primary_state,
)
from llm_localizator.web.index import MAX_PAGE_LIMIT
from llm_localizator.web.translator import translator_lookup

from .conftest import write_json

CONFIG = """
[project]
name = "demo"
data_home = "project"   # state beside the config, where the fixture writes it (ADR-112 default is the engine home)

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
        "bye": "Goodbye",
        "same": "Bridge",
        "gone": "Not translated yet",
    })
    write_json(tmp_path / "messages" / "pl" / "app.json", {
        "greet": "Witaj {name}",
        "bye": "Zegnaj",
        "same": "Bridge",
    })
    store = StateStore(tmp_path / "messages" / ".state")
    store.record("pl", "app", "greet", make_entry("Hello {name}", "m"))
    store.record("pl", "app", "bye", make_entry("OLD SOURCE", "m"))   # -> stale
    store.record("pl", "app", "same", make_entry("Bridge", "m"))
    store.save("pl")
    return build_state(load_config(tmp_path / ".llm-localize.toml"))


# ---- overview --------------------------------------------------------------

def test_overview_reports_coverage(app) -> None:
    o = overview(app)
    assert o["project"] == "demo"
    assert o["sourceLocale"] == "en"
    assert o.get("hasContext") is False
    assert "taskqueueAvailable" in o
    assert isinstance(o["taskqueueAvailable"], bool)
    assert [n["name"] for n in o["namespaces"]] == ["app"]

    pl = o["locales"][0]
    assert pl["locale"] == "pl"
    assert pl["frozen"] is False
    assert o["activeLocales"] == ["pl"]
    assert o["frozenLocales"] == []
    assert pl["total"] == 4
    assert pl["stale"] == 1        # bye
    assert pl["missing"] == 1      # gone
    assert 0 < pl["coverage"] < 100


def test_overview_excludes_skip_keys(tmp_path: Path) -> None:
    (tmp_path / ".llm-localize.toml").write_text(
        CONFIG.replace('path = "messages', 'skip_keys = ["brand"]\npath = "messages'),
        encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"brand": "X", "a": "A"})
    st = build_state(load_config(tmp_path / ".llm-localize.toml"))
    assert overview(st)["locales"][0]["total"] == 1


def test_overview_lite_is_fast_shape(app) -> None:
    lite = overview_lite(app)
    assert lite["project"] == "demo"
    assert lite["sourceTotal"] == 4
    assert "scaleHints" in lite
    assert lite["scaleHints"]["maxPageLimit"] == MAX_PAGE_LIMIT
    assert "locales" not in lite


def test_overview_stats_matches_combined(app) -> None:
    stats = overview_stats(app)
    combined = overview(app)
    assert stats["locales"] == combined["locales"]
    assert "pendingReview" in stats
    assert "avgQuality" in stats
    assert "qualityBins" in stats
    assert len(stats["qualityBins"]) == 6
    assert "lastRunAt" in stats
    assert combined["pendingReview"] == stats["pendingReview"]


def test_refresh_sidecars_picks_up_cli_adopt(tmp_path: Path) -> None:
    """CLI/ops adopt writes via a separate StateStore; web must re-read disk."""
    from llm_localizator.ops.adopt import op_adopt
    from llm_localizator.ops.types import AdoptRequest
    from llm_localizator.web.server import refresh_sidecars_from_disk

    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {"greet": "Cześć"})
    st = build_state(load_config(tmp_path / ".llm-localize.toml"))

    before = overview_stats(st)["locales"][0]
    assert before["missing"] + before.get("no_record", 0) == 1
    assert before["translated"] == 0

    # Out-of-band adopt (same as CLI): writes disk, does not touch st.store cache.
    result = op_adopt(st.cfg, AdoptRequest(locales=["pl"]))
    assert result.data["adopted"] == 1

    # Still stale until refresh — in-memory store predates the write.
    row = overview_stats(st)["locales"][0]
    assert row["missing"] + row.get("no_record", 0) == 1

    refresh_sidecars_from_disk(st)
    after = overview_stats(st)["locales"][0]
    assert after["translated"] == 1
    assert after["missing"] == 0


def test_messages_limit_clamped(app) -> None:
    page = messages(app, ["pl"], "app", limit=9999)
    assert page["counts"]["limit"] == MAX_PAGE_LIMIT


def test_messages_limit_non_positive_uses_default(app) -> None:
    from llm_localizator.web.index import clamp_limit

    assert clamp_limit(0) == 100
    assert clamp_limit(-1) == 100
    assert clamp_limit(None) == 100
    page = messages(app, ["pl"], "app", limit=0)
    assert page["counts"]["limit"] == 100
    assert len(page["rows"]) <= 100


def test_messages_server_sort(app) -> None:
    asc = messages(app, ["pl"], "app", sort="key", sort_dir="asc")["rows"]
    desc = messages(app, ["pl"], "app", sort="key", sort_dir="desc")["rows"]
    assert [r["key"] for r in asc] == sorted(r["key"] for r in asc)
    assert [r["key"] for r in desc] == sorted((r["key"] for r in desc), reverse=True)


def test_findings_keys_scoped(app) -> None:
    payload = findings(app, "pl", "app", keys=[("app", "gone")])
    assert payload["ok"] is True
    assert "gone" in payload["byKey"]
    assert "greet" not in payload["byKey"]


def test_findings_partial_at_scale(app, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_localizator.web.server_logic.FULL_FINDINGS_THRESHOLD", 2,
    )
    payload = findings(app, "pl", "app")
    assert payload.get("partial") is True
    assert payload["byKey"] == {}


def test_findings_full_all_still_partial_at_scale(
    app, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_localizator.web.server_logic.FULL_FINDINGS_THRESHOLD", 2,
    )
    payload = findings(app, "pl", "__all__", full=True)
    assert payload.get("partial") is True
    assert payload["byKey"] == {}


def test_findings_full_one_namespace_allowed_at_scale(
    app, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_localizator.web.server_logic.FULL_FINDINGS_THRESHOLD", 2,
    )
    payload = findings(app, "pl", "app", full=True)
    assert payload.get("partial") is not True
    assert payload["ok"] is True


def test_message_row_full_detail(app) -> None:
    row = message_row(app, ["pl"], "app", "greet")
    assert row["ok"] is True
    assert row["row"]["key"] == "greet"
    assert row["row"]["source"] == "Hello {name}"
    assert "glossaryHits" in row["row"]


def test_messages_full_detail_skips_glossary_hits(app) -> None:
    """Glossary regex work stays on /api/messages/row, not the list path."""
    payload = messages(app, ["pl"], "app", detail="full")
    assert payload["rows"]
    assert payload["rows"][0].get("glossaryHits") == []
    row = message_row(app, ["pl"], "app", "greet")
    assert isinstance(row["row"].get("glossaryHits"), list)


def test_translator_lookup_single_key(app) -> None:
    hit = translator_lookup(app, "pl", "app", "greet")
    assert hit["source"] == "Hello {name}"
    assert hit["target"] == "Witaj {name}"


def test_save_partial_cache_invalidation(app) -> None:
    overview_lite(app)
    overview_stats(app)
    assert app._overview_cache is not None
    assert app._overview_stats_cache is not None
    messages(app, ["pl"], "app")
    cache_key = (("pl",), "app")
    assert cache_key in app._message_index_cache
    old_stale = app._overview_stats_cache["locales"][0]["stale"]
    save(app, "pl", "app", "bye", "Do widzenia")
    assert cache_key in app._message_index_cache
    row = next(r for r in app._message_index_cache[cache_key].rows if r.key == "bye")
    assert row.statuses["pl"] == "human"
    assert app._overview_stats_cache is not None
    assert app._overview_stats_cache["locales"][0]["stale"] == max(0, old_stale - 1)
    assert app._overview_cache is not None


def test_messages_detail_minimal(app) -> None:
    payload = messages(app, ["pl"], "app", detail="minimal")
    row = next(r for r in payload["rows"] if r["key"] == "greet")
    assert row["qualitySignals"] == []
    assert row["note"] == ""
    assert row["fullKey"] is None


def test_messages_detail_full(app) -> None:
    payload = messages(app, ["pl"], "app", detail="full")
    assert payload["detail"] == "full"


def test_coverage_bucket_matches_stats(app) -> None:
    overview_stats(app)
    assert _coverage_bucket(app, "pl", "app", "bye") == "stale"
    assert _coverage_bucket(app, "pl", "app", "gone") == "missing"


def test_registered_project_names() -> None:
    names = _registered_project_names("demo")
    assert "demo" in names


def test_load_primary_state_only(tmp_path: Path) -> None:
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"a": "A"})
    cfg = load_config(tmp_path / ".llm-localize.toml")
    states = _load_primary_state(cfg)
    assert list(states) == ["demo"]


@pytest.mark.slow
def test_10k_index_pagination(tmp_path: Path) -> None:
    keys = {f"k{i:05d}": f"Source {i}" for i in range(10_000)}
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", keys)
    write_json(
        tmp_path / "messages" / "pl" / "app.json",
        {k: f"T{i}" for i, k in enumerate(keys)},
    )
    st = build_state(load_config(tmp_path / ".llm-localize.toml"))
    page = messages(st, ["pl"], "app", offset=9990, limit=10, detail="minimal")
    assert page["counts"]["total"] == 10_000
    assert len(page["rows"]) == 10
    assert page["rows"][0]["key"] == "k09990"


def test_large_catalog_pagination(tmp_path: Path) -> None:
    keys = {f"k{i:04d}": f"Source {i}" for i in range(600)}
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", keys)
    write_json(tmp_path / "messages" / "pl" / "app.json", {k: f"T {i}" for i, k in enumerate(keys)})
    st = build_state(load_config(tmp_path / ".llm-localize.toml"))
    lite = overview_lite(st)
    assert lite["scaleHints"]["pageSizeAllDisabled"] is True
    page = messages(st, ["pl"], "app", offset=0, limit=100)
    assert page["counts"]["total"] == 600
    assert len(page["rows"]) == 100


# ---- messages --------------------------------------------------------------

def test_messages_classifies_each_row(app) -> None:
    rows = {r["key"]: r for r in messages(app, ["pl"], "app")["rows"]}
    assert rows["greet"]["statuses"]["pl"] == "machine"
    assert rows["bye"]["statuses"]["pl"] == "stale"
    assert rows["same"]["statuses"]["pl"] == "untranslated"   # identical to source
    assert rows["gone"]["statuses"]["pl"] == "missing"
    assert rows["gone"]["values"]["pl"] is None


def test_messages_includes_quality_score(app) -> None:
    from llm_localizator.catalog import ScoreStore

    scores = ScoreStore(app.cfg.scores_root())
    scores.record("pl", "app", "greet", score=0.42, signals=["bt_mismatch"], text="Witaj {name}")
    scores.record("pl", "app", "same", score=0.91, signals=[], text="Bridge")
    scores.save("pl")

    payload = messages(app, ["pl"], "app", detail="full")
    assert payload["qualityThreshold"] == pytest.approx(0.55)
    rows = {r["key"]: r for r in payload["rows"]}
    assert rows["greet"]["qualityScore"] == pytest.approx(0.42)
    assert rows["greet"]["qualitySignals"] == ["bt_mismatch"]
    assert rows["same"]["qualityScore"] == pytest.approx(0.91)
    assert rows["gone"]["qualityScore"] is None

    assert {r["key"] for r in messages(app, ["pl"], "app", only="low_score")["rows"]} == {"greet"}
    # unscored = has translation status worth reviewing but no score yet
    unscored = {r["key"] for r in messages(app, ["pl"], "app", only="unscored")["rows"]}
    assert "greet" not in unscored
    assert "same" not in unscored
    assert "gone" not in unscored
    assert "bye" in unscored


def test_messages_carries_source_alongside_translation(app) -> None:
    row = next(r for r in messages(app, ["pl"], "app")["rows"] if r["key"] == "greet")
    assert row["source"] == "Hello {name}"
    assert row["values"]["pl"] == "Witaj {name}"


def test_messages_light_has_empty_findings_by_default(app) -> None:
    rows = {r["key"]: r for r in messages(app, ["pl"], "app")["rows"]}
    assert rows["gone"]["findings"] == []


def test_messages_include_findings_and_findings_api(app) -> None:
    rows = {
        r["key"]: r
        for r in messages(app, ["pl"], "app", include_findings=True)["rows"]
    }
    assert any("V01" in f for f in rows["gone"]["findings"])
    payload = findings(app, "pl", "app")
    assert payload["ok"] is True
    assert any("V01" in f for f in payload["byKey"]["gone"])


def test_messages_pagination(app) -> None:
    page = messages(app, ["pl"], "app", offset=0, limit=2)
    assert page["counts"]["total"] == 4
    assert len(page["rows"]) == 2
    page2 = messages(app, ["pl"], "app", offset=2, limit=2)
    assert len(page2["rows"]) == 2
    keys = {r["key"] for r in page["rows"]} | {r["key"] for r in page2["rows"]}
    assert keys == {"greet", "bye", "same", "gone"}


@pytest.mark.parametrize("only,expected", [
    ("missing", {"gone"}), ("stale", {"bye"}), ("untranslated", {"same"}),
])
def test_status_filter(app, only: str, expected: set[str]) -> None:
    assert {r["key"] for r in messages(app, ["pl"], "app", only=only)["rows"]} == expected


def test_has_findings_filter(app) -> None:
    rows = messages(app, ["pl"], "app", only="has_findings")["rows"]
    # "gone" has a V01 finding (missing translation); others should be absent
    assert any(r["key"] == "gone" for r in rows)
    assert all(r["findings"] for r in rows)


def test_query_matches_key_source_and_translation(app) -> None:
    keys = lambda q: {r["key"] for r in messages(app, ["pl"], "app", query=q)["rows"]}
    assert keys("greet") == {"greet"}          # by key
    assert keys("Goodbye") == {"bye"}          # by source
    assert keys("Witaj") == {"greet"}          # by translation
    assert keys("zzz") == set()


def test_messages_multi_locale_compare(app) -> None:
    """Compare columns carry values for each locale; primary status still filters."""
    # add a second locale with a different value
    write_json(app.cfg.root / "messages" / "en" / "auth.json", {"hi": "Hi"})
    write_json(app.cfg.root / "messages" / "pl" / "auth.json", {"hi": "Cześć"})
    # for compare we use the same locale twice (contrived but exercises the path)
    d = messages(app, ["pl", "pl"], "app")
    row = next(r for r in d["rows"] if r["key"] == "greet")
    assert "pl" in row["values"]
    assert d["locales"] == ["pl", "pl"]


# ---- save ------------------------------------------------------------------

def test_save_writes_the_translation(app) -> None:
    assert save(app, "pl", "app", "bye", "Do widzenia")["ok"] is True
    assert app.catalog.load("pl", "app")["bye"] == "Do widzenia"


def test_save_marks_the_key_as_human_edited(app) -> None:
    save(app, "pl", "app", "bye", "Do widzenia")
    entry = StateStore(app.cfg.state_dir).entry("pl", "app", "bye")
    assert entry["status"] == "human"
    assert entry["model"] == "human"
    assert entry["provider"] == "human"


def test_save_agent_stamps_provider(app) -> None:
    result = save(
        app, "pl", "app", "bye", "Do widzenia",
        provider="agent", model="cursor-agent",
    )
    assert result["ok"] is True
    assert result["provider"] == "agent"
    entry = StateStore(app.cfg.state_dir).entry("pl", "app", "bye")
    assert entry["provider"] == "agent"
    assert entry["model"] == "cursor-agent"
    assert entry["status"] == "agent"
    assert entry.get("verified_by") == "cursor-agent"
    history = (app.cfg.history_dir or app.cfg.root / ".llm-history") / "pl.jsonl"
    assert '"trigger": "agent-edit"' in history.read_text(encoding="utf-8")
    assert '"provider": "agent"' in history.read_text(encoding="utf-8")


def test_messages_exposes_provider(app) -> None:
    rows = {r["key"]: r for r in messages(app, ["pl"], "app")["rows"]}
    assert rows["greet"]["provider"] == "ollama"
    assert rows["greet"]["model"] == "m"
    local = {r["key"] for r in messages(app, ["pl"], "app", only="provider_local")["rows"]}
    assert "greet" in local
    assert "gone" not in local


def test_save_records_score_and_history(app) -> None:
    save(app, "pl", "app", "bye", "Do widzenia")
    from llm_localizator.catalog import ScoreStore
    from llm_localizator.catalog.scores import score_matches_text
    score = ScoreStore(app.cfg.scores_dir or app.cfg.root / ".llm-scores").get(
        "pl", "app", "bye"
    )
    assert score is not None and score_matches_text(score, "Do widzenia")
    history = (app.cfg.history_dir or app.cfg.root / ".llm-history") / "pl.jsonl"
    assert '"trigger": "web-edit"' in history.read_text(encoding="utf-8")


def test_save_refreshes_the_source_hash(app) -> None:
    """`bye` was stale; saving must clear that, not leave it stale forever."""
    from llm_localizator.catalog import needs_translation

    save(app, "pl", "app", "bye", "Do widzenia")
    entry = StateStore(app.cfg.state_dir).entry("pl", "app", "bye")
    assert not needs_translation("Goodbye", entry)


def test_save_rejects_a_dropped_placeholder(app) -> None:
    """A human is held to the same rules as the model: a hand-typed string
    that loses {name} breaks the UI exactly as badly."""
    result = save(app, "pl", "app", "greet", "Witaj")
    assert result["ok"] is False
    assert "placeholder" in result["error"]
    assert app.catalog.load("pl", "app")["greet"] == "Witaj {name}", "must not write"


def test_save_rejects_an_unknown_key(app) -> None:
    result = save(app, "pl", "app", "nope", "x")
    assert result["ok"] is False
    assert "not in the source" in result["error"]


def test_save_rejects_path_like_locale_and_unknown_target(app) -> None:
    assert save(app, "../outside", "app", "bye", "Do widzenia")["ok"] is False
    assert save(app, "de", "app", "bye", "Auf Wiedersehen")["ok"] is False


def test_save_rejects_full_value_without_a_sibling(app) -> None:
    result = save(app, "pl", "app", "bye", "Do widzenia", full_value="longer")
    assert result["ok"] is False
    assert "fullKey" in result["error"]
    assert app.catalog.load("pl", "app")["bye"] == "Zegnaj"


def test_save_propagates_an_identical_source(app) -> None:
    en = app.catalog.load("en", "app")
    en["again"] = "Goodbye"
    app.catalog.save("en", "app", en)
    pl = app.catalog.load("pl", "app")
    pl.pop("again", None)
    app.catalog.save("pl", "app", pl)
    result = save(app, "pl", "app", "bye", "Do widzenia")
    assert result["ok"] is True
    assert app.catalog.load("pl", "app")["again"] == "Do widzenia"
    history = (app.cfg.history_root() / "pl.jsonl").read_text(encoding="utf-8")
    assert '"trigger": "propagated"' in history
    assert "app.bye" in history


def test_save_does_not_propagate_over_max_chars(tmp_path: Path) -> None:
    (tmp_path / ".llm-localize.toml").write_text(CONFIG + """
[prompt]
context_dir = "context"
""", encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {
        "bye": "Goodbye",
        "short": "Goodbye",
    })
    write_json(tmp_path / "messages" / "pl" / "app.json", {"bye": "Zegnaj"})
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "app.json").write_text(
        '{"short": {"maxChars": 3}}\n', encoding="utf-8",
    )
    state = build_state(load_config(tmp_path / ".llm-localize.toml"))
    assert save(state, "pl", "app", "bye", "Do widzenia")["ok"] is True
    assert state.catalog.load("pl", "app")["short"] == "Goodbye"
    history = state.cfg.history_root() / "pl.jsonl"
    assert '"trigger": "propagated"' not in history.read_text(encoding="utf-8")


def test_save_does_not_disturb_sibling_keys(app) -> None:
    before = app.catalog.load("pl", "app")
    save(app, "pl", "app", "bye", "Do widzenia")
    after = app.catalog.load("pl", "app")
    assert after["greet"] == before["greet"]
    assert after["same"] == before["same"]


def test_verify_key_under_lock(app) -> None:
    result = verify_key(app, "pl", "app", "greet", verify=True)
    assert result["ok"] is True
    assert result["verified"] is True
    entry = app.store.entry("pl", "app", "greet")
    assert entry.get("verified_at")
    hist = (app.cfg.history_root() / "pl.jsonl").read_text(encoding="utf-8")
    assert "web-verify" in hist


def test_save_prunes_nothing_from_the_source_key_set(app) -> None:
    save(app, "pl", "app", "bye", "Do widzenia")
    assert set(app.catalog.load("pl", "app")) == set(app.catalog.load("en", "app"))


def test_mark_example_appends_pair(tmp_path: Path) -> None:
    from llm_localizator.web import mark_example

    config = CONFIG + """
[prompt]
examples_file = "i18n/examples.json"
"""
    (tmp_path / ".llm-localize.toml").write_text(config, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {"greet": "Cześć"})
    st = build_state(load_config(tmp_path / ".llm-localize.toml"))
    result = mark_example(st, "pl", "app", "greet")
    assert result["ok"] and result["added"]
    data = json.loads((tmp_path / "i18n" / "examples.json").read_text(encoding="utf-8"))
    assert data["pl"] == [["Hello", "Cześć"]]


# ---- the page --------------------------------------------------------------

def _static(name: str) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / name).read_text(encoding="utf-8")


def test_page_is_self_contained(app) -> None:
    """No external requests: the tool must work with the machine offline."""
    from llm_localizator.web.shell import render_shell
    html = render_shell("editor")
    assert "<!DOCTYPE html>" in html
    for remote in ("http://", "https://", "cdn."):
        assert remote not in html
    for name in ("app.css", "shell.js", "editor.js", "ops.js", "dashboard.js"):
        text = _static(name)
        assert "http://" not in text
        assert "https://" not in text


def test_page_includes_ops_drawer() -> None:
    from llm_localizator.web.assets import WEB_FEATURES
    from llm_localizator.web.shell import render_shell
    html = render_shell("editor")
    ops = _static("ops.js")
    # ops-drawer was removed from the shell; the ops panel lives only inside
    # operations.js's own UI now.
    assert "Loading…" in html
    assert "text/event-stream" in ops
    assert "Select at least one locale" in ops
    assert "/api/ops/" in ops
    assert "payload.stream = true" in ops
    assert "ops" in WEB_FEATURES
    assert "ops_stream" in WEB_FEATURES


def test_editor_boot_shows_loading_and_errors() -> None:
    js = _static("editor.js")
    assert 'empty-state", "Loading…"' in js or "Loading…" in js
    assert "Select a project…" in js
    assert "overview-lite" in js
    assert "payload.ok === false" in js

def test_commands_manifest_matches_cli(app) -> None:
    from llm_localizator.cli.main import build_parser
    from llm_localizator.ops import build_commands_manifest

    manifest = build_commands_manifest(build_parser())
    assert "validate" in manifest["commands"]
    assert "status" in manifest["commands"]


def test_dispatch_ops_validate(app) -> None:
    from llm_localizator.ops import dispatch_op

    out = dispatch_op(app.cfg, "validate", {}, actor_role="Admin")
    assert out["command"] == "validate"
    assert "summary" in out


def test_history_for_key(app) -> None:
    from llm_localizator.web.server import history_for_key

    out = history_for_key(app, "pl", "app", "greet")
    assert "events" in out
    assert out.get("retention", 0) > 0


def test_history_exposes_candidates_and_tm_hit(app) -> None:
    from llm_localizator.catalog.history import HistoryStore, make_history_event
    from llm_localizator.web.server import history_for_key

    hist = HistoryStore(app.cfg.history_root())
    hist.append(
        "pl",
        make_history_event(
            namespace="app", key="greet", prev=None, next_text="Witaj",
            model="secondary", status="machine", src_sha="abc",
            trigger="tm-hit", quality_score=0.95, provider="ollama",
            candidates=[
                {"model": "primary", "score": 0.4, "provider": "ollama"},
                {"model": "secondary", "score": 0.95, "provider": "ollama"},
            ],
        ),
    )
    out = history_for_key(app, "pl", "app", "greet")
    assert out["events"]
    top = out["events"][0]
    assert top["trigger"] == "tm-hit"
    assert top["provider"] == "ollama"
    assert top["candidates"] is not None
    assert len(top["candidates"]) == 2
    assert top["candidates"][1]["model"] == "secondary"


def test_history_carries_the_old_and_new_source_for_a_stale_key(app) -> None:
    from llm_localizator.catalog.history import HistoryStore, make_history_event
    from llm_localizator.web.server import history_for_key

    HistoryStore(app.cfg.history_root()).append(
        "pl",
        make_history_event(
            namespace="app", key="greet", prev="Witaj", next_text="Witaj ponownie",
            model="m", status="machine", src_sha="abc", trigger="translate",
            prev_src="Hello", next_src="Hello again",
        ),
    )
    top = history_for_key(app, "pl", "app", "greet")["events"][0]
    assert (top["prevSource"], top["nextSource"]) == ("Hello", "Hello again")


def test_revert_key_restores_previous_text(app) -> None:
    from llm_localizator.web.server import revert_key, save

    save(app, "pl", "app", "bye", "Do widzenia")
    result = revert_key(app, "pl", "app", "bye", to_text="Pa")
    assert result["ok"] is True
    assert app.catalog.load("pl", "app")["bye"] == "Pa"
    history = (app.cfg.history_dir or app.cfg.root / ".llm-history") / "pl.jsonl"
    assert '"trigger": "web-revert"' in history.read_text(encoding="utf-8")


def test_save_context_llm_note(app) -> None:
    from llm_localizator.web.server import save_context

    (app.cfg.root / "i18n" / "context").mkdir(parents=True, exist_ok=True)
    app.cfg.context_dir = app.cfg.root / "i18n" / "context"
    result = save_context(app, "app", "greet", llm_note="shorter please")
    assert result["ok"] is True


def test_save_context_human_note_and_max_chars(app) -> None:
    from llm_localizator.projects.context import ContextNotes
    from llm_localizator.web.server import save_context

    (app.cfg.root / "i18n" / "context").mkdir(parents=True, exist_ok=True)
    app.cfg.context_dir = app.cfg.root / "i18n" / "context"
    assert save_context(app, "app", "greet", note="button label", max_chars=24)["ok"]
    notes = ContextNotes(app.cfg.context_dir)
    assert notes.note("app", "greet") == "button label"
    assert notes.max_chars("app", "greet") == 24


def test_overview_has_context_when_configured(app) -> None:
    (app.cfg.root / "i18n" / "context").mkdir(parents=True, exist_ok=True)
    app.cfg.context_dir = app.cfg.root / "i18n" / "context"
    assert overview(app)["hasContext"] is True


def test_page_editable_context_fields() -> None:
    editor = _static("editor.js")
    assert "/api/context" in editor
    assert "Context note" in editor


def test_page_ops_export_tab() -> None:
    ops = _static("ops.js")
    assert "ops-format" in ops
    assert "ops-layout" in ops
    assert "ops-file-count" in ops
    assert "ops-import-files" in ops


def test_page_validate_write_flags_option() -> None:
    from llm_localizator.cli.main import build_parser
    from llm_localizator.ops.manifest import build_commands_manifest
    fields = build_commands_manifest(build_parser())["commands"]["validate"]["fields"]
    assert any(field["name"] == "write_flags" for field in fields)


def test_page_uses_row_ns_helper() -> None:
    editor = _static("editor.js")
    assert "row.namespace" in editor


def test_dispatch_ops_status(app) -> None:
    from llm_localizator.ops import dispatch_op

    out = dispatch_op(app.cfg, "status", {}, actor_role="Admin")
    assert out["command"] == "status"
    assert "locales" in out["data"]


def test_save_refuses_all_namespaces(app) -> None:
    before = app.catalog.load("pl", "app").get("bye")
    result = save(app, "pl", "__all__", "bye", "Nope")
    assert result["ok"] is False
    assert result["error"] == "cannot write with namespace='__all__'"
    assert app.catalog.load("pl", "app").get("bye") == before


def test_save_appends_history_after_state(app) -> None:
    from unittest.mock import patch

    from llm_localizator.catalog.history import HistoryStore

    seen = {}
    real = HistoryStore.append

    def wrapped(self, locale, event):
        assert app.catalog.load("pl", "app")["bye"] == "Do widzenia"
        raw = (Path(app.cfg.state_dir) / "pl.json").read_text(encoding="utf-8")
        assert "app.bye" in raw
        seen["ok"] = True
        return real(self, locale, event)

    with patch.object(HistoryStore, "append", wrapped):
        assert save(app, "pl", "app", "bye", "Do widzenia")["ok"] is True
    assert seen["ok"] is True


def test_page_has_translate_key_action() -> None:
    editor = _static("editor.js")
    assert "translateBody" in editor
    assert "/api/ops/translate" in editor


def test_translate_key_body_reaches_op(app, monkeypatch) -> None:
    from llm_localizator.ops import dispatch_op
    from llm_localizator.ops.types import OpResult

    seen = {}

    def fake(cfg, req, report=None):
        seen["keys"] = list(req.keys or [])
        return OpResult(ok=True, exit_code=0, command="translate", summary="queued")

    # No tq: default operator path still reaches op_translate (local fallback).
    monkeypatch.setattr("llm_localizator.projects.taskqueue.tq_available", lambda: False)
    monkeypatch.setattr("llm_localizator.ops.dispatch_cmds.op_translate", fake)
    out = dispatch_op(app.cfg, "translate", {"locales": ["pl"], "keys": ["app.greet"]}, actor_role="Admin")
    assert out["ok"] is True
    assert seen["keys"] == ["app.greet"]


def test_web_save_learns_only_from_human_edits(app) -> None:
    from llm_localizator.projects.context import load_examples
    from llm_localizator.web.server import save

    app.cfg.examples_file = app.cfg.root / "examples.json"
    first = save(app, "pl", "app", "bye", "Do widzenia zatem")
    assert first["ok"]
    assert "pl" in load_examples(app.cfg.examples_file)

    src = app.catalog.load(app.cfg.source_locale, "app")["bye"]
    assert load_examples(app.cfg.examples_file)["pl"][0][0] == src
    imported = save(app, "pl", "app", "bye", "Jeszcze coś innego tu", provider="import")
    assert imported["ok"] and len(load_examples(app.cfg.examples_file)["pl"]) == 1


def test_history_endpoint_serves_the_source_change_log(app) -> None:
    from llm_localizator.catalog.source_history import SourceHistory
    from llm_localizator.web.server import history_for_key

    assert history_for_key(app, "pl", "app", "greet")["sourceChange"] is None
    SourceHistory(app.cfg.state_root()).record_changes([("app", "greet", "Hi {name}", "Hello {name}")])
    change = history_for_key(app, "pl", "app", "greet")["sourceChange"]
    assert (change["prev_src"], change["next_src"]) == ("Hi {name}", "Hello {name}")


def test_stale_row_carries_the_source_change(app) -> None:
    from llm_localizator.catalog.source_history import SourceHistory

    SourceHistory(app.cfg.state_root()).record_changes([("app", "bye", "OLD SOURCE", "Goodbye")])
    stale = message_row(app, ["pl"], "app", "bye")["row"]
    assert stale["sourceChange"]["prev_src"] == "OLD SOURCE"
    fresh = message_row(app, ["pl"], "app", "greet")["row"]
    assert "sourceChange" not in fresh


def test_editor_script_labels_every_quality_dimension() -> None:
    js = (Path(__file__).parent.parent / "llm_localizator" / "web" / "static" / "editor.js").read_text(encoding="utf-8")
    for name in ("placeholder_ok", "glossary_ok", "fluency", "bt_overlap", "length"):
        assert name + ":" in js


def test_validate_key_carries_the_docs_url_and_editor_links_codes(app) -> None:
    from llm_localizator.web.server import validate_key
    assert validate_key(app, "pl", "app", "greet", "Witaj")["docsUrl"] == ""
    app.cfg.docs_url = "https://docs.example.test/docs"
    assert validate_key(app, "pl", "app", "greet", "Witaj")["docsUrl"] == "https://docs.example.test/docs"
    assert '"checks.md#"' in _static("editor.js")


def test_docs_checks_has_an_anchor_per_code() -> None:
    text = (Path(__file__).parent.parent / "docs" / "checks.md").read_text(encoding="utf-8")
    for code in ("V01", "V04", "V13", "V98", "V99"):
        assert f'<a id="{code.lower()}"></a>{code}' in text
