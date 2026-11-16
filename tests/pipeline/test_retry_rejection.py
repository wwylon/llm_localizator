"""A validation-rejected translation is retried once, with the reason in the prompt."""

from __future__ import annotations

from llm_localizator.pipeline.prompts import BatchItem, build_refine_prompt, build_single_prompt
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import CompletionRequest, NullProvider

from .test_translate import setup_project

TAG = "[previous attempt rejected:"


def _run(project_root, make_config, make_catalog, silent, handler):
    setup_project(project_root, {"hi": "Hello {name}"})
    cfg = make_config(project_root)
    provider = NullProvider(handler=handler)
    result = run_translation(cfg, make_catalog(cfg), provider, report=silent)
    return result, provider


def test_rejected_placeholder_is_retried_with_the_reason(
    project_root, make_config, make_catalog, silent
) -> None:
    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            return "Hello {name}"
        if TAG in request.prompt:
            return "Witaj {name}"
        return "Witaj"  # placeholder dropped

    result, provider = _run(project_root, make_config, make_catalog, silent, handler)
    assert result.rejected == []
    retry_prompts = [c.prompt for c in provider.calls if TAG in c.prompt]
    assert len(retry_prompts) == 1
    assert "missing placeholders" in retry_prompts[0].split(TAG, 1)[1]


def test_a_still_bad_retry_is_rejected_after_exactly_one_retry(
    project_root, make_config, make_catalog, silent
) -> None:
    def handler(request: CompletionRequest) -> str:
        return "Witaj"

    result, provider = _run(project_root, make_config, make_catalog, silent, handler)
    assert result.rejected == ["pl/app.hi"]
    assert sum(TAG in c.prompt for c in provider.calls) == 1


def test_single_and_refine_prompts_carry_the_tag() -> None:
    item = BatchItem(source="Save", previous_rejection="placeholder {n} was missing\nextra")
    single = build_single_prompt(item, "Polish", "demo", "")
    assert "[previous attempt rejected: placeholder {n} was missing extra]" in single
    assert TAG not in build_single_prompt(BatchItem(source="Save"), "Polish", "demo", "")
    refine = build_refine_prompt(
        BatchItem(source="Save"), "Zapisz", "Polish", "demo", "", rejection="too long",
    )
    assert "[previous attempt rejected: too long]" in refine


def test_long_reason_is_trimmed() -> None:
    item = BatchItem(source="Save", previous_rejection="x" * 500)
    assert "x" * 200 not in build_single_prompt(item, "Polish", "demo", "")
