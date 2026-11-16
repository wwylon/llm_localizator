"""Blueprint generation and queue submission.

The VRAM derivation is the part that matters: emitting a GPU blueprint without
a reservation is how bridge lost 7x throughput (plan/optimization_log.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.projects.config import ProjectConfig
from llm_localizator.projects.taskqueue import (
    sweep_one_off_jobs,
    MODEL_VRAM_GIB,
    VRAM_HEADROOM_GIB,
    derive_vram,
    generate_blueprint,
    submit,
    submit_locales,
    task_id_for,
)


def config(**overrides) -> ProjectConfig:
    defaults = dict(
        root=Path("/proj"), name="demo",
        targets=["pl", "ar"],
        models={"default": "llama3.2", "ar": "qwen2.5:7b"},
    )
    defaults.update(overrides)
    return ProjectConfig(**defaults)


# ---- VRAM derivation -------------------------------------------------------

def test_largest_model_governs_the_reservation() -> None:
    expected = MODEL_VRAM_GIB["qwen2.5:7b"] + VRAM_HEADROOM_GIB
    assert derive_vram({"llama3.2", "qwen2.5:7b"}) == pytest.approx(expected)


def test_single_model_still_gets_headroom() -> None:
    assert derive_vram({"llama3.2"}) == pytest.approx(
        MODEL_VRAM_GIB["llama3.2"] + VRAM_HEADROOM_GIB
    )


def test_translategemma_is_in_vram_table() -> None:
    assert derive_vram({"translategemma:4b"}) == pytest.approx(
        MODEL_VRAM_GIB["translategemma:4b"] + VRAM_HEADROOM_GIB
    )


def test_override_supplies_a_missing_model() -> None:
    assert derive_vram({"custom"}, {"custom": 3.0}) == pytest.approx(3.2)


# ---- blueprint -------------------------------------------------------------

def test_blueprint_declares_a_gpu_reservation() -> None:
    # Pins default model (llama3.2), not per-locale ar→qwen — one model per job.
    yaml = generate_blueprint(config())
    assert "gpu_vram_gib: 4.3" in yaml
    assert 'locks:        [ollama]' in yaml


def test_blueprint_invokes_the_run_variant_not_the_submit_one() -> None:
    """If the blueprint called `translate`, the queue job would enqueue another job."""
    yaml = generate_blueprint(config())
    assert "run-translate" in yaml
    assert "[translate," not in yaml


def test_blueprint_uses_only_valid_taskqueue_keys() -> None:
    """`requires_ollama` and `args_overridable` belonged to bridge's deleted
    project-local daemon; `tq validate` rejects them as unknown keys. The real
    spellings are `requires_services` and `overridable_args`."""
    yaml = generate_blueprint(config())
    for invalid in ("requires_ollama:", "args_overridable:"):
        assert invalid not in yaml


def test_blueprint_declares_the_service_prerequisite() -> None:
    """R1 + S1: health + free-VRAM gate before dispatch."""
    yaml = generate_blueprint(config())
    assert "requires_services:" in yaml
    assert "name:              ollama" in yaml
    assert 'health_url:        "http://localhost:11434/api/tags"' in yaml
    assert "timeout_sec:       5" in yaml
    assert "min_vram_free_gib: 4.3" in yaml
    assert 'resident_ok_models: ["llama3.2"]' in yaml


def test_health_url_follows_the_configured_provider() -> None:
    from llm_localizator.projects.config import ProviderConfig

    yaml = generate_blueprint(config(provider=ProviderConfig(url="http://gpu-box:11434/")))
    assert 'health_url:        "http://gpu-box:11434/api/tags"' in yaml


def test_blueprint_declares_overridable_args() -> None:
    """R2: the flags a caller may scope a single run with."""
    yaml = generate_blueprint(config())
    assert "overridable_args: [" in yaml


def test_blueprint_lists_every_target_locale() -> None:
    assert '"pl,ar"' in generate_blueprint(config())


def test_base_blueprint_skips_frozen_locales() -> None:
    yaml = generate_blueprint(config(targets=["pl", "ar", "de"], frozen=["de", "ar"]))
    assert '--locales, "pl"' in yaml
    assert "1 active locale (2 frozen)" in yaml
    assert '--locales, "pl,ar"' not in yaml
    assert '--locales, "pl,ar,de"' not in yaml


def test_blueprint_marks_the_job_idempotent() -> None:
    # Retry is the queue's recovery mechanism, so this must be honest.
    assert "idempotent:       true" in generate_blueprint(config())


def test_blueprint_exposes_the_expected_overrides() -> None:
    yaml = generate_blueprint(config())
    for flag in (
        "--locales", "--model", "--batch-size", "--force", "--flagged",
        "--dry-run", "--namespace", "--collection", "--ignore-min-keys",
    ):
        assert flag in yaml


def test_per_locale_blueprint_pins_locale_and_skips_review_chain() -> None:
    yaml = generate_blueprint(config(), "translate", locale="pt-BR")
    assert "task_id:          localize_ui_messages__pt_BR" in yaml
    assert '--locales, "pt-BR"' in yaml
    assert "--ignore-min-keys" in yaml
    assert "on_complete:" not in yaml
    assert "locks:        [ollama]" in yaml
    assert task_id_for("translate", "pt-BR") == "localize_ui_messages__pt_BR"


def test_base_translate_blueprint_keeps_min_keys_gate() -> None:
    """Automated sync→translate must still honour [translate] min_keys."""
    yaml = generate_blueprint(config(), "translate")
    assert "--ignore-min-keys" not in yaml.split("args:", 1)[1].split("\n\n", 1)[0]




def test_unknown_job_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown job"):
        generate_blueprint(config(), "nonsense")


def test_review_blueprint_also_declares_vram() -> None:
    """F-004: bridge's hand-written review blueprint omitted this."""
    assert "gpu_vram_gib:" in generate_blueprint(config(), "review")
    assert "locks:" in generate_blueprint(config(), "review")


