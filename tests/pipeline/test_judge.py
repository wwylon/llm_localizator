"""LQS judge and score_candidate (ADR-20, ADR-158)."""

from __future__ import annotations

import json

from llm_localizator.pipeline.judge import (
    build_judge_prompt,
    build_key_rubric,
    lqs_from_judgment,
    normalize_issues,
    parse_judge_response,
    quality_from_judge,
)
from llm_localizator.pipeline.scoring import (
    improve_score_cut,
    judge_model_for,
    score_candidate,
    score_model_for,
    score_with_backtranslation,
)
from llm_localizator.providers import CompletionRequest, NullProvider


def test_parse_judge_json():
    raw = json.dumps({
        "semantic_accuracy": 90,
        "fluency": 85,
        "terminology": 80,
        "ui_appropriateness": 88,
        "missing_information": False,
        "added_information": False,
        "placeholder_error": False,
        "html_error": False,
        "explanation": "solid",
    })
    result = parse_judge_response(raw)
    assert result.ok
    score, dims, signals, issues = lqs_from_judgment(
        result.judgment, source="Hello", translated="Cześć",
    )
    assert 0.8 <= score <= 1.0
    assert dims["semantic"] == 0.9
    assert any("solid" in s for s in signals)
    assert issues == []


def test_lqs_penalizes_missing_info():
    judgment = {
        "semantic_accuracy": 100,
        "fluency": 100,
        "terminology": 100,
        "ui_appropriateness": 100,
        "missing_information": True,
        "added_information": False,
        "placeholder_error": False,
        "html_error": False,
    }
    score, dims, _, issues = lqs_from_judgment(
        judgment, source="Delete permanently", translated="Usuń",
    )
    assert dims["info"] == 0.0
    assert score < 0.9
    assert issues == []


def test_major_issue_caps_lqs_below_060():
    judgment = {
        "semantic_accuracy": 95,
        "fluency": 95,
        "terminology": 95,
        "ui_appropriateness": 95,
        "missing_information": False,
        "added_information": False,
        "placeholder_error": False,
        "html_error": False,
        "issues": [{
            "category": "accuracy",
            "severity": "major",
            "description": "Wrong verb polarity: delete vs keep",
        }],
    }
    score, _dims, signals, issues = lqs_from_judgment(
        judgment, source="Delete", translated="Zachowaj",
    )
    assert score <= 0.59
    assert len(issues) == 1
    assert issues[0]["severity"] == "major"
    assert any("judge issue: major/accuracy" in s for s in signals)


def test_normalize_issues_drops_malformed():
    assert normalize_issues([
        {"category": "accuracy", "severity": "minor", "description": "ok"},
        {"category": "nope", "severity": "minor", "description": "bad cat"},
        {"category": "accuracy", "severity": "huge", "description": "bad sev"},
        "not-a-dict",
    ]) == [{"category": "accuracy", "severity": "minor", "description": "ok"}]


def test_build_key_rubric_includes_placeholders_and_role():
    rubric = build_key_rubric(
        source="Hello {name}",
        locale="pl",
        message_key="app.button.save",
        max_chars=24,
        glossary={"terms": {"Hello": {"pl": "Cześć"}}},
    )
    joined = "\n".join(rubric)
    assert "{name}" in joined or "name" in joined
    assert "24" in joined
    assert "button" in joined.lower()
    assert "Cześć" in joined


def test_judge_prompt_includes_rubric_checklist():
    prompt = build_judge_prompt(
        source="Save", translated="Zapisz", language="Polish", domain="an app",
        rubric=["UI role is button label: keep length short."],
    )
    assert "Per-key rubric" in prompt
    assert "button label" in prompt
    assert '"issues"' in prompt


def test_quality_from_judge_hard_fail():
    q = quality_from_judge(
        source="Hello {name}",
        translated="Witaj",
        locale="pl",
        glossary={},
        judgment={
            "semantic_accuracy": 100, "fluency": 100,
            "terminology": 100, "ui_appropriateness": 100,
        },
    )
    assert q.score == 0.0
    assert q.scorer == "lqs"


