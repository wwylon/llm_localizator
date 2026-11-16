"""cycle: one pass, one report, no consumer writes (P5, ADR-126)."""

from __future__ import annotations

import json

from llm_localizator.ops.cycle import op_cycle
from llm_localizator.ops.set_translation import op_set


def test_cycle_writes_one_report(tmp_path, make_config) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps({"a.save": "Save", "a.open": "Open"}),
                                                  encoding="utf-8")
    (tmp_path / "locales" / "pl.json").write_text("{}", encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "app.js").write_text("i18n.t('a.save'); i18n.t('a.open');\n", encoding="utf-8")
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                      targets=["pl"], scan_src_dirs=["web"], state_dir=tmp_path / ".state")
    op_set(cfg, locale="pl", key="a.save", text="Zapisz")
    before = (tmp_path / "locales" / "pl.json").read_text(encoding="utf-8")
    result = op_cycle(cfg)
    assert result.data["status"]["pl"]["pending"] == 1
    assert result.data["check_keys"]["ok"] is True
    report = result.data["report"]
    text = open(report, encoding="utf-8").read()
    for heading in ("## 1. Keys", "## 2. Validate", "## 3. Translation status", "## 4. Review first",
                    "## 5. Hardcoded text"):
        assert heading in text
    assert "--translate" in text  # due strings are not queued without the flag
    assert (tmp_path / "locales" / "pl.json").read_text(encoding="utf-8") == before


def test_cycle_repair_queues_only_failing_keys(tmp_path, make_config, monkeypatch) -> None:
    from llm_localizator.ops import translate as translate_mod
    from llm_localizator.ops.types import OpResult

    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps({"a.save": "Save", "a.open": "Open"}),
                                                  encoding="utf-8")
    (tmp_path / "locales" / "pl.json").write_text(
        json.dumps({"a.save": "\u201eZapisz\u201d", "a.open": "Otw\u00f3rz"}), encoding="utf-8")
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                      targets=["pl"], state_dir=tmp_path / ".state")
    calls = []

    def fake(cfg_, req, **_kw):
        calls.append(req)
        return OpResult(ok=True, exit_code=0, command="translate", summary="queued")

    monkeypatch.setattr(translate_mod, "op_translate", fake)
    hint = op_cycle(cfg)
    assert not calls and "--repair" in open(hint.data["report"], encoding="utf-8").read()
    op_cycle(cfg, repair=True)
    assert len(calls) == 1 and calls[0].keys == ["a.save"] and calls[0].force and calls[0].submit


def _repair_project(tmp_path, make_config):
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps({"a.save": "Save", "a.open": "Open"}),
                                                  encoding="utf-8")
    (tmp_path / "locales" / "pl.json").write_text(
        json.dumps({"a.save": "\u201eZapisz\u201d", "a.open": "Otw\u00f3rz"}), encoding="utf-8")
    return make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                       targets=["pl"], state_dir=tmp_path / ".state")


def _fake_queue(monkeypatch, tmp_path, *, fixes_on: int | None):
    """op_translate stand-in: the n-th submit writes a clean value (None: never)."""
    from llm_localizator.ops import translate as translate_mod
    from llm_localizator.ops.types import OpResult
    from llm_localizator.projects import taskqueue as tq

    calls = []

    def fake(cfg_, req, **_kw):
        calls.append(req)
        if fixes_on is not None and len(calls) == fixes_on:
            path = tmp_path / "locales" / "pl.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["a.save"] = "Zapisz"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return OpResult(ok=True, exit_code=0, command="translate", summary="queued",
                        data={"taskIds": [f"t{len(calls)}"]})

    monkeypatch.setattr(translate_mod, "op_translate", fake)
    monkeypatch.setattr(tq, "task_state", lambda ids, **_k: "done")
    return calls


def test_follow_reports_a_key_fixed_by_the_first_repair(tmp_path, make_config, monkeypatch) -> None:
    cfg = _repair_project(tmp_path, make_config)
    calls = _fake_queue(monkeypatch, tmp_path, fixes_on=1)
    result = op_cycle(cfg, repair=True, follow=True)
    assert len(calls) == 1
    assert result.data["follow"]["pl"] == {"status": "done", "attempts": 1, "fixed": 1, "stuck": []}


def test_follow_retries_once_then_lists_the_stuck_key(tmp_path, make_config, monkeypatch) -> None:
    cfg = _repair_project(tmp_path, make_config)
    calls = _fake_queue(monkeypatch, tmp_path, fixes_on=None)
    result = op_cycle(cfg, repair=True, follow=True)
    assert len(calls) == 2 and calls[1].keys == ["a.save"]
    assert result.data["follow"]["pl"]["stuck"] == ["a.save"]
    assert "`a.save`" in open(result.data["report"], encoding="utf-8").read()


def test_follow_gives_up_on_timeout(tmp_path, make_config, monkeypatch) -> None:
    from llm_localizator.projects import taskqueue as tq

    cfg = _repair_project(tmp_path, make_config)
    _fake_queue(monkeypatch, tmp_path, fixes_on=None)
    monkeypatch.setattr(tq, "task_state", lambda ids, **_k: "pending")
    result = op_cycle(cfg, repair=True, follow=True, follow_timeout=0)
    assert result.data["follow"]["pl"]["status"] == "timeout"