def test_sync_blueprint_is_cpu_only_and_chains_translate() -> None:
    yaml = generate_blueprint(config(), "sync")
    assert "run-sync" in yaml
    assert "--no-translate" in yaml
    assert "gpu_vram_gib:" not in yaml
    assert "requires_services:" not in yaml
    assert "priority:         30" in yaml
    assert "on_complete: [localize_ui_messages]" in yaml
    assert 'cron: "30 1 * * *"' in yaml


def test_improve_blueprint_wires_wave2_gpu_lane() -> None:
    yaml = generate_blueprint(config(improve_model="aya-expanse:8b"), "improve")
    assert "run-improve" in yaml
    assert "gpu_vram_gib: 5.4" in yaml
    assert "priority:         20" in yaml
    assert "depends_on: [localize_ui_messages]" in yaml
    assert "rearm_on:   upstream_success" in yaml
    assert 'cron: "0 2 * * *"' in yaml
    assert "hung_task_k: 60" in yaml
    assert 'args:        [stop, "aya-expanse:8b"]' in yaml
    assert 'locks:        [ollama]' in yaml


def test_rescore_blueprint_wires_gpu_lane() -> None:
    yaml = generate_blueprint(config(score_model="aya-expanse:8b"), "rescore")
    assert "run-rescore" in yaml
    assert "task_id:          localize_rescore" in yaml
    assert "gpu_vram_gib: 5.4" in yaml
    assert 'locks:        [ollama]' in yaml
    assert "--namespace" in yaml
    assert '--model, "aya-expanse:8b"' in yaml
    assert 'args:        [stop, "aya-expanse:8b"]' in yaml


def test_rescore_vram_covers_judge_when_larger() -> None:
    yaml = generate_blueprint(
        config(score_model="llama3.2", judge_model="aya-expanse:8b"),
        "rescore",
    )
    # max(4.1, 5.2) + 0.2 headroom
    assert "gpu_vram_gib: 5.4" in yaml
    assert 'resident_ok_models: ["llama3.2"]' in yaml


