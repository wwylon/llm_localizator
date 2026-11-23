"""Prompt context (register, gender, group, HTML tags), Markdown fences and frontmatter,
source style checks (V35-V37), review sampling and the source-changed webhook."""

from __future__ import annotations

import json

from llm_localizator.core.source_quality import source_style_findings
from llm_localizator.pipeline.documents import (
    build_section_prompt, is_frontmatter, join_sections, split_sections, translate_document,
)
from llm_localizator.pipeline.prompts import BatchItem, build_batch_prompt, build_single_prompt
from llm_localizator.pipeline.tiers import sampled
from llm_localizator.projects.context import ContextNotes
from llm_localizator.providers import CompletionRequest, NullProvider


# ---- context fields --------------------------------------------------------

def _notes(tmp_path, data):
    (tmp_path / "app.json").write_text(json.dumps(data), encoding="utf-8")
    return ContextNotes(tmp_path)


def test_context_fields_are_read(tmp_path) -> None:
    notes = _notes(tmp_path, {
        "a": {"register": "Formal", "gender": "feminine", "group": "bid"},
        "b": {"group": "bid"},
        "c": {"register": "loud"},
    })
    assert notes.register("app", "a") == "formal"
    assert notes.register("app", "c") is None
    assert notes.register("app", "zzz") is None
    assert notes.gender("app", "a") == "feminine"
    assert notes.group("app", "b") == "bid"
    assert notes.group_keys("app", "bid") == ["a", "b"]


def test_annotations_show_register_gender_and_fragments() -> None:
    item = BatchItem(
        source="was rejected", register="formal", gender="feminine", group="bid",
        group_parts=[("bidBefore", "Your bid")],
    )
    prompt = build_batch_prompt([item], "Polish", "pl", "an app", "")
    assert "[register: formal]" in prompt
    assert "[gender: feminine]" in prompt
    assert "bidBefore: 'Your bid'" in prompt and "one sentence" in prompt


def test_plain_item_has_none_of_those_lines() -> None:
    prompt = build_batch_prompt([BatchItem(source="Save")], "Polish", "pl", "an app", "")
    for token in ("[register", "[gender", "sentence fragment", "Worked example: EN `Click"):
        assert token not in prompt


def test_html_strings_get_a_tag_reorder_example() -> None:
    item = BatchItem(source="Click <b>here</b>", html=True)
    for prompt in (
        build_batch_prompt([item], "German", "de", "an app", ""),
        build_single_prompt(item, "German", "an app", "", locale="de"),
    ):
        assert "Klicken Sie <b>hier</b>" in prompt


# ---- Markdown --------------------------------------------------------------

FENCED = """Intro.

## Real heading

```bash
## not a heading
echo hi
```

## Second

~~~
## also not
~~~
Tail.
"""


def test_heading_inside_a_code_fence_does_not_split() -> None:
    sections = split_sections(FENCED)
    assert [s.splitlines()[0] for s in sections] == ["Intro.", "## Real heading", "## Second"]
    assert "## not a heading" in sections[1]
    assert join_sections(sections) == FENCED


def test_unterminated_fence_swallows_the_rest_rather_than_splitting() -> None:
    text = "## A\n```\n## inside\nstill code\n"
    assert split_sections(text) == [text]


def test_frontmatter_is_its_own_section_and_never_translated(tmp_path) -> None:
    text = "---\ntitle: Terms\nslug: terms\n---\n## Intro\n\nHello.\n"
    sections = split_sections(text)
    assert is_frontmatter(sections[0]) and sections[0].endswith("---\n")
    assert join_sections(sections) == text

    calls: list[str] = []

    def handler(request: CompletionRequest) -> str:
        calls.append(request.prompt)
        return "## Wstep\n\nCzesc.\n\n"

    source = tmp_path / "en.md"
    source.write_text(text, encoding="utf-8")
    target = tmp_path / "pl.md"
    result = translate_document(source, target, "pl", NullProvider(handler=handler), model="m", report=lambda _m: None)
    assert result.ok and len(calls) == 1
    assert "title: Terms" not in calls[0].split("Section:\n", 1)[-1]
    assert target.read_text(encoding="utf-8").startswith("---\ntitle: Terms\nslug: terms\n---\n")


