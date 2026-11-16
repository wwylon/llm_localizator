"""Plan-review-7 phase 2: lock re-entrancy, sticky intentional, trims, plural operands."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from llm_localizator.catalog import translator_activity as ta
from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.mutation_lock import MutationLockTimeout, mutation_lock
from llm_localizator.catalog.scores import ScoreStore
from llm_localizator.catalog.source_history import SourceHistory
from llm_localizator.catalog.state import StateStore
from llm_localizator.core.plural import plural_operands
from llm_localizator.pipeline.recording import record_candidate


def test_mutation_lock_is_reentrant_in_thread(tmp_path: Path) -> None:
    lock = tmp_path / ".mutation.lock"
    with mutation_lock(lock, timeout_s=1):
        with mutation_lock(lock, timeout_s=1):  # would time out if not re-entrant
            pass
        # still held after the inner exit: another thread cannot take it
        got: list[bool] = []

        def other() -> None:
            try:
                with mutation_lock(lock, timeout_s=0.2):
                    got.append(True)
            except MutationLockTimeout:
                got.append(False)

        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert got == [False]
    with mutation_lock(lock, timeout_s=1):
        pass


def test_tm_import_under_held_lock_does_not_deadlock(tmp_path: Path, make_config) -> None:
    from llm_localizator.catalog.mutation_lock import project_mutation_lock
    from llm_localizator.ops.tm import op_tm_import
    from llm_localizator.ops.types import TmImportRequest

    cfg = make_config(tmp_path)
    tmx = '<?xml version="1.0"?><tmx version="1.4"><header srclang="en"/><body></body></tmx>'
    with project_mutation_lock(cfg, timeout_s=1):
        res = op_tm_import(cfg, TmImportRequest(locale="pl", tmx=tmx))
    assert res.command == "tm-import"


def test_add_locale_takes_lock(tmp_path: Path, make_config, monkeypatch) -> None:
    from llm_localizator.ops import add_locale as al_mod
    from llm_localizator.ops import glossary as gl_mod
    from llm_localizator.ops import push_strings as ps_mod
    from llm_localizator.ops import tm as tm_mod

    for mod in (al_mod, gl_mod, tm_mod, ps_mod):
        assert hasattr(mod, "project_mutation_lock"), mod.__name__

    cfg_path = tmp_path / ".llm-localize.toml"
    cfg_path.write_text('[locales]\ntargets = ["pl"]\n', encoding="utf-8")
    cfg = make_config(tmp_path, config_path=cfg_path)
    calls: list[str] = []
    real = al_mod.project_mutation_lock

    def spy(c, **kw):
        calls.append("lock")
        return real(c, **kw)

    monkeypatch.setattr(al_mod, "project_mutation_lock", spy)
    assert al_mod.add_locale(cfg, "de")["ok"]
    assert calls == ["lock"]


def _record(state, scores, history, *, source, text, status="machine"):
    return record_candidate(
        state=state, scores=scores, history=history,
        locale="pl", namespace="app", key="k", source=source,
        previous=None, text=text, model="m", quality_score=0.9,
        quality_signals=[], trigger="translate", status=status,
    )


def test_intentional_survives_machine_overwrite_until_source_changes(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "s")
    scores = ScoreStore(tmp_path / "sc")
    history = HistoryStore(tmp_path / "h")
    _record(state, scores, history, source="OK", text="OK", status="intentional")
    entry = _record(state, scores, history, source="OK", text="OK")
    assert entry["status"] == "intentional"
    entry = _record(state, scores, history, source="OK changed", text="Zmienione")
    assert entry["status"] == "machine"


def test_human_edit_replaces_intentional(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "s")
    scores = ScoreStore(tmp_path / "sc")
    history = HistoryStore(tmp_path / "h")
    _record(state, scores, history, source="OK", text="OK", status="intentional")
    entry = _record(state, scores, history, source="OK", text="Dobrze", status="human")
    assert entry["status"] == "human"


def test_cli_lock_timeout_is_clean_exit_1(monkeypatch, capsys) -> None:
    import llm_localizator.cli.cmd_validate as cv
    import importlib

    cli_main = importlib.import_module("llm_localizator.cli.main")

    def boom(args):
        raise MutationLockTimeout("timed out after 600s waiting for x")

    monkeypatch.setattr(cv, "run", boom)
    rc = cli_main.main(["validate"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "mutation lock" in err


def test_diff_scope_tty_stdin_is_error(monkeypatch) -> None:
    import sys

    from llm_localizator.cli import cmd_validate

    class Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty())
    with pytest.raises(ValueError, match="terminal"):
        cmd_validate._diff_scope([])


def test_diff_scope_empty_pipe_means_nothing_changed(monkeypatch, tmp_path: Path, make_config, capsys) -> None:
    import argparse
    import io
    import sys

    from llm_localizator.cli import cmd_validate

    cfg = make_config(tmp_path)
    monkeypatch.setattr(cmd_validate, "resolve", lambda *a, **k: cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    args = argparse.Namespace(project=None, config=None, diff_scope=[], locales=None,
                              namespace=None, strict=False, check_expansion=False,
                              flag_checks=None, fmt="text", quiet=True)
    assert cmd_validate.run(args) == 0  # a CI run with no changed files passes


def test_pipeline_validate_empty_changed_files_checks_nothing(tmp_path: Path, make_config) -> None:
    from llm_localizator.catalog import build_catalog
    from llm_localizator.pipeline.validate import run_validation

    cfg = make_config(tmp_path)
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    report = run_validation(cfg, catalog, changed_files=set())
    assert report.scope_error is None and not report.findings


@pytest.mark.parametrize("n,expected", [
    (1e-7, (0, 7)), (1.5e-07, (0, 8)), (1.0, (1, 0)), (2.5, (2, 1)),
    (1e20, (10 ** 20, 0)), (-3.25, (3, 2)), (0.0, (0, 0)),
])
def test_plural_operands_exponent(n, expected) -> None:
    assert plural_operands(n) == expected


def test_source_history_appends_and_skips_rewrite(tmp_path: Path) -> None:
    hist = SourceHistory(tmp_path)
    assert hist.record_changes([("app", "k", "old", "new")]) == 1
    before = hist.path.read_bytes()
    assert hist.record_changes([("app", "k", "old", "new")]) == 0
    assert hist.path.read_bytes() == before
    assert hist.record_changes([("app", "k", "new", "newer")]) == 1
    assert hist.path.read_bytes().startswith(before)
    assert len(hist.path.read_text().splitlines()) == 2


def test_activity_trim_only_past_threshold(tmp_path: Path, monkeypatch) -> None:
    reads: list[Path] = []
    real = Path.read_text

    def spy(self, *a, **k):
        reads.append(self)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    monkeypatch.setattr(ta, "_TRIM_EVERY", 1)
    for i in range(20):
        ta.append_activity(tmp_path, user_id="u", username="u", locale="pl",
                           namespace="app", key=f"k{i}", trigger="save", retention=1000)
    assert not [p for p in reads if p.name == ta.ACTIVITY_NAME]

    for i in range(30):
        ta.append_activity(tmp_path, user_id="u", username="u", locale="pl",
                           namespace="app", key=f"z{i}", trigger="save", retention=10)
    lines = real(tmp_path / ta.ACTIVITY_NAME, encoding="utf-8").splitlines()
    assert len(lines) <= 10 + 1
    assert json.loads(lines[-1])["key"] == "z29"


def test_history_iter_events_public_and_alias(tmp_path: Path) -> None:
    h = HistoryStore(tmp_path)
    assert list(h.iter_events("pl")) == []
    assert list(h._iter_events("pl")) == []
