"""LLM review pass."""

from __future__ import annotations

import json

import pytest

from llm_localizator.catalog import StateStore, make_entry
from llm_localizator.pipeline.review import (
    STATUS_MACHINE,
    STATUS_REJECTED,
    STATUS_REVIEWED,
    run_review,
)
from llm_localizator.providers import NullProvider, ProviderError

from .test_translate import setup_project


def verdicts(*items: dict) -> NullProvider:
    return NullProvider(handler=lambda _r: json.dumps(list(items), ensure_ascii=False))


@pytest.fixture
def seeded(project_root, make_config, make_catalog):
    """A project with two machine-translated keys ready for review."""
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"},
                  existing={"greet": "Witaj", "bye": "Zegnaj"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    for key, src in (("greet", "Hello"), ("bye", "Goodbye")):
        state.record("pl", "app", key, make_entry(src, "testmodel"))
    state.save("pl")
    return cfg, catalog


def test_ok_verdict_promotes_status(seeded, silent) -> None:
    cfg, catalog = seeded
    provider = verdicts({"index": 0, "verdict": "ok"}, {"index": 1, "verdict": "ok"})

    result = run_review(cfg, catalog, provider, locale="pl", report=silent)

    assert result.approved == 2
    state = StateStore(cfg.state_dir)
    assert state.entry("pl", "app", "greet")["status"] == STATUS_REVIEWED


def test_fixed_verdict_rewrites_the_translation(seeded, silent) -> None:
    cfg, catalog = seeded
    provider = verdicts(
        {"index": 0, "verdict": "fixed", "text": "Czesc"},
        {"index": 1, "verdict": "ok"},
    )

    result = run_review(cfg, catalog, provider, locale="pl", report=silent)

    assert result.corrected == 1
    assert catalog.load("pl", "app")["greet"] == "Czesc"


def test_fixed_verdict_records_provenance(seeded, silent) -> None:
    cfg, catalog = seeded
    provider = verdicts({"index": 0, "verdict": "fixed", "text": "Czesc"})

    run_review(cfg, catalog, provider, locale="pl", report=silent)

    from llm_localizator.catalog import ScoreStore
    from llm_localizator.catalog.scores import score_matches_text
    score = ScoreStore(cfg.scores_dir or cfg.root / ".llm-scores").get("pl", "app", "greet")
    assert score is not None and score_matches_text(score, "Czesc")
    history = ((cfg.history_dir or cfg.root / ".llm-history") / "pl.jsonl").read_text(encoding="utf-8")
    assert '"trigger": "review"' in history


def test_reject_verdict_marks_needs_better_model(seeded, silent) -> None:
    cfg, catalog = seeded
    provider = verdicts(
        {"index": 0, "verdict": "reject"}, {"index": 1, "verdict": "ok"},
    )

    result = run_review(cfg, catalog, provider, locale="pl", report=silent)

    assert result.rejected == ["pl/app.greet"]
    state = StateStore(cfg.state_dir)
    assert state.entry("pl", "app", "greet")["status"] == STATUS_REJECTED


def test_invalid_correction_is_not_applied(project_root, make_config, make_catalog, silent) -> None:
    """A reviewer that drops a placeholder must not override the validator."""
    setup_project(project_root, {"greet": "Hello {name}"}, existing={"greet": "Witaj {name}"})
    cfg = make_config(project_root)
    catalog = make_catalog(cfg)
    state = StateStore(cfg.state_dir)
    state.record("pl", "app", "greet", make_entry("Hello {name}", "testmodel"))
    state.save("pl")

    provider = verdicts({"index": 0, "verdict": "fixed", "text": "Czesc"})
    result = run_review(cfg, catalog, provider, locale="pl", report=silent)

    assert result.corrected == 0
    assert catalog.load("pl", "app")["greet"] == "Witaj {name}"
    assert StateStore(cfg.state_dir).entry("pl", "app", "greet")["status"] == STATUS_REJECTED


def test_already_reviewed_keys_are_skipped(seeded, silent) -> None:
    cfg, catalog = seeded
    state = StateStore(cfg.state_dir)
    state.entry("pl", "app", "greet")["status"] = STATUS_REVIEWED
    state.save("pl")

    provider = verdicts({"index": 0, "verdict": "ok"})
    result = run_review(cfg, catalog, provider, locale="pl", report=silent)

    assert result.checked == 1


def test_dry_run_makes_no_calls(seeded, silent) -> None:
    cfg, catalog = seeded
    provider = NullProvider()
    result = run_review(cfg, catalog, provider, locale="pl", dry_run=True, report=silent)
    assert result.checked == 2
    assert provider.call_count == 0
    assert StateStore(cfg.state_dir).entry("pl", "app", "greet")["status"] == STATUS_MACHINE


def test_malformed_verdict_json_is_survivable(seeded, silent) -> None:
    cfg, catalog = seeded
    provider = NullProvider(handler=lambda _r: "not json")
    result = run_review(cfg, catalog, provider, locale="pl", report=silent)
    assert result.approved == 0 and result.corrected == 0


def test_review_emits_progress_lines(seeded) -> None:
    cfg, catalog = seeded
    lines: list[str] = []
    provider = verdicts({"index": 0, "verdict": "ok"}, {"index": 1, "verdict": "ok"})

    run_review(cfg, catalog, provider, locale="pl", report=lines.append)

    assert any("[0/2]" in line for line in lines)
    assert any("(100%)" in line for line in lines)
    assert any("Reviewing 2 key(s)" in line for line in lines)
    assert any("→" in line for line in lines)


def test_timeout_splits_batch_and_retries(seeded, silent) -> None:
    """Oversized review prompts time out — halve the batch and continue."""
    cfg, catalog = seeded
    calls: list[int] = []

    def handler(req):
        calls.append(len(req.prompt))
        # First call covers both keys; force a timeout so we split.
        if len(calls) == 1:
            raise ProviderError("Ollama request failed: timed out")
        # After split, each half is one key — approve.
        return json.dumps([{"index": 0, "verdict": "ok"}], ensure_ascii=False)

    provider = NullProvider(handler=handler)
    result = run_review(
        cfg, catalog, provider, locale="pl", batch_size=2, report=silent,
    )

    assert result.approved == 2
    assert len(calls) == 3  # 1 fail + 2 singles
    assert StateStore(cfg.state_dir).entry("pl", "app", "greet")["status"] == STATUS_REVIEWED


def test_pack_review_batches_respects_char_budget() -> None:
    from llm_localizator.pipeline.review import _pack_review_batches

    items = [
        ("app", "a", "x" * 100, "y" * 100),
        ("app", "b", "x" * 100, "y" * 100),
        ("app", "c", "x" * 1800, "y" * 1800),
    ]
    batches = _pack_review_batches(items, batch_size=10, max_chars=500)
    assert [len(b) for b in batches] == [2, 1]


def test_parse_flags_missing_duplicate_and_out_of_range() -> None:
    from llm_localizator.pipeline.review import _parse

    raw = json.dumps([
        {"index": 1, "verdict": "ok"},
        {"index": 0, "verdict": "ok"},
        {"index": 0, "verdict": "reject"},
        {"index": 7, "verdict": "ok"},
    ])
    out = _parse(raw, 3)
    assert out[0] is None  # duplicated: ambiguous
    assert out[1] == {"index": 1, "verdict": "ok"}  # order does not matter
    assert out[2] is None  # missing


def test_missing_verdict_is_retried_once_then_reported(seeded) -> None:
    cfg, catalog = seeded
    lines: list[str] = []
    calls: list[str] = []

    def handler(req):
        calls.append(req.prompt)
        if len(calls) == 1:
            return json.dumps([{"index": 0, "verdict": "ok"}])  # skips item 1
        return json.dumps([])  # and still does not answer on the retry

    result = run_review(
        cfg, catalog, NullProvider(handler=handler), locale="pl", report=lines.append,
    )
    assert len(calls) == 2  # first pass + one retry of the unanswered item
    assert result.approved == 1
    assert result.unanswered == 1
    assert any("1 not answered" in line for line in lines)


def test_retry_recovers_the_missing_verdict(seeded, silent) -> None:
    cfg, catalog = seeded
    n = {"calls": 0}

    def handler(_req):
        n["calls"] += 1
        if n["calls"] == 1:
            return json.dumps([{"index": 1, "verdict": "ok"}, {"index": 1, "verdict": "ok"}])
        return json.dumps([{"index": 0, "verdict": "ok"}, {"index": 1, "verdict": "ok"}])

    result = run_review(cfg, catalog, NullProvider(handler=handler), locale="pl", report=silent)
    assert result.approved == 2 and result.unanswered == 0


def test_failed_retry_keeps_first_call_verdicts(seeded) -> None:
    cfg, catalog = seeded
    n = {"calls": 0}

    def handler(_req):
        n["calls"] += 1
        if n["calls"] == 1:
            return json.dumps([{"index": 0, "verdict": "ok"}])  # skips item 1
        raise ProviderError("boom")

    result = run_review(
        cfg, catalog, NullProvider(handler=handler), locale="pl", report=lambda _l: None,
    )
    assert result.approved == 1 and result.unanswered == 1


def test_same_model_does_not_re_review_its_own_rejection(seeded, silent) -> None:
    cfg, catalog = seeded
    first = verdicts({"index": 0, "verdict": "reject"}, {"index": 1, "verdict": "ok"})
    run_review(cfg, catalog, first, locale="pl", report=silent)
    again = run_review(cfg, catalog, verdicts(), locale="pl", report=silent)
    assert again.approved == 0 and again.rejected == []  # nothing re-sent
    other = verdicts({"index": 0, "verdict": "ok"})
    bigger = run_review(cfg, catalog, other, locale="pl", model="bigger:70b", report=silent)
    assert bigger.approved == 1
    assert StateStore(cfg.state_dir).entry("pl", "app", "greet").get("rejected_by") is None