def test_a_lone_rule_is_not_frontmatter() -> None:
    assert not is_frontmatter("---\n")
    assert split_sections("Intro\n\n---\n\nMore\n") == ["Intro\n\n---\n\nMore\n"]


def test_section_prompt_protects_code() -> None:
    prompt = build_section_prompt("## A\n", None, "", "", "Polish", "an app")
    assert "Fenced code blocks" in prompt and "do not wrap the answer" in prompt


# ---- source style ----------------------------------------------------------

def _rows(*texts):
    return [("app", f"k{i}", t) for i, t in enumerate(texts)]


def _codes(findings):
    return sorted((k, c) for _ns, k, c, _m in findings)


def test_fragments_are_flagged_but_ordinary_labels_are_not() -> None:
    found = source_style_findings(_rows(
        "Your bid was", "Terms and", "and the rest", "Log in", "Sort by", "Email:", "Save", " padded label",
        "Sign in to", "Name, ",
    ))
    flagged = {k for k, c in _codes(found) if c == "V35"}
    assert flagged == {"k1", "k2", "k7", "k8"}


def test_mixed_final_period_flags_the_rarer_style() -> None:
    plain = [f"Open item number {n}" for n in range(9)]
    found = source_style_findings(_rows(*plain, "Close the window."))
    assert _codes(found) == [("k9", "V36")]
    assert source_style_findings(_rows(*plain)) == []
    assert source_style_findings(_rows("Wait...", "Open item", "Close now")) == []  # sample too small


def test_serial_comma_mix_flags_the_rarer_style() -> None:
    serial = [f"Red, green {n}, and blue" for n in range(9)]
    found = source_style_findings(_rows(*serial, "Red, green and blue"))
    assert ("k9", "V37") in _codes(found)


def test_validate_emits_the_source_style_codes(project_root, make_config) -> None:
    from llm_localizator.catalog import build_catalog
    from llm_localizator.pipeline.validate import run_validation
    from tests.conftest import setup_project

    setup_project(project_root, {"a": "Terms and", "b": "Save"}, existing={"a": "x", "b": "y"})
    cfg = make_config(project_root)
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    report = run_validation(cfg, catalog, locales=["pl"])
    assert any(f.check == "V35" and f.key == "a" for f in report.findings)


# ---- review sampling / webhook --------------------------------------------

def test_sampling_is_stable_and_proportional() -> None:
    assert sampled(100, "pl", "a", "k") and not sampled(0, "pl", "a", "k")
    keys = [f"key{n}" for n in range(1000)]
    picked = [k for k in keys if sampled(30, "pl", "a", k)]
    assert 200 < len(picked) < 400
    assert picked == [k for k in keys if sampled(30, "pl", "a", k)]


def test_review_sample_percent_is_validated(tmp_path) -> None:
    import pytest

    from llm_localizator.projects.config import ConfigError, load_config

    path = tmp_path / ".llm-localize.toml"
    path.write_text('[project]\nname = "x"\n[review]\nsample_percent = 40\n', encoding="utf-8")
    assert load_config(path).review_sample_percent == 40
    path.write_text('[project]\nname = "x"\n[review]\nsample_percent = 140\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_sync_diff_posts_a_source_changed_event(project_root, make_config, monkeypatch) -> None:
    from llm_localizator.ops.dispatch import dispatch_op
    from tests.conftest import setup_project

    # Untranslated copies of the source are backlog; a differing value with no record is an existing translation.
    setup_project(project_root, {"a": "A", "b": "B"}, existing={"a": "A", "b": "B"})
    cfg = make_config(project_root, notify_webhook="http://127.0.0.1:9/hook")
    seen: list[dict] = []
    monkeypatch.setattr("llm_localizator.ops.notify.notify_webhook", lambda url, payload, **_kw: seen.append(payload))
    dispatch_op(cfg, "sync", {"dry_run": False, "diff": True, "no_translate": True, "locales": ["pl"]}, actor_role="Admin")
    events = [p for p in seen if p.get("event") == "source.changed"]
    assert events and events[0]["project"] == cfg.name
