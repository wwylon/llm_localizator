"""Translation memory exact + near match (R-06)."""

from __future__ import annotations

import pytest
import json

from llm_localizator.catalog.history import HistoryStore
from llm_localizator.catalog.state import StateStore
from llm_localizator.catalog.tm import TranslationMemory
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import CompletionRequest, NullProvider

from ..conftest import write_json


def setup_project(root, source: dict, *, locale: str = "pl") -> None:
    write_json(root / "messages" / "en" / "app.json", source)
    write_json(root / "messages" / locale / "app.json", {})


def test_tm_exact_hit_skips_provider(project_root, make_config, make_catalog, silent) -> None:
    setup_project(project_root, {"greet": "Hello friend there"})
    cfg = make_config(project_root, tm_dir=project_root / ".llm-tm")
    tm = TranslationMemory(cfg.tm_root())
    tm.record(
        locale="pl",
        source="Hello friend there",
        text="Witaj przyjacielu",
        model="tm-model",
        provider="ollama",
        quality_score=0.95,
    )

    calls: list[CompletionRequest] = []

    def handler(request: CompletionRequest) -> str:
        calls.append(request)
        raise AssertionError("provider must not be called on exact TM hit")

    provider = NullProvider(handler=handler)
    result = run_translation(cfg, make_catalog(cfg), provider, report=silent)
    assert result.written == 1
    assert calls == []
    assert make_catalog(cfg).load("pl", "app")["greet"] == "Witaj przyjacielu"
    entry = StateStore(cfg.state_dir).entry("pl", "app", "greet")
    assert entry is not None
    assert entry["model"] == "tm-model"
    hist = HistoryStore(cfg.history_root()).latest("pl", "app", "greet")
    assert hist is not None
    assert hist.trigger == "tm-hit"


