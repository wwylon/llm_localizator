"""A failed read must never be turned into an empty store that is then saved."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.catalog.budget import BudgetStore
from llm_localizator.catalog.pricing import estimate_tokens


def test_multilang_save_refuses_to_overwrite_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "glossary.json"
    path.write_text('{"terms": {"trick": {"pl": "lewa"', encoding="utf-8")  # truncated
    cat = build_catalog("multilang-json", tmp_path, "glossary.json")
    with pytest.raises(json.JSONDecodeError):
        cat.save("de", None, {"trick": "Stich"})
    assert path.read_text(encoding="utf-8").startswith('{"terms"')  # untouched


def test_budget_record_refuses_to_reset_corrupt_ledger(tmp_path: Path) -> None:
    store = BudgetStore(tmp_path)
    store.record(1.0, locale="pl", model="m")
    store.path.write_text("{not json", encoding="utf-8")
    assert store.month_total() == 0.0  # readers stay tolerant
    with pytest.raises(RuntimeError, match="unreadable"):
        store.record(0.5, locale="pl", model="m")
    assert store.path.read_text(encoding="utf-8") == "{not json"


def test_po_continuation_line_keeps_trailing_quote(tmp_path: Path) -> None:
    po = tmp_path / "locale" / "pl" / "app.po"
    po.parent.mkdir(parents=True)
    po.write_text(
        'msgid "say"\nmsgstr ""\n"he said \\"\\""\n',
        encoding="utf-8",
    )
    cat = build_catalog("po", tmp_path, "locale/{locale}/{namespace}.po", "en")
    assert cat.load("pl", "app")["say"] == 'he said ""'


def test_estimate_tokens_accepts_underscore_locale() -> None:
    assert estimate_tokens(1000, "zh_CN") == estimate_tokens(1000, "zh")


def test_apply_gap_fill_skips_namespace_when_catalogue_unreadable(monkeypatch) -> None:
    from llm_localizator.ops import apply as apply_mod

    saved: list[tuple] = []

    class FakeCat:
        def load(self, locale, ns):
            raise OSError("transient")

        def save(self, locale, ns, msgs):
            saved.append((locale, ns, msgs))

    monkeypatch.setattr(apply_mod, "catalog_for", lambda *a, **k: FakeCat())
    cfg = SimpleNamespace(
        catalog_format="json", root=Path("."), catalog_path="x", source_locale="en"
    )
    gaps = [{"namespace": "app", "locale": "pl", "key": "k", "source_text": "hi"}]
    written, log = apply_mod._apply_catalogue_gaps(cfg, gaps, dry_run=False)
    assert saved == []
    assert written == 0
    assert any("skip" in line for line in log)


def test_append_text_line_closes_torn_last_line(tmp_path: Path) -> None:
    from llm_localizator.catalog.io import append_text_line

    path = tmp_path / "log.jsonl"
    path.write_bytes(b'{"a": 1}\n{"b": ')  # crash mid-append
    append_text_line(path, '{"c": 3}')
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"a": 1}'
    assert lines[-1] == '{"c": 3}'  # not glued onto the torn row
    assert json.loads(lines[-1]) == {"c": 3}


def test_tm_export_outside_project_denied_for_non_admin(tmp_path: Path) -> None:
    from llm_localizator.ops.dispatch import _escaping_path

    data = tmp_path / "engine-data"
    cfg = SimpleNamespace(root=tmp_path, data_root=lambda: data)
    outside = str(tmp_path.parent / "evil.tmx")
    assert outside in _escaping_path(cfg, "tm_export", {"path": outside}, "Translator")
    assert _escaping_path(cfg, "tm_export", {"path": "../x.tmx"}, "Supervisor")
    # Inside the repo is not enough for a file the op overwrites: it could be the config or source (M0).
    assert _escaping_path(cfg, "tm_export", {"path": ".llm-localize.toml"}, "Translator")
    assert _escaping_path(cfg, "tm_export", {"path": str(data / "exports" / "x.tmx")}, "Translator") == ""
    assert _escaping_path(cfg, "tm_export", {"path": outside}, "Admin") == ""
    # Imports still read from inside the project.
    assert _escaping_path(cfg, "tm_import", {"path": "in/x.tmx"}, "Translator") == ""


def test_host_allowlist_rejects_rebinding_names() -> None:
    from llm_localizator.web.server_logic import _host_allowed

    assert _host_allowed("127.0.0.1:8765") and _host_allowed("localhost") and _host_allowed("[::1]:80")
    assert not _host_allowed("evil.example.com")
    assert not _host_allowed("127.0.0.1.evil.com:80")
    assert not _host_allowed("localhost.evil.com")


def test_printf_placeholder_multiplicity_is_checked() -> None:
    from llm_localizator.core.standards import get_standard
    from llm_localizator.core.validate import validate_translation

    std = get_standard("printf")
    ok, reason = validate_translation("%s of %s", "%s z", "pl", {}, standard=std)
    assert not ok and "count" in reason
    ok, _ = validate_translation("%s of %s", "%s z %s", "pl", {}, standard=std)
    assert ok


def test_score_only_resume_exits_zero() -> None:
    from llm_localizator.pipeline.translate import TranslationResult

    assert TranslationResult(total=3, written=0, score_only=True).exit_code == 0
    assert TranslationResult(total=3, written=0).exit_code == 1


def test_rescore_batches_never_mix_locales() -> None:
    from llm_localizator.pipeline.scoring import PendingScoreItem, _locale_batches

    def item(loc: str, k: str) -> PendingScoreItem:
        return PendingScoreItem(loc, "ns", k, "src", "tr")

    items = [item("pl", "a"), item("pl", "b"), item("de", "c"), item("de", "d"), item("de", "e")]
    batches = _locale_batches(items, 2)
    assert [(s, [i.key for i in b]) for s, b in batches] == [
        (0, ["a", "b"]), (2, ["c", "d"]), (4, ["e"]),
    ]


def test_scan_skip_ignores_dirs_above_project_root(tmp_path: Path) -> None:
    from llm_localizator.scan.base import path_is_skipped

    root = tmp_path / "docs" / "myapp"
    f = root / "src" / "ui.py"
    assert path_is_skipped(f)  # legacy behaviour: absolute path judged whole
    assert not path_is_skipped(f, root=root)
    assert path_is_skipped(root / "docs" / "guide.py", root=root)


def test_history_tolerates_non_object_lines(tmp_path) -> None:
    from llm_localizator.catalog.history import HistoryStore, make_history_event

    store = HistoryStore(tmp_path)
    store.append("pl", make_history_event(
        namespace="n", key="k", prev=None, next_text="x", model="m", status="machine",
        src_sha="s", trigger="t",
    ))
    with store.path_for("pl").open("a", encoding="utf-8") as fh:
        fh.write("[1, 2]\n\"str\"\n")
    assert len(store.events_for("pl", "n", "k")) == 1
    store.compact("pl")
    assert len(store.events_for("pl", "n", "k")) == 1


def test_other_path_ops_are_confined_for_non_admin(tmp_path: Path) -> None:
    from llm_localizator.ops.dispatch import _escaping_path

    data = tmp_path / "engine-data"
    cfg = SimpleNamespace(root=tmp_path, data_root=lambda: data)
    outside = str(tmp_path.parent / "evil")
    for cmd, key in (("glossary_import", "file"), ("bakeoff", "out"), ("scan", "out_dir"), ("patch", "outDir")):
        assert _escaping_path(cfg, cmd, {key: outside}, "Translator") == outside, cmd
        assert _escaping_path(cfg, cmd, {key: "inside/x"}, "Translator") == "", cmd
    # Ops that overwrite the named file: only the engine's exports folder (M0).
    for cmd, key in (("glossary_export", "file"), ("glossary_propose", "out")):
        assert outside in _escaping_path(cfg, cmd, {key: outside}, "Translator"), cmd
        assert _escaping_path(cfg, cmd, {key: "inside/x"}, "Translator"), cmd
        assert _escaping_path(cfg, cmd, {key: str(data / "exports" / "g.csv")}, "Translator") == "", cmd
