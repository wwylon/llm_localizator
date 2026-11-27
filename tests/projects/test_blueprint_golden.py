"""Byte-for-byte golden output of generate_blueprint (guards the Phase 3 refactor).

Blueprint text is synced into consumer ``experiments/operator_queue/`` files, so a
refactor must not change a single character. Regenerate deliberately with:

    python tests/projects/test_blueprint_golden.py --update
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from llm_localizator.projects.config import ProjectConfig, ProviderConfig
from llm_localizator.projects.taskqueue import TASK_IDS, generate_blueprint

GOLDEN = Path(__file__).with_name("blueprint_golden.json")


def _local(**o) -> ProjectConfig:
    d = dict(root=Path("/proj"), name="demo", targets=["pl", "ar"],
             models={"default": "llama3.2", "ar": "qwen2.5:7b"})
    d.update(o)
    return ProjectConfig(**d)


def _cloud(**o) -> ProjectConfig:
    d = dict(root=Path("/proj"), name="demo", targets=["pl"],
             models={"default": "claude-haiku-5-5"},
             provider=ProviderConfig(kind="anthropic"),
             improve_model="claude-haiku-5-5", score_model="claude-haiku-5-5",
             allow_cloud=True, budget_monthly_usd=5.0)
    d.update(o)
    return ProjectConfig(**d)


def cases() -> dict[str, str]:
    out: dict[str, str] = {}
    for flavour, make in (("local", _local), ("cloud", _cloud)):
        for job in sorted(TASK_IDS):
            try:
                out[f"{flavour}/{job}"] = generate_blueprint(make(), job)
            except ValueError as exc:  # e.g. a GPU job with a cloud-only model
                out[f"{flavour}/{job}"] = f"ValueError: {exc}"
        out[f"{flavour}/translate@pl"] = generate_blueprint(make(), "translate", locale="pl")
        out[f"{flavour}/translate/batch5"] = generate_blueprint(make(), "translate", batch_size=5)
        out[f"{flavour}/one-off"] = generate_blueprint(
            make(), "translate", task_id="localize_one_off_x",
            extra_args={"--ignore-min-keys": "", "--batch-size": "10"},
        )
    out["local/vram-override"] = generate_blueprint(
        _local(), "translate", vram_overrides={"llama3.2": 9.5}, wall_clock_cap_sec=1200,
    )
    return out


def test_blueprints_match_golden() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    now = cases()
    assert sorted(now) == sorted(golden)
    for name, text in now.items():
        assert text == golden[name], f"blueprint {name} changed"


if __name__ == "__main__" and "--update" in sys.argv:
    GOLDEN.write_text(json.dumps(cases(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN}")
elif __name__ == "__main__":
    pytest.main([__file__, "-q"])