def test_tm_near_match_appears_in_prompt(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(
        project_root,
        {"a": "Please confirm your selection now"},
    )
    cfg = make_config(project_root, tm_dir=project_root / ".llm-tm")
    tm = TranslationMemory(cfg.tm_root())
    tm.record(
        locale="pl",
        source="Please confirm your selection",
        text="Proszę potwierdź swój wybór",
        model="prior",
        quality_score=0.9,
    )

    seen_prompts: list[str] = []

    def handler(request: CompletionRequest) -> str:
        seen_prompts.append(request.prompt)
        if "back to English" in request.prompt:
            return "Please confirm your selection now"
        if request.schema is not None:
            from llm_localizator.providers.null import _numbered_lines
            return json.dumps(
                [f"[xx] {s}" for s in _numbered_lines(request.prompt)],
                ensure_ascii=False,
            )
        return "[xx] " + request.prompt.strip().splitlines()[-1]

    result = run_translation(
        cfg, make_catalog(cfg), NullProvider(handler=handler), report=silent,
    )
    assert result.written == 1
    assert any("Proszę potwierdź swój wybór" in p for p in seen_prompts)


def test_tm_force_bypasses_exact(project_root, make_config, make_catalog, silent) -> None:
    setup_project(project_root, {"greet": "Hello friend there"})
    cfg = make_config(project_root, tm_dir=project_root / ".llm-tm")
    TranslationMemory(cfg.tm_root()).record(
        locale="pl",
        source="Hello friend there",
        text="STALE",
        model="old",
        quality_score=0.99,
    )

    def handler(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            return "Hello friend there"
        if request.schema is not None:
            from llm_localizator.providers.null import _numbered_lines
            return json.dumps(
                [f"[xx] {s}" for s in _numbered_lines(request.prompt)],
                ensure_ascii=False,
            )
        return "[xx] Hello friend there"

    result = run_translation(
        cfg, make_catalog(cfg), NullProvider(handler=handler),
        force=True, report=silent,
    )
    assert result.written == 1
    assert make_catalog(cfg).load("pl", "app")["greet"] == "[xx] Hello friend there"


@pytest.mark.slow
def test_near_index_matches_a_linear_scan(tmp_path) -> None:
    from llm_localizator.catalog.tm import context_hash
    from llm_localizator.core.hash import src_hash
    from llm_localizator.core.quality import token_overlap

    tm = TranslationMemory(tmp_path)
    for i in range(1000):
        source = (
            f"hello friend note{i}" if i % 10 == 0 else f"unrelated cargo {i} crate"
        )
        tm.record(
            locale="pl",
            source=source,
            text=f"t{i}",
            model="m",
            verified=i % 20 == 0,
        )
    query = "hello friend"
    got = tm.near("pl", query, limit=50)
    exact_key = (src_hash(query), context_hash(""))
    scored = []
    for key, entry in tm._ensure_index("pl").items():
        if key == exact_key:
            continue
        overlap = token_overlap(query, entry.source)
        if overlap >= 0.55:
            scored.append((entry, overlap))
    from llm_localizator.catalog.tm import tm_near_sort_key

    scored.sort(key=tm_near_sort_key)
    expect = scored[:50]
    assert [(e.source, e.text, round(score, 6)) for e, score in got] == [
        (e.source, e.text, round(score, 6)) for e, score in expect
    ]
    assert len(got) == 50
    assert len(tm._ensure_index("pl")) == 1000


def test_record_keeps_the_near_index_warm(tmp_path: Path) -> None:
    from pathlib import Path as PathCls
    from unittest.mock import patch

    tm = TranslationMemory(tmp_path)
    tm.record(locale="pl", source="alpha beta", text="a", model="m")
    tm.record(locale="pl", source="gamma delta", text="b", model="m")
    tm.near("pl", "alpha beta", min_overlap=0.1)
    tm.record(locale="pl", source="alpha gamma", text="c", model="m")
    assert tm._near_cache["pl"][0] == tm.path_for("pl").stat().st_mtime_ns
    reads = {"n": 0}
    real = PathCls.read_text

    def counting(self, *args, **kwargs):
        if self.suffix == ".jsonl":
            reads["n"] += 1
        return real(self, *args, **kwargs)

    with patch.object(PathCls, "read_text", counting):
        hits = tm.near("pl", "alpha beta", min_overlap=0.1, limit=10)
    assert reads["n"] == 0
    assert "alpha gamma" in {entry.source for entry, _score in hits}


def test_near_ranking_prefers_the_better_scored_translation_on_a_tie() -> None:
    from llm_localizator.catalog.tm import TMEntry, tm_near_sort_key

    def entry(text: str, quality: float | None, verified: bool = False) -> tuple[TMEntry, float]:
        return TMEntry(
            src_hash="h", source="Save your changes", context_hash="", locale="pl",
            text=text, model="m", quality_score=quality, verified=verified,
        ), 0.9

    rows = [entry("meh", 0.6), entry("best", 0.95), entry("unscored", None)]
    assert [r[0].text for r in sorted(rows, key=tm_near_sort_key)] == ["best", "meh", "unscored"]
    with_verified = rows + [entry("human", 0.2, verified=True)]
    assert sorted(with_verified, key=tm_near_sort_key)[0][0].text == "human"


def test_edit_similarity_bounds() -> None:
    from llm_localizator.catalog.tm import edit_similarity

    assert edit_similarity("abc", "abc") == 1.0
    assert edit_similarity("", "abc") == 0.0
    assert edit_similarity("kitten", "sitting") == 1 - 3 / 7


def test_near_edit_metric_ranks_by_character_distance(tmp_path) -> None:
    from llm_localizator.catalog.tm import TranslationMemory

    tm = TranslationMemory(tmp_path / "tm")
    tm.record(locale="pl", source="Save the file", text="Zapisz plik", model="m")
    tm.record(locale="pl", source="Save the files now please", text="x", model="m")
    hits = tm.near("pl", "Save the file!", metric="edit", min_overlap=0.8)
    assert [e.source for e, _ in hits] == ["Save the file"]
    assert hits[0][1] > 0.9
