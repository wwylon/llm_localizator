"""agent-hardcoded is a report. It does not call a model unless asked."""

from __future__ import annotations

from llm_localizator.ops.agent_hardcoded import op_agent_hardcoded
from llm_localizator.ops.types import AgentHardcodedRequest


def _project(tmp_path, make_config):
    app = tmp_path / "app"
    app.mkdir()
    (app / "Page.tsx").write_text(
        "<button>Sign in now</button>\n<button>{t('signIn')}</button>\n",
        encoding="utf-8",
    )
    return make_config(tmp_path, scan_adapter="next-intl", scan_src_dirs=["app"])


def test_report_includes_the_sentence_and_path(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    result = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    blob = "\n".join(result.lines)
    assert result.exit_code == 0
    assert "Sign in now" in blob
    assert "app/Page.tsx" in blob
    assert all(hit["text"] != "signIn" for hit in result.data["hits"])


def test_default_path_never_builds_a_provider(tmp_path, make_config, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("provider constructed")

    monkeypatch.setattr("llm_localizator.providers.build_provider", boom)
    cfg = _project(tmp_path, make_config)
    result = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert result.exit_code == 0
    assert result.data["hits"]


def test_llm_can_add_a_hit_and_dry_run_does_not_call_it(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    calls: list[int] = []

    class Fake:
        def complete(self, request):
            calls.append(1)
            return '[{"text": "Open the roster", "line": 1, "reason": "heading"}]'

    dry = op_agent_hardcoded(
        cfg, AgentHardcodedRequest(llm=True, dry_run=True), provider=Fake(),
    )
    assert calls == []
    assert dry.data["dryRun"] is True
    assert "app/Page.tsx" in dry.data["files"]

    result = op_agent_hardcoded(
        cfg, AgentHardcodedRequest(llm=True), provider=Fake(),
    )
    assert calls == [1]
    assert any(
        hit["source"] == "llm" and hit["text"] == "Open the roster"
        for hit in result.data["hits"]
    )


def test_missing_adapter_exits_64(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path, scan_adapter=None, scan_src_dirs=[])
    result = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert result.exit_code == 64


def test_parse_llm_reports_a_non_list(tmp_path, make_config) -> None:
    from llm_localizator.ops.agent_hardcoded import _parse_llm

    items, err = _parse_llm('{"text": "nope"}')
    assert items == []
    assert err and "not a list" in err
    items, err = _parse_llm('[{"text": "Open", "line": 1}]')
    assert err is None
    assert items[0]["text"] == "Open"


def test_llm_prompt_json_escapes_the_path(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    seen: list[str] = []

    class Fake:
        def complete(self, request):
            seen.append(request.prompt)
            return "[]"

    op_agent_hardcoded(cfg, AgentHardcodedRequest(llm=True), provider=Fake())
    assert seen
    assert '"app/Page.tsx"' in seen[0]


def test_path_hint_skips_underscore_when_template_has_no_namespace(tmp_path, make_config) -> None:
    from llm_localizator.ops.agent_backlog import _catalog_path_hint

    cfg = make_config(tmp_path, catalog_path="messages/{locale}.json")
    assert _catalog_path_hint(cfg, "pl", "app") == "messages/pl.json"


def test_existing_key_annotated_in_report(tmp_path, make_config) -> None:
    """When a scanned literal already exists in the source catalogue, the report
    should cite the existing key instead of treating it as a missing translation."""
    import json

    app = tmp_path / "app"
    app.mkdir()
    (app / "Page.tsx").write_text(
        "<button>Sign in now</button>\n", encoding="utf-8",
    )
    # Write a source catalogue entry so the reverse lookup can find it.
    cat_dir = tmp_path / "messages" / "en"
    cat_dir.mkdir(parents=True)
    (cat_dir / "auth.json").write_text(
        json.dumps({"signIn": "Sign in now"}), encoding="utf-8",
    )
    cfg = make_config(tmp_path, scan_adapter="next-intl", scan_src_dirs=["app"])
    result = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert result.exit_code == 0
    hits = result.data["hits"]
    matched = [h for h in hits if h["text"] == "Sign in now"]
    assert matched, "expected 'Sign in now' in hits"
    assert matched[0]["existing_key"] == "auth.signIn"
    blob = "\n".join(result.lines)
    assert "already at" in blob
    assert "auth.signIn" in blob


def test_literal_languages_are_reported_too(tmp_path, make_config) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.go").write_text('package main\nvar s = "Please sign in now"\n', encoding="utf-8")
    (tmp_path / "app" / "Labels.ts").write_text('const L = { SAVE: "Save" };\n', encoding="utf-8")
    cfg = make_config(tmp_path, scan_adapter="next-intl", scan_src_dirs=["app"])
    # Low literals are hidden from the default report; ask for them.
    req = AgentHardcodedRequest(show_low=True)
    hits = {h["text"]: h for h in op_agent_hardcoded(cfg, req).data["hits"]}
    assert hits["Please sign in now"]["confidence"] == "low"
    assert hits["Save"]["confidence"] == "medium"


def test_second_run_uses_the_cache_until_a_file_changes(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    first = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert first.data["cachedAt"] is None
    second = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert second.data["cachedAt"] is not None
    assert second.data["hits"] == first.data["hits"]
    page = tmp_path / "app" / "Page.tsx"
    page.write_text("<button>Sign in now</button>\n<button>Log out today</button>\n", encoding="utf-8")
    third = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert third.data["cachedAt"] is None
    assert any(h["text"] == "Log out today" for h in third.data["hits"])


def test_refresh_bypasses_the_cache_and_llm_never_caches(tmp_path, make_config) -> None:
    cfg = _project(tmp_path, make_config)
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert op_agent_hardcoded(cfg, AgentHardcodedRequest(refresh=True)).data["cachedAt"] is None

    class Fake:
        def complete(self, request):
            return "[]"

    cache = cfg.state_root() / "scan_cache.json"
    cache.unlink()
    op_agent_hardcoded(cfg, AgentHardcodedRequest(llm=True), provider=Fake())
    assert not cache.exists()


def test_scan_cache_status_reports_stale_after_an_edit(tmp_path, make_config) -> None:
    from llm_localizator.ops.agent_hardcoded import scan_cache_status

    cfg = _project(tmp_path, make_config)
    assert scan_cache_status(cfg)["cached"] is False
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    status = scan_cache_status(cfg)
    assert status["cached"] and not status["stale"] and status["total"] >= 1
    (tmp_path / "app" / "Page.tsx").write_text("<b>Changed text here</b>\n", encoding="utf-8")
    assert scan_cache_status(cfg)["stale"] is True


def _two_file_project(tmp_path, make_config):
    cfg = _project(tmp_path, make_config)
    (tmp_path / "app" / "Other.tsx").write_text(
        "<h1>Welcome back friend</h1>\n", encoding="utf-8",
    )
    return cfg


def _texts(result) -> set[str]:
    return {hit["text"] for hit in result.data["hits"]}


def test_edit_rescans_only_the_changed_file(tmp_path, make_config, monkeypatch) -> None:
    cfg = _two_file_project(tmp_path, make_config)
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    page = tmp_path / "app" / "Page.tsx"
    page.write_text("<button>Log out now</button>\n", encoding="utf-8")

    from llm_localizator.scan import next_intl

    scanned: list[str] = []
    real = next_intl.NextIntlScanner.scan_file

    def spy(self, path, lines, result):
        scanned.append(path.name)
        return real(self, path, lines, result)

    monkeypatch.setattr(next_intl.NextIntlScanner, "scan_file", spy)
    result = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert scanned == ["Page.tsx"]
    assert _texts(result) == {"Log out now", "Welcome back friend"}


def test_incremental_result_equals_a_cold_scan(tmp_path, make_config) -> None:
    cfg = _two_file_project(tmp_path, make_config)
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    (tmp_path / "app" / "Other.tsx").write_text("<h1>Goodbye for now</h1>\n", encoding="utf-8")
    (tmp_path / "app" / "New.tsx").write_text("<p>Brand new paragraph</p>\n", encoding="utf-8")
    warm = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    cold = op_agent_hardcoded(cfg, AgentHardcodedRequest(refresh=True))
    assert warm.data["hits"] == cold.data["hits"]


def test_cache_stores_each_hit_once_and_reloads_it(tmp_path, make_config) -> None:
    """M4: hits live under their file only; an unchanged second run rebuilds the same list from them."""
    import json

    cfg = _two_file_project(tmp_path, make_config)
    first = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    stored = json.loads((cfg.state_root() / "scan_cache.json").read_text(encoding="utf-8"))
    assert "hits" not in stored and stored["order"]
    again = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert again.data["hits"] == first.data["hits"]
    # A limited run saw one file: the per-file cache keeps the other (M4: it used to be pruned).
    op_agent_hardcoded(cfg, AgentHardcodedRequest(limit=1))
    stored = json.loads((cfg.state_root() / "scan_cache.json").read_text(encoding="utf-8"))
    assert len(stored["files"]) == 2


def test_status_memo_is_opt_in_and_follows_the_cache_file(tmp_path, make_config, monkeypatch) -> None:
    from llm_localizator.ops import agent_hardcoded as ah

    cfg = _two_file_project(tmp_path, make_config)
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    calls = []
    real = ah._fingerprint
    monkeypatch.setattr(ah, "_fingerprint", lambda *a, **k: calls.append(1) or real(*a, **k))
    ah._STATUS_MEMO.clear()
    ah.scan_cache_status(cfg, max_age=60)
    ah.scan_cache_status(cfg, max_age=60)
    assert len(calls) == 1          # the second poll reused the answer
    ah.scan_cache_status(cfg)
    assert len(calls) == 2          # the default never reuses
    op_agent_hardcoded(cfg, AgentHardcodedRequest(refresh=True))   # rewrites the cache file
    ah.scan_cache_status(cfg, max_age=60)
    assert len(calls) >= 3


def test_deleted_file_drops_out_of_the_cache(tmp_path, make_config) -> None:
    import json

    cfg = _two_file_project(tmp_path, make_config)
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    (tmp_path / "app" / "Other.tsx").unlink()
    result = op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert "Welcome back friend" not in _texts(result)
    stored = json.loads((cfg.state_root() / "scan_cache.json").read_text(encoding="utf-8"))
    assert not any(name.endswith("Other.tsx") for name in stored["files"])


def test_changed_scan_settings_discard_per_file_hits(tmp_path, make_config, monkeypatch) -> None:
    cfg = _two_file_project(tmp_path, make_config)
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    from llm_localizator.ops import agent_hardcoded as mod

    monkeypatch.setattr(mod, "_SCAN_VERSION", mod._SCAN_VERSION + 1)
    from llm_localizator.scan import next_intl

    scanned: list[str] = []
    real = next_intl.NextIntlScanner.scan_file
    monkeypatch.setattr(
        next_intl.NextIntlScanner, "scan_file",
        lambda self, p, l, r: (scanned.append(p.name), real(self, p, l, r))[1],
    )
    op_agent_hardcoded(cfg, AgentHardcodedRequest())
    assert sorted(scanned) == ["Other.tsx", "Page.tsx"]
