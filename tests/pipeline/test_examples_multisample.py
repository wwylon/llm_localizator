"""Few-shot examples_file wiring and multi-sample selection."""

from __future__ import annotations

import json
from pathlib import Path


from llm_localizator.pipeline.prompts import BatchItem, build_single_prompt
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.projects.context import append_example, load_examples
from llm_localizator.providers import CompletionRequest, NullProvider

from ..conftest import write_json


def test_load_examples_caps_and_skips_bad(tmp_path: Path) -> None:
    path = tmp_path / "examples.json"
    path.write_text(
        json.dumps({
            "pl": [["Hello", "Cześć"], ["Bye", "Pa"], ["A", "B"], ["C", "D"],
                   ["E", "F"], ["G", "H"], ["bad"]],
            "de": "not a list",
        }),
        encoding="utf-8",
    )
    loaded = load_examples(path)
    assert len(loaded["pl"]) == 5
    assert "de" not in loaded


def test_append_example_dedupes(tmp_path: Path) -> None:
    path = tmp_path / "examples.json"
    assert append_example(path, "pl", "Hello", "Cześć")
    assert not append_example(path, "pl", "Hello", "Cześć")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["pl"] == [["Hello", "Cześć"]]


def test_prompt_includes_examples() -> None:
    item = BatchItem(
        source="Save",
        examples=[("Cancel", "Anuluj"), ("Delete", "Usuń")],
    )
    prompt = build_single_prompt(item, "Polish", "a test app", "")
    assert "EN: Cancel → Anuluj" in prompt
    assert "EN: Delete → Usuń" in prompt


def test_translate_injects_examples(project_root, make_config, make_catalog, silent) -> None:
    write_json(project_root / "messages" / "en" / "app.json", {"greet": "Hello"})
    examples = project_root / "i18n" / "examples.json"
    examples.parent.mkdir(parents=True)
    examples.write_text(
        json.dumps({"pl": [["Goodbye", "Do widzenia"]]}, ensure_ascii=False),
        encoding="utf-8",
    )
    cfg = make_config(project_root, examples_file=examples)
    seen: list[str] = []

    def handler(req: CompletionRequest) -> str:
        seen.append(req.prompt)
        return "[xx] Hello"

    result = run_translation(
        cfg, make_catalog(cfg), NullProvider(handler=handler), report=silent,
    )
    assert result.written == 1
    assert any("EN: Goodbye → Do widzenia" in p for p in seen)


def test_multi_sample_picks_bt_best(project_root, make_config, make_catalog, silent) -> None:
    """With multi_sample=2, keep the candidate whose BT is closer to the source."""
    write_json(project_root / "messages" / "en" / "app.json", {"greet": "Hello world"})
    cfg = make_config(project_root, multi_sample=2, quality_threshold=0.9)
    # Answer by prompt kind, not call order: the risky-key judge (ADR-125) also runs and shifts the order.
    samples = ["Bonjour monde", "Witaj świecie"]   # sample 1 back-translates badly, sample 2 well

    def handler(req: CompletionRequest) -> str:
        prompt = req.prompt
        if "back to English" in prompt:
            return "Bonjour monde" if "Bonjour" in prompt else "Hello world"
        if "quality judge" in prompt:
            good = "Witaj" in prompt
            return json.dumps({
                "semantic_accuracy": 95 if good else 20, "fluency": 95 if good else 20,
                "terminology": 95 if good else 20, "ui_appropriateness": 95 if good else 20,
                "missing_information": False, "added_information": False,
                "placeholder_error": False, "html_error": False, "explanation": "test",
            })
        return samples.pop(0) if samples else "Witaj świecie"

    result = run_translation(
        cfg, make_catalog(cfg), NullProvider(handler=handler),
        multi_sample=2, report=silent,
    )
    assert result.written == 1
    assert make_catalog(cfg).load("pl", "app")["greet"] == "Witaj świecie"


def test_multi_sample_records_a_consistency_dimension(
    project_root, make_config, make_catalog, silent,
) -> None:
    from llm_localizator.catalog import ScoreStore

    write_json(project_root / "messages" / "en" / "app.json", {"greet": "Hello world"})
    cfg = make_config(
        project_root, multi_sample=2, scores_dir=project_root / ".llm-scores",
    )
    samples = iter(["Witaj świecie", "Dzień dobry wszystkim ludziom"])

    def handler(req: CompletionRequest) -> str:
        if "back to English" in req.prompt:
            return "Hello world"
        return next(samples, "Witaj świecie")

    run_translation(
        cfg, make_catalog(cfg), NullProvider(handler=handler), multi_sample=2, report=silent,
    )
    entry = ScoreStore(cfg.scores_dir).get("pl", "app", "greet")
    assert entry["dimensions"]["consistency"] < 0.8
    assert any(sig.startswith("low-consistency") for sig in entry["signals"])


def test_single_sample_has_no_consistency_dimension(
    project_root, make_config, make_catalog, silent,
) -> None:
    from llm_localizator.catalog import ScoreStore

    write_json(project_root / "messages" / "en" / "app.json", {"greet": "Hello world"})
    cfg = make_config(project_root, scores_dir=project_root / ".llm-scores")

    def handler(req: CompletionRequest) -> str:
        return "Hello world" if "back to English" in req.prompt else "Witaj świecie"

    run_translation(cfg, make_catalog(cfg), NullProvider(handler=handler), report=silent)
    entry = ScoreStore(cfg.scores_dir).get("pl", "app", "greet")
    assert "consistency" not in (entry.get("dimensions") or {})
