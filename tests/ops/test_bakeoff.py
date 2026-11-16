"""In-package bakeoff: evidence for an ADR-12 model decision, never a config change."""

from __future__ import annotations

import json

import pytest

from llm_localizator.ops.bakeoff import op_bakeoff
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.types import BakeoffRequest
from llm_localizator.pipeline.bakeoff import (
    BUILTIN_CORPUS,
    KeyRow,
    load_corpus_file,
    plan_cells,
    run_cell,
    sample_catalogue,
    stratify,
)
from llm_localizator.providers import CompletionRequest, NullProvider

from tests.conftest import setup_project

SOURCES = {
    "saveButton": "Save",
    "cancelButton": "Cancel",
    "errorNoNetwork": "No connection",
    "errorTimeout": "Timed out",
    "welcomeTitle": "Welcome to the app",
    "menuHelp": "Help",
}


def _handler(request: CompletionRequest) -> str:
    if "back to English" in request.prompt:
        return "Save"
    return f"[pl] {request.source_texts[0]}" if request.source_texts else "x"


def _row(key: str, bucket: str) -> KeyRow:
    return KeyRow(key=key, source=key, bucket=bucket, message_key=key)


def _quiet(_message: str) -> None:
    return None


def test_stratify_is_deterministic_and_covers_every_bucket() -> None:
    rows = [_row(f"{b}{i}", b) for b in ("button", "error", "menu") for i in range(6)]
    first = stratify(rows, 6, seed=0)
    assert [r.key for r in first] == [r.key for r in stratify(rows, 6, seed=0)]
    assert {r.bucket for r in first} == {"button", "error", "menu"}
    assert len(stratify(rows, 100)) == len(rows)


def test_the_builtin_corpus_ships_with_the_package() -> None:
    rows = load_corpus_file(BUILTIN_CORPUS)
    assert len(rows) >= 50
    assert {"buttons", "errors"} <= {r.bucket for r in rows}