def test_score_candidate_without_judge_uses_bt(make_config, tmp_path):
    cfg = make_config(tmp_path)
    assert judge_model_for(cfg) is None
    provider = NullProvider(handler=lambda r: "Hello friend")
    q = score_candidate(
        provider,
        source="Hello friend",
        translated="Witaj przyjacielu",
        locale="pl",
        language="Polish",
        glossary={},
        cfg=cfg,
    )
    assert q.scorer in {"bt", "heuristic"}
    assert q.score > 0


def test_score_candidate_with_judge(make_config, tmp_path):
    cfg = make_config(tmp_path)
    cfg.judge_model = "judge-test"

    def handler(req: CompletionRequest) -> str:
        if "quality judge" in req.prompt or "localization quality judge" in req.prompt.lower():
            return json.dumps({
                "semantic_accuracy": 92,
                "fluency": 90,
                "terminology": 88,
                "ui_appropriateness": 91,
                "missing_information": False,
                "added_information": False,
                "placeholder_error": False,
                "html_error": False,
                "explanation": "ok",
            })
        return "Hello"

    provider = NullProvider(handler=handler)
    q = score_candidate(
        provider,
        source="Hello",
        translated="Cześć",
        locale="pl",
        language="Polish",
        glossary={},
        cfg=cfg,
        message_key="app.hi",
    )
    assert q.scorer == "lqs"
    assert q.dimensions is not None
    # Judge dimensions and the deterministic ones live side by side.
    assert {"semantic", "fluency", "placeholder_ok", "glossary_ok", "script_ok"} <= set(q.dimensions)
    assert q.score >= 0.85
    assert improve_score_cut(cfg, scorer="lqs") == cfg.band_retranslate


def test_judge_prompt_names_the_configured_source_language(make_config, tmp_path):
    cfg = make_config(tmp_path, source_locale="de")
    cfg.judge_model = "judge-test"
    prompts: list[str] = []

    def handler(req: CompletionRequest) -> str:
        prompts.append(req.prompt)
        return json.dumps({
            "semantic_accuracy": 90, "fluency": 90, "terminology": 90,
            "ui_appropriateness": 90, "missing_information": False,
            "added_information": False, "placeholder_error": False,
            "html_error": False, "explanation": "ok",
        })

    score_candidate(
        NullProvider(handler=handler),
        source="Hallo", translated="Cześć", locale="pl", language="Polish",
        glossary={}, cfg=cfg, message_key="app.hi",
    )
    judge_prompts = [p for p in prompts if "quality judge" in p]
    assert judge_prompts
    assert "Source (German):" in judge_prompts[0]
    assert "Source (English)" not in judge_prompts[0]


def test_score_model_not_overridden_by_generation_tag(make_config, tmp_path):
    cfg = make_config(tmp_path)
    cfg.score_model = "scorer-pin"
    cfg.improve_model = None
    assert score_model_for(cfg) == "scorer-pin"
    calls: list[str] = []

    def handler(req: CompletionRequest) -> str:
        calls.append(req.model)
        return "Hello"

    provider = NullProvider(handler=handler)
    score_with_backtranslation(
        provider,
        source="Hello", translated="Cześć", locale="pl",
        language="Polish", glossary={}, cfg=cfg, model="translator-tag",
    )
    assert calls == ["scorer-pin"]


def test_judge_parse_fallback(make_config, tmp_path):
    cfg = make_config(tmp_path)
    cfg.judge_model = "judge-test"
    cfg.score_model = "bt-model"

    def handler(req: CompletionRequest) -> str:
        if "judge" in req.prompt.lower():
            return "not-json-at-all"
        return "Hello"

    provider = NullProvider(handler=handler)
    q = score_candidate(
        provider,
        source="Hello", translated="Cześć", locale="pl",
        language="Polish", glossary={}, cfg=cfg,
    )
    assert q.scorer == "bt"
    assert any("judge_parse_failed" in s for s in q.signals)