def test_translate_blueprint_reserves_score_model_when_different() -> None:
    yaml = generate_blueprint(
        config(
            models={"default": "translategemma:4b", "ar": "translategemma:4b"},
            score_model="aya-expanse:8b",
        ),
        "translate",
        locale="ar",
    )
    # max(translategemma:4b, aya-expanse:8b) + headroom
    assert "gpu_vram_gib: 5.4" in yaml
    assert 'resident_ok_models: ["translategemma:4b", "aya-expanse:8b"]' in yaml
    assert 'args:        [stop, "aya-expanse:8b"]' in yaml




# ---- submission ------------------------------------------------------------

class FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_submit_uses_retry_on_the_happy_path(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []

    def runner(cmd, **_kw):
        seen.append(cmd)
        return FakeProc(0, "queued")

    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    assert submit(config(root=tmp_path), "translate", runner=runner).exit_code == 0
    assert seen[0] == ["tq", "retry", "demo/localize_ui_messages"]








def test_submit_without_overrides_passes_no_set_flags(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []

    def runner(cmd, **_kw):
        seen.append(cmd)
        return FakeProc(0, "queued")

    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    submit(config(root=tmp_path), "translate", runner=runner)
    assert "--set" not in seen[0]


def test_submit_locales_retries_each_locale(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []

    def runner(cmd, **_kw):
        seen.append(cmd)
        return FakeProc(0, "queued")

    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    out = submit_locales(config(root=tmp_path), ["vi", "de"], runner=runner)
    assert out.ok
    assert seen[0] == ["tq", "retry", "demo/localize_ui_messages__vi"]
    assert seen[1] == ["tq", "retry", "demo/localize_ui_messages__de"]
    assert "demo/localize_ui_messages__vi" in out.task_ids
    assert "demo/localize_ui_messages__de" in out.task_ids


def test_submit_locales_partial_success(monkeypatch, tmp_path) -> None:
    def runner(cmd, **_kw):
        task = cmd[2]
        if task.endswith("__vi"):
            return FakeProc(0, "queued")
        return FakeProc(1, "fatal boom")

    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    out = submit_locales(config(root=tmp_path), ["vi", "de"], runner=runner)
    assert out.ok  # any locale ok → overall ok
    assert "localize_ui_messages__vi" in out.message or "queued" in out.message


def test_submit_falls_back_to_add_when_task_is_unregistered(monkeypatch, tmp_path) -> None:
    blueprint = tmp_path / "experiments" / "operator_queue" / "llm_localizator_translate.yaml"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text("task_id: localize_ui_messages\n", encoding="utf-8")

    calls: list[list[str]] = []

    def runner(cmd, **_kw):
        calls.append(cmd)
        if "retry" in cmd:
            # First retry: unregistered. After `tq add`, retry succeeds.
            if any("add" in c for c in calls):
                return FakeProc(0, "queued")
            return FakeProc(1, "", "task not found")
        return FakeProc(0, "added")

    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    assert submit(config(root=tmp_path), "translate", runner=runner).exit_code == 0
    assert "add" in calls[1]




def test_submit_already_queued_is_success(monkeypatch, tmp_path) -> None:
    def runner(cmd, **_kw):
        return FakeProc(1, "cannot retry task with status 'queued'")

    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    out = submit(config(root=tmp_path), "translate", runner=runner)
    assert out.ok
    assert "already queued" in out.message


def test_submit_raises_when_tq_is_absent(monkeypatch) -> None:
    from llm_localizator.projects.taskqueue import TaskqueueNotFound

    monkeypatch.setattr("shutil.which", lambda _n: None)
    with pytest.raises(TaskqueueNotFound):
        submit(config(), "translate")


# ---- one-off runs (per-run options) ----------------------------------------

def test_per_locale_blueprint_resolves_the_locale_model_at_run_time() -> None:
    """No baked --model: run-translate uses model_for(locale) and keeps roles."""
    yaml = generate_blueprint(config(), "translate", locale="ar")
    args = yaml.split("args:", 1)[1].split("\n", 1)[0]
    assert "--model" not in args
    assert 'resident_ok_models: ["qwen2.5:7b", "llama3.2"]' in yaml
    assert "task_id:          localize_ui_messages__ar" in yaml


def test_translate_blueprint_does_not_pin_a_model() -> None:
    yaml = generate_blueprint(config())
    assert "--model" not in yaml.split("args:", 1)[1].split("\n", 1)[0]
    assert "hung_task_k: 60" in yaml
    assert 'args:        [stop, "llama3.2"]' in yaml


def _one_off_runner(seen: list[list[str]], add_result: "FakeProc | None" = None):
    def runner(cmd, **_kw):
        seen.append(cmd)
        if cmd[1] == "add":
            return add_result or FakeProc(0, "Added")
        return FakeProc(0, "done")
    return runner


def test_per_run_options_are_baked_into_a_one_off_blueprint(monkeypatch, tmp_path) -> None:
    """Options used to vanish when tq rejected `retry --set`; now they are the task's args."""
    seen: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    out = submit(
        config(root=tmp_path), "translate",
        {"--keys": "app.save,app.title", "--force": "true", "--model": "qwen2.5:14b"},
        locale="pl", runner=_one_off_runner(seen),
    )
    assert out.ok and "queued one-off" in out.message
    add = next(c for c in seen if c[1] == "add")
    assert add[-2:] == ["--project", "demo"]
    text = Path(add[2]).read_text(encoding="utf-8")
    args = text.split("args:", 1)[1].split("\n", 1)[0]
    assert '--keys, "app.save,app.title"' in args
    assert "--force" in args and '--model, "qwen2.5:14b"' in args
    assert "--ignore-min-keys" in args
    assert "__oneoff_" in text and "schedule:" not in text and "on_complete" not in text
    assert not any(c[1] == "retry" for c in seen)
    assert (config(root=tmp_path).state_root() / "one_off_jobs.jsonl").exists()


def test_several_locales_with_options_become_one_run(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    out = submit_locales(
        config(root=tmp_path), ["zh", "ar"], "translate", {"--keys": "a.b"},
        runner=_one_off_runner(seen),
    )
    assert out.ok
    adds = [c for c in seen if c[1] == "add"]
    assert len(adds) == 1
    args = Path(adds[0][2]).read_text(encoding="utf-8").split("args:", 1)[1].split("\n", 1)[0]
    assert '--locales, "zh,ar"' in args


def test_unknown_project_gets_a_registration_hint(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    out = submit(
        config(root=tmp_path), "translate", {"--force": "true"},
        runner=_one_off_runner(seen, FakeProc(1, "", "add failed: Unknown project 'demo'")),
    )
    assert not out.ok
    assert "~/.taskqueue/projects.yaml" in out.message and "demo:" in out.message


def test_settled_one_off_files_are_swept(monkeypatch, tmp_path) -> None:
    """tq copies the blueprint into queue_dir; it must not stay in the consumer repo."""
    seen: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    cfg = config(root=tmp_path)
    submit(cfg, "improve", {"--keys": "a.b"}, runner=_one_off_runner(seen))
    blueprint = Path(next(c for c in seen if c[1] == "add")[2])
    copy = tmp_path / "experiments" / "operator_queue" / blueprint.name
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text("copied by tq add", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(cmd, **_kw):
        calls.append(list(cmd))
        return FakeProc(0, "done")

    removed = sweep_one_off_jobs(cfg, runner=runner)
    assert removed == 1
    assert not copy.exists() and not blueprint.exists()
    # The DB row goes too, or it piles up once its YAML is gone.
    assert any(c[1:2] == ["remove"] and "__oneoff_" in c[2] for c in calls)



def test_failed_retry_after_add_is_success_when_the_task_is_queued(monkeypatch, tmp_path) -> None:
    """problems_open 2026-11-05: `tq add` queued the task, the follow-up retry errored, submit reported failure."""
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tq")
    calls: list[list[str]] = []

    def runner(cmd, **_kw):
        calls.append(list(cmd))
        verb = cmd[1]
        if verb == "retry" and sum(c[1] == "retry" for c in calls) == 1:
            return FakeProc(1, "", "task not found")
        if verb == "add":
            return FakeProc(0, "added")
        if verb == "retry":
            return FakeProc(1, "", "some retry error")
        if verb == "wait":
            return FakeProc(2, "timeout")  # still pending = queued
        return FakeProc(0, "")

    out = submit(config(root=tmp_path), "translate", runner=runner)
    assert out.ok and "registered by tq add" in out.message