def test_catalogue_sample_buckets_by_key_role(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    rows = sample_catalogue(cfg, make_catalog(cfg), limit=4)
    assert len(rows) == 4
    assert all(r.message_key.startswith("app.") for r in rows)
    assert len({r.bucket for r in rows}) > 1


def test_plan_always_includes_the_locales_incumbent(project_root, make_config) -> None:
    cfg = make_config(project_root)
    cells = plan_cells(cfg, ["candidate:7b"], ["pl"])
    assert {c.model for c in cells} == {"candidate:7b", cfg.model_for("pl")}
    matrix = plan_cells(cfg, ["candidate:7b"], ["pl"], matrix=True)
    assert {(c.mode, c.family) for c in matrix} == {
        ("stripped", "chat"), ("consumer", "chat"), ("consumer", "mt_chat"),
    }


def test_run_cell_scores_and_gates(project_root, make_config) -> None:
    cfg = make_config(project_root)
    cell = plan_cells(cfg, ["m"], ["pl"])[0]
    keys = [_row("Save", "buttons"), _row("Cancel", "buttons")]

    def good(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            return "Save" if "Zapisz" in request.prompt else "Cancel"
        return "Zapisz" if "Save" in request.prompt else "Anuluj"

    result = run_cell(
        NullProvider(handler=good), cell, keys, cfg=cfg, glossary={}, report=_quiet,
    )
    assert result.accepted == 2 and result.reject_rate == 0
    assert result.gate_ok and result.mean >= 0.7


def test_dry_run_lists_cells_and_calls_no_model(project_root, make_config) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    result = op_bakeoff(cfg, BakeoffRequest(models=["cand:7b"], dry_run=True, limit=4))
    assert result.ok and "nothing was run" in result.summary
    assert result.data["keys"] == 4
    assert {c["model"] for c in result.data["cells"]} == {"cand:7b", cfg.model_for("pl")}


def test_run_writes_evidence_and_skips_finished_cells(project_root, make_config, tmp_path) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    out = tmp_path / "bake"
    provider = NullProvider(handler=_handler)
    req = BakeoffRequest(models=["cand:7b"], limit=3, out=str(out), inline=True)

    first = op_bakeoff(cfg, req, provider=provider, report=_quiet)
    assert first.ok, first.summary
    assert first.data["ran"] == 2 and "unchanged" in first.summary
    rows = [json.loads(x) for x in (out / "matrix_results.jsonl").read_text().splitlines()]
    assert {r["model"] for r in rows} == {"cand:7b", cfg.model_for("pl")}
    assert (out / "LEDGER.md").is_file()
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert report.startswith("# Quality bakeoff report") and "## Matrix run" in report

    second = op_bakeoff(cfg, req, provider=provider, report=_quiet)
    assert second.data["ran"] == 0 and second.data["skipped"] == 2


def test_report_append_never_touches_a_hand_written_winners_section(
    project_root, make_config, tmp_path,
) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    out = tmp_path / "bake"
    out.mkdir()
    winners = "# Quality bakeoff report\n\n## Winners (consumer/chat) - ADR-12\n\n| pl | aya |\n"
    (out / "REPORT.md").write_text(winners, encoding="utf-8")
    op_bakeoff(
        cfg, BakeoffRequest(models=["cand:7b"], limit=2, out=str(out), inline=True),
        provider=NullProvider(handler=_handler), report=_quiet,
    )
    assert (out / "REPORT.md").read_text(encoding="utf-8").startswith(winners.rstrip())


def test_it_does_not_change_the_configured_models(project_root, make_config, tmp_path) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    before = dict(cfg.models)
    op_bakeoff(
        cfg, BakeoffRequest(models=["cand:7b"], limit=2, out=str(tmp_path / "b"), inline=True),
        provider=NullProvider(handler=_handler), report=_quiet,
    )
    assert cfg.models == before


def test_a_non_ollama_project_is_refused(project_root, make_config) -> None:
    cfg = make_config(project_root)
    result = op_bakeoff(cfg, BakeoffRequest(inline=True))
    assert not result.ok and "local Ollama" in result.summary


@pytest.fixture
def queue(monkeypatch):
    submitted: list[dict] = []

    class Outcome:
        ok = True
        exit_code = 0
        message = "queued"
        task_ids = ("localize_bakeoff",)

    def fake_submit(cfg, job, overrides=None, **_kw):
        submitted.append({"job": job, "overrides": overrides})
        return Outcome()

    monkeypatch.setattr("llm_localizator.ops.bakeoff.tq_available", lambda: True)
    monkeypatch.setattr("llm_localizator.ops.bakeoff.submit", fake_submit)
    return submitted


def test_bakeoff_prefers_the_queue_and_run_bakeoff_does_not(
    project_root, make_config, queue,
) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    cfg.provider.kind = "ollama"
    queued = op_bakeoff(cfg, BakeoffRequest(models=["a", "b"], limit=5, matrix=True))
    assert queued.summary == "queued"
    assert queue[0]["job"] == "bakeoff"
    assert queue[0]["overrides"] == {
        "--locales": "pl", "--models": "a,b", "--limit": "5", "--matrix": "true",
    }

    queue.clear()
    inline = dispatch_op(cfg, "run-bakeoff", {"dry_run": True, "corpus": "builtin"}, actor_role="Admin")
    assert queue == [] and inline["ok"] is True


def test_the_blueprint_sizes_vram_from_the_largest_candidate(project_root, make_config) -> None:
    from llm_localizator.projects.taskqueue import generate_blueprint

    cfg = make_config(project_root)
    text = generate_blueprint(cfg, "bakeoff", vram_overrides={"testmodel": 3.0})
    assert "task_id:          localize_bakeoff" in text
    assert "run-bakeoff" in text and "--models" in text
    assert "gpu_vram_gib: 5.4" in text  # aya-expanse:8b (5.2) + headroom


def test_bucket_of_understands_camel_and_snake_case_keys() -> None:
    from llm_localizator.pipeline.bakeoff import bucket_of

    assert bucket_of("app.saveButton") == "button label"
    assert bucket_of("app.error_no_network") == "error message"
    assert bucket_of("app.welcome") == "other"


def test_a_cell_that_fails_the_gate_says_so(project_root, make_config) -> None:
    cfg = make_config(project_root)
    cell = plan_cells(cfg, ["m"], ["pl"])[0]
    keys = [_row("Save your changes now", "buttons"), _row("Cancel this whole action", "buttons")]
    # Echoing the English source back is the leftover-English case: it scores far below 0.7.
    echo = NullProvider(handler=lambda request: request.source_texts[0]
                        if request.source_texts else "Save your changes now")
    result = run_cell(echo, cell, keys, cfg=cfg, glossary={}, report=_quiet)
    assert not result.gate_ok and result.mean < 0.7


def test_a_provider_error_counts_as_a_reject_not_a_crash(project_root, make_config) -> None:
    cfg = make_config(project_root)
    cell = plan_cells(cfg, ["m"], ["pl"])[0]
    keys = [_row("Save", "buttons"), _row("Cancel", "buttons")]
    provider = NullProvider(handler=_handler, fail_on="Cancel")
    result = run_cell(provider, cell, keys, cfg=cfg, glossary={}, report=_quiet)
    assert result.reject_rate == 0.5
    assert list(result.out_map) == ["Save"]


def test_corpus_file_is_used_and_limited(project_root, make_config, tmp_path) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([
        {"key": f"k{i}", "source": f"String number {i}", "bucket": "b"} for i in range(10)
    ]), encoding="utf-8")
    result = op_bakeoff(cfg, BakeoffRequest(corpus=str(corpus), limit=4, dry_run=True))
    assert result.ok and result.data["keys"] == 4
    missing = op_bakeoff(cfg, BakeoffRequest(corpus=str(tmp_path / "nope.json"), dry_run=True))
    assert not missing.ok and "cannot read corpus" in missing.summary


def test_a_model_that_never_answers_is_not_ledgered(project_root, make_config, tmp_path) -> None:
    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    out = tmp_path / "bake"

    def dead(_request: CompletionRequest) -> str:
        from llm_localizator.providers import ProviderError

        raise ProviderError("model not found")

    req = BakeoffRequest(models=["ghost:7b"], limit=3, out=str(out), inline=True)
    op_bakeoff(cfg, req, provider=NullProvider(handler=dead), report=_quiet)
    ledger = out / "matrix_results.jsonl"
    assert not ledger.exists() or ledger.read_text(encoding="utf-8").strip() == ""

    again = op_bakeoff(cfg, req, provider=NullProvider(handler=_handler), report=_quiet)
    assert again.data["skipped"] == 0  # the dead run left nothing that hides the cell


def test_a_dead_model_is_not_retried_for_its_other_cells(project_root, make_config, tmp_path) -> None:
    import dataclasses

    from llm_localizator.pipeline.bakeoff import Cell, load_corpus_file, run_bakeoff
    from llm_localizator.providers import ProviderError

    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    calls: list[str] = []

    def dead(request: CompletionRequest) -> str:
        calls.append(request.model)
        raise ProviderError("model not found")

    base = Cell(model="ghost:7b", locale="pl", mode="consumer", family="chat")
    cells = [base, dataclasses.replace(base, locale="de"), dataclasses.replace(base, locale="fr")]
    keys = load_corpus_file()[:3]
    out = run_bakeoff(
        cfg, NullProvider(handler=dead), cells, keys, out_dir=tmp_path / "b", report=_quiet,
    )
    assert len(out.failed) == 3  # all reported failed ...
    assert len(calls) <= len(keys) * 2  # ... but only the first cell touched the model


def test_previous_model_is_unloaded_when_the_bakeoff_switches(project_root, make_config, tmp_path) -> None:
    import dataclasses

    from llm_localizator.pipeline.bakeoff import Cell, load_corpus_file, run_bakeoff

    setup_project(project_root, SOURCES)
    cfg = make_config(project_root)
    stopped: list[str] = []

    class Unloading(NullProvider):
        def stop(self, model: str) -> None:
            stopped.append(model)

    a = Cell(model="a:7b", locale="pl", mode="consumer", family="chat")
    cells = [a, dataclasses.replace(a, locale="de"), dataclasses.replace(a, model="b:7b")]
    run_bakeoff(cfg, Unloading(handler=_handler), cells, load_corpus_file()[:2],
                out_dir=tmp_path / "b", report=_quiet)
    assert stopped == ["a:7b", "b:7b"]  # once on the switch, once at the end
