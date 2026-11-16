"""Cloud jobs in taskqueue blueprints: no GPU reservation, ollama lock, Ollama probe, teardown or --model pin."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as pyyaml

from llm_localizator.projects.config import NamedProvider, ProjectConfig, ProviderConfig
from llm_localizator.projects.taskqueue import generate_blueprint, job_runs_on_cloud


def cloud_config(**overrides) -> ProjectConfig:
    defaults = dict(
        root=Path("/proj"), name="demo", targets=["pl"],
        models={"default": "claude-haiku-5-5"},
        provider=ProviderConfig(kind="anthropic"),
        improve_model="claude-haiku-5-5", score_model="claude-haiku-5-5",
        allow_cloud=True, budget_monthly_usd=5.0,
    )
    defaults.update(overrides)
    return ProjectConfig(**defaults)


@pytest.mark.parametrize("job", ["translate", "improve", "review", "rescore", "documents"])
def test_all_cloud_job_has_no_gpu_parts(job: str) -> None:
    cfg = cloud_config()
    assert job_runs_on_cloud(cfg, job)
    text = generate_blueprint(cfg, job)
    doc = pyyaml.safe_load(text)
    assert "gpu_vram_gib" not in doc["resources"]
    assert "locks" not in doc["resources"]
    assert "requires_services" not in doc
    assert "teardown" not in doc
    assert "--model" not in doc["args"]
    assert "cloud" in doc["description"]
    # Cloud calls can still be slow: the hung override stays.
    assert doc["hung_task_k"] == 60


def test_per_locale_translate_is_cloud_too() -> None:
    doc = pyyaml.safe_load(generate_blueprint(cloud_config(), "translate", locale="pl"))
    assert "requires_services" not in doc and "--ignore-min-keys" in doc["args"]


def test_without_allow_cloud_the_job_keeps_its_gpu() -> None:
    """At run time the provider falls back to Ollama, so the reservation must stay."""
    cfg = cloud_config(allow_cloud=False, provider=ProviderConfig(kind="ollama"),
                       models={"default": "aya-expanse:8b"}, improve_model="aya-expanse:8b",
                       score_model="aya-expanse:8b")
    assert not job_runs_on_cloud(cfg, "translate")
    assert "gpu_vram_gib" in generate_blueprint(cfg, "translate")


def test_zero_budget_is_not_cloud() -> None:
    assert not job_runs_on_cloud(cloud_config(budget_monthly_usd=0.0), "improve")


def test_cloud_translator_with_local_scorer_keeps_the_gpu() -> None:
    cfg = cloud_config(provider=ProviderConfig(kind="ollama"), locale_providers={"pl": "anthropic"},
                       models={"pl": "claude-haiku-5-5", "default": "aya-expanse:8b"},
                       improve_model="aya-expanse:8b", score_model="aya-expanse:8b")
    assert not job_runs_on_cloud(cfg, "translate")
    text = generate_blueprint(cfg, "translate")
    assert "gpu_vram_gib" in text and "aya-expanse:8b" in text


def test_bakeoff_and_sync_are_never_cloud() -> None:
    cfg = cloud_config()
    assert not job_runs_on_cloud(cfg, "bakeoff")
    assert not job_runs_on_cloud(cfg, "sync")


def test_local_only_wins() -> None:
    assert not job_runs_on_cloud(cloud_config(local_only=True), "review")


def test_local_translator_with_hosted_scorer_sizes_only_the_local_model() -> None:
    """Frozen de stays on Ollama while BT scores on Haiku: no VRAM for, and no `ollama stop` of, the hosted scorer."""
    cfg = cloud_config(targets=["pl", "de"], frozen=["de"], locale_providers={"de": "local"},
                       providers={"local": NamedProvider(id="local", name="Local", kind="ollama")},
                       models={"default": "claude-haiku-5-5", "de": "aya-expanse:8b"},
                       score_provider="anthropic")
    doc = pyyaml.safe_load(generate_blueprint(cfg, "translate", locale="de"))
    assert doc["resources"]["gpu_vram_gib"] == pytest.approx(5.4)
    assert doc["teardown"]["args"] == ["stop", "aya-expanse:8b"]
    assert doc["requires_services"][0]["resident_ok_models"] == ["aya-expanse:8b"]


def test_blueprint_uses_the_configured_batch_size() -> None:
    doc = pyyaml.safe_load(generate_blueprint(cloud_config(translate_batch_size=25), "translate"))
    at = doc["args"].index("--batch-size")
    assert doc["args"][at + 1] == "25"


def test_cloud_batch_size_loads(tmp_path) -> None:
    from llm_localizator.projects.config import load_config

    path = tmp_path / ".llm-localize.toml"
    path.write_text('[project]\nname = "d"\nsource_locale = "en"\n[catalog]\nformat = "json-flat"\npath = "{locale}.json"\n'
                    '[locales]\ntargets = ["pl"]\n[translate]\ncloud_batch_size = 40\n', encoding="utf-8")
    cfg = load_config(path)
    assert cfg.translate_cloud_batch_size == 40 and cfg.translate_batch_size == 10
