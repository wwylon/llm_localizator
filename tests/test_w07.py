"""Project config and model-eval pages (W-07)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.web.model_eval import (
    apply_recommendation,
    model_eval_view,
    report_text,
    run_bakeoff,
    run_eval,
)
from llm_localizator.web.project_config import project_config_view, save_project_config
from llm_localizator.web.shell import render_shell


def _toml(root: Path, *, extra: str = "") -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(
        "[project]\n"
        "name = \"demo\"\n"
        "source_locale = \"en\"\n"
        "\n"
        "[catalog]\n"
        "format = \"json-nested\"\n"
        "path = \"messages/{locale}/{namespace}.json\"\n"
        "\n"
        "[locales]\n"
        "targets = [\"pl\"]\n"
        "\n"
        "[provider]\n"
        "kind = \"null\"\n"
        "\n"
        "[prompt]\n"
        "family = \"chat\"\n"
        f"{extra}",
        encoding="utf-8",
    )
    (root / "messages" / "en").mkdir(parents=True, exist_ok=True)
    return path


def test_unknown_prompt_family_fails_load(tmp_path) -> None:
    path = _toml(tmp_path, extra='family = "not_a_family"\n')
    # duplicate family key — rewrite cleanly
    path.write_text(
        path.read_text(encoding="utf-8").replace('family = "chat"', 'family = "not_a_family"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="family"):
        load_config(path)


def test_save_project_config_round_trips(tmp_path) -> None:
    path = _toml(tmp_path)
    cfg = load_config(path)
    result = save_project_config(
        cfg,
        family="mt_chat",
        locale_families={"pl": "chat"},
        glossary="glossary/terms.json",
        glossary_domains={"app": ["ui", "errors"]},
    )
    assert result["ok"] is True
    loaded = load_config(path)
    assert loaded.prompt_family == "mt_chat"
    assert loaded.locale_prompt_families["pl"] == "chat"
    assert loaded.glossary_path is not None
    assert loaded.glossary_path.name == "terms.json"
    assert loaded.glossary_domains["app"] == ["ui", "errors"]
    view = project_config_view(loaded)
    assert view["family"] == "mt_chat"
    assert "chat" in view["families"]


def test_save_shared_paths_does_not_create_files(tmp_path) -> None:
    path = _toml(tmp_path)
    cfg = load_config(path)
    shared = tmp_path / "other" / "glossary.json"
    result = save_project_config(
        cfg,
        glossary_shared=["other/glossary.json"],
        tm_shared="other/memory.jsonl",
    )
    assert result["ok"] is True
    assert not shared.exists()
    assert not (tmp_path / "other" / "memory.jsonl").exists()
    loaded = load_config(path)
    assert loaded.glossary_shared[0].name == "glossary.json"
    assert loaded.tm_shared is not None
    assert loaded.tm_shared.name == "memory.jsonl"
    view = project_config_view(loaded)
    assert view["glossaryShared"] == ["other/glossary.json"]
    assert view["tmShared"] == "other/memory.jsonl"


def test_save_rejects_unknown_family(tmp_path) -> None:
    path = _toml(tmp_path)
    cfg = load_config(path)
    before = path.read_bytes()
    result = save_project_config(cfg, family="bogus")
    assert result["ok"] is False
    assert "family" in (result.get("error") or "").lower()
    assert path.read_bytes() == before


def test_apply_leaves_config_bytes_unchanged(tmp_path, monkeypatch) -> None:
    path = _toml(tmp_path)
    cfg = load_config(path)
    bakeoff = tmp_path / "quality_bakeoff"
    bakeoff.mkdir()
    (bakeoff / "REPORT.md").write_text(
        "# Quality bakeoff\n\n## Winners (consumer/chat) — ADR-12\n\n"
        "| Locale | Winner | chat BT | Runner-up | Notes |\n"
        "|--------|--------|---------|-----------|-------|\n"
        "| pl | `aya-expanse:8b` | 0.9 | qwen | |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "llm_localizator.web.model_eval.bakeoff_root", lambda: bakeoff,
    )
    before = path.read_bytes()
    result = apply_recommendation(cfg, report="REPORT.md")
    assert result["ok"] is True
    assert path.read_bytes() == before
    notes = bakeoff / "apply-notes.md"
    assert notes.exists()
    assert "REPORT.md" in notes.read_text(encoding="utf-8")


def test_apply_disabled_without_winner(tmp_path, monkeypatch) -> None:
    path = _toml(tmp_path)
    cfg = load_config(path)
    bakeoff = tmp_path / "quality_bakeoff"
    bakeoff.mkdir()
    (bakeoff / "LEDGER.md").write_text("# Ledger\n\nNo winners here.\n", encoding="utf-8")
    monkeypatch.setattr(
        "llm_localizator.web.model_eval.bakeoff_root", lambda: bakeoff,
    )
    result = apply_recommendation(cfg, report="LEDGER.md")
    assert result["ok"] is False
    assert "Winner" in (result.get("error") or "")


def test_run_without_tq_does_not_start_bakeoff(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr("llm_localizator.web.model_eval.tq_available", lambda: False)
    monkeypatch.setattr("llm_localizator.web.model_eval.subprocess.run", fake_run)
    result = run_bakeoff(locale="pl")
    assert result["ok"] is False
    assert "tq" in (result.get("error") or "").lower()
    assert calls == []


def test_model_eval_view_lists_reports(tmp_path, monkeypatch) -> None:
    bakeoff = tmp_path / "quality_bakeoff"
    bakeoff.mkdir()
    (bakeoff / "REPORT.md").write_text(
        "## Winners\n\n| Locale | Winner | chat BT | Runner-up | Notes |\n"
        "|--------|--------|---------|-----------|-------|\n"
        "| pl | aya | 0.9 | qwen | |\n",
        encoding="utf-8",
    )
    (bakeoff / "ANALYSIS.md").write_text("# analysis\n", encoding="utf-8")
    monkeypatch.setattr(
        "llm_localizator.web.model_eval.bakeoff_root", lambda: bakeoff,
    )
    view = model_eval_view()
    assert view["ok"] is True
    assert view["available"] is True
    assert view["has_winner"] is True
    names = {r["name"] for r in view["reports"]}
    assert names == {"REPORT.md", "ANALYSIS.md"}
    assert view["comparison"]
    assert "models" not in view


def test_model_eval_view_has_setup_hints(tmp_path, monkeypatch) -> None:
    cfg = load_config(_toml(tmp_path))
    monkeypatch.setattr("llm_localizator.web.model_eval.bakeoff_root", lambda: None)
    view = model_eval_view(cfg)
    assert view["locales"] == ["pl"]
    assert view["limit"] == {"min": 10, "max": 500, "default": 50}
    assert view["pinned"]


def test_report_text_validates_name(tmp_path, monkeypatch) -> None:
    bakeoff = tmp_path / "quality_bakeoff"
    bakeoff.mkdir()
    (bakeoff / "REPORT.md").write_text("# hi\n", encoding="utf-8")
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr("llm_localizator.web.model_eval.bakeoff_root", lambda: bakeoff)
    assert report_text("REPORT.md")["text"] == "# hi\n"
    for bad in ("../secret.md", "..\\secret.md", "REPORT.txt", "", "nope.md"):
        assert report_text(bad)["ok"] is False


@pytest.mark.parametrize("kwargs", [
    {"locale": "xx"},
    {"locale": "pl", "model": "bad name;rm"},
    {"locale": "pl", "limit": 5},
    {"locale": "pl", "limit": 501},
    {"locale": "pl", "limit": "abc"},
    {"locale": "pl", "corpus": "../etc"},
])
def test_run_eval_rejects_bad_input(tmp_path, monkeypatch, kwargs) -> None:
    cfg = load_config(_toml(tmp_path))

    def boom(*a, **k):
        raise AssertionError("op_bakeoff must not be reached")

    monkeypatch.setattr("llm_localizator.ops.bakeoff.op_bakeoff", boom)
    result = run_eval(cfg, **kwargs)
    assert result["ok"] is False
    assert result["error"]


def test_run_eval_passes_request_to_op(tmp_path, monkeypatch) -> None:
    cfg = load_config(_toml(tmp_path))
    seen = {}

    class _Res:
        ok = True
        summary = "dry"
        lines = ["1 cell"]
        data = {}

    def fake(cfg_, req):
        seen["req"] = req
        return _Res()

    monkeypatch.setattr("llm_localizator.ops.bakeoff.op_bakeoff", fake)
    result = run_eval(cfg, locale="pl", model="mistral:7b", limit="20", dry_run=True)
    assert result["ok"] is True
    req = seen["req"]
    assert req.locales == ["pl"] and req.models == ["mistral:7b"]
    assert req.limit == 20 and req.dry_run is True and req.submit is False


def test_shell_scripts_for_w07() -> None:
    html = render_shell("project-config", "tok")
    assert "/static/project-config.js" in html
    html = render_shell("model-eval", "tok")
    assert "/static/model-eval.js" in html
    assert "__LLM_ENSURE_HELP" in html or "requestIdleCallback" in html
    assert "me-head-actions" in html
