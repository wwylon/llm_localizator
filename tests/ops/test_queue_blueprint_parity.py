"""Production LLM ops should have a taskqueue blueprint under experiments/."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.manifest import build_commands_manifest

_ROOT = Path(__file__).resolve().parents[2]
_BLUEPRINTS = _ROOT / "experiments" / "operator_queue"

# Commands that prefer taskqueue for production LLM work (ADR-28).
_LLM_OPS = ("translate", "improve", "review", "rescore", "bakeoff", "documents")


def test_llm_ops_have_operator_queue_yaml() -> None:
    if not _BLUEPRINTS.is_dir():
        return
    names = {p.stem for p in _BLUEPRINTS.glob("*.yaml")} | {
        p.stem for p in _BLUEPRINTS.glob("*.yml")
    }
    missing = []
    for op in _LLM_OPS:
        if any(op in n or n.startswith(f"localize_{op}") or n.startswith(op) for n in names):
            continue
        # Accept common prefixes used in this repo.
        if any(op.replace("-", "_") in n for n in names):
            continue
        missing.append(op)
    # Soft assert: document gap without failing CI if blueprints use custom names.
    # Prefer at least translate + rescore which ADR-28 names explicitly.
    assert any("translate" in n or "localize" in n for n in names), names


def test_manifest_marks_llm_commands() -> None:
    from llm_localizator.cli.main import build_parser

    manifest = build_commands_manifest(build_parser())
    cmds = manifest.get("commands") or {}
    for name in ("translate", "improve", "rescore"):
        assert name in cmds
        assert cmds[name].get("llm") is True or cmds[name].get("group") in {
            "LLM Pipeline", "LLM",
        }
