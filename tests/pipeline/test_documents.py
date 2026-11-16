"""Section-level document translation.

Ported from bridge's ``test_localize_documents.py``. The all-or-nothing failure
policy is the important one: a partially translated privacy policy looks
authoritative and is wrong, so a single failed section must remove the whole
locale file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.pipeline.documents import (
    join_sections,
    split_sections,
    translate_document,
)
from llm_localizator.providers import CompletionRequest, NullProvider

DOC = """Preamble text before any heading.

## First section

Body of the first section.

## Second section

Body of the second section.
"""


def faithful(request: CompletionRequest) -> str:
    """Translate by prefixing the body, preserving the heading line."""
    section = request.prompt.split("Section:\n", 1)[-1]
    lines = section.splitlines()
    if lines and lines[0].startswith("## "):
        return lines[0] + "\n[xx] " + "\n".join(lines[1:]).strip() + "\n\n"
    return "[xx] " + section.strip() + "\n\n"


@pytest.fixture
def provider() -> NullProvider:
    return NullProvider(handler=faithful)


@pytest.fixture
def doc(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "en" / "terms.md"
    source.parent.mkdir(parents=True)
    source.write_text(DOC, encoding="utf-8")
    return source, tmp_path / "pl" / "terms.md"


# ---- splitting -------------------------------------------------------------

def test_preamble_is_section_zero() -> None:
    sections = split_sections(DOC)
    assert sections[0].startswith("Preamble")
    assert sections[1].startswith("## First")
    assert len(sections) == 3


def test_no_headings_is_a_single_section() -> None:
    assert split_sections("Just prose.") == ["Just prose."]


def test_empty_document_has_no_sections() -> None:
    assert split_sections("") == []


def test_join_round_trips_content() -> None:
    assert join_sections(split_sections(DOC)) == DOC


def test_join_skips_empty_sections() -> None:
    assert join_sections(["a\n", "", "   ", "b\n"]) == "a\nb\n"


# ---- first run -------------------------------------------------------------

def test_first_run_translates_every_section(doc, provider) -> None:
    source, target = doc
    state: dict = {}
    result = translate_document(source, target, "pl", provider,
                                model="m", state=state, report=lambda _: None)

    assert result.ok
    assert result.translated == 3 and result.reused == 0
    assert target.exists()
    assert "[xx]" in target.read_text(encoding="utf-8")
    assert len(state) == 3


def test_headings_survive_translation(doc, provider) -> None:
    source, target = doc
    translate_document(source, target, "pl", provider, model="m",
                       state={}, report=lambda _: None)
    text = target.read_text(encoding="utf-8")
    assert "## First section" in text and "## Second section" in text


# ---- incremental runs ------------------------------------------------------

def test_unchanged_document_reuses_everything(doc, provider) -> None:
    source, target = doc
    state: dict = {}
    translate_document(source, target, "pl", provider, model="m",
                       state=state, report=lambda _: None)
    calls_after_first = provider.call_count

    result = translate_document(source, target, "pl", provider, model="m",
                                state=state, report=lambda _: None)

    assert result.reused == 3 and result.translated == 0
    assert provider.call_count == calls_after_first, "no model calls for an unchanged document"


def test_edited_section_retranslates_only_itself(doc, provider) -> None:
    source, target = doc
    state: dict = {}
    translate_document(source, target, "pl", provider, model="m",
                       state=state, report=lambda _: None)
    before = provider.call_count

    source.write_text(DOC.replace("Body of the first section.",
                                  "Body of the first section, amended."), encoding="utf-8")
    result = translate_document(source, target, "pl", provider, model="m",
                                state=state, report=lambda _: None)

    assert result.translated == 1 and result.reused == 2
    assert provider.call_count - before == 1


# ---- all-or-nothing failure ------------------------------------------------

def test_failed_section_removes_the_whole_target(doc, provider) -> None:
    source, target = doc
    state: dict = {}
    translate_document(source, target, "pl", provider, model="m",
                       state=state, report=lambda _: None)
    assert target.exists()

    source.write_text(DOC.replace("Second section", "Second section POISON"),
                      encoding="utf-8")
    failing = NullProvider(fail_on="POISON")
    result = translate_document(source, target, "pl", failing, model="m",
                                state=state, report=lambda _: None)

    assert not result.ok
    assert not target.exists(), "a partial legal document must not be served"
    assert result.removed == target
    assert state, "finished sections are kept so the next run resumes after them"
    retry = translate_document(source, target, "pl", provider, model="m",
                               state=state, report=lambda _: None)
    assert retry.ok and retry.reused == 2 and retry.translated == 1


def test_empty_translation_counts_as_failure(doc) -> None:
    source, target = doc
    provider = NullProvider(handler=lambda r: "   ")
    result = translate_document(source, target, "pl", provider, model="m",
                                state={}, report=lambda _: None)
    assert not result.ok
    assert not target.exists()


def test_failure_on_first_ever_run_leaves_no_file(doc) -> None:
    source, target = doc
    result = translate_document(source, target, "pl", NullProvider(fail_on="Section"),
                                model="m", state={}, report=lambda _: None)
    assert not result.ok
    assert not target.exists()


# ---- dry run ---------------------------------------------------------------

def test_dry_run_writes_nothing(doc, provider) -> None:
    source, target = doc
    result = translate_document(source, target, "pl", provider, model="m",
                                state={}, dry_run=True, report=lambda _: None)
    assert not target.exists()
    assert provider.call_count == 0
    assert result.translated == 3


# ---- prompt construction ---------------------------------------------------

def test_previous_translation_is_offered_as_an_update_target(doc, provider) -> None:
    source, target = doc
    state: dict = {}
    translate_document(source, target, "pl", provider, model="m",
                       state=state, report=lambda _: None)

    source.write_text(DOC.replace("Body of the first", "Body of the very first"),
                      encoding="utf-8")
    provider.calls.clear()
    translate_document(source, target, "pl", provider, model="m",
                       state=state, report=lambda _: None)

    assert "earlier translation" in provider.calls[0].prompt


def test_neighbouring_sections_are_supplied_as_context(doc, provider) -> None:
    source, target = doc
    translate_document(source, target, "pl", provider, model="m",
                       state={}, report=lambda _: None)
    middle = provider.calls[1].prompt
    assert "Neighbouring sections" in middle
    assert "do NOT translate" in middle


class _Warmable(NullProvider):
    def __init__(self, keep_alive, **kw) -> None:
        super().__init__(**kw)
        self.keep_alive = keep_alive
        self.warmups = 0

    def ensure_ready(self, model, *, report=None) -> None:
        self.warmups += 1


def test_recent_call_skips_the_per_section_warmup(doc, monkeypatch) -> None:
    from llm_localizator.pipeline import documents as documents_mod

    monkeypatch.setattr(documents_mod, "_now", lambda: 100.0)  # clock never moves
    source, target = doc
    provider = _Warmable("30m", handler=faithful)
    result = translate_document(source, target, "pl", provider, model="m", report=lambda _: None)
    assert result.ok and result.translated == 3
    assert provider.warmups == 1  # the initial one only


def test_stale_window_rewarms_before_a_section(doc, monkeypatch) -> None:
    from llm_localizator.pipeline import documents as documents_mod

    tick = iter(range(0, 10**6, 2000))  # 2000 s per reading: past keep_alive/2
    monkeypatch.setattr(documents_mod, "_now", lambda: float(next(tick)))
    source, target = doc
    provider = _Warmable("30m", handler=faithful)
    translate_document(source, target, "pl", provider, model="m", report=lambda _: None)
    assert provider.warmups == 4  # initial + one per section


def test_zero_keep_alive_always_rewarms(doc, monkeypatch) -> None:
    from llm_localizator.pipeline import documents as documents_mod

    monkeypatch.setattr(documents_mod, "_now", lambda: 100.0)
    source, target = doc
    provider = _Warmable(0, handler=faithful)
    translate_document(source, target, "pl", provider, model="m", report=lambda _: None)
    assert provider.warmups == 4


def test_reuse_follows_the_source_hash_when_sections_move(doc, provider) -> None:
    source, target = doc
    state: dict = {}
    translate_document(source, target, "pl", provider, model="m",
                       state=state, report=lambda _: None)
    source.write_text(
        DOC.replace("## First section", "## Inserted\n\nNew.\n\n## First section"),
        encoding="utf-8",
    )
    result = translate_document(source, target, "pl", provider, model="m",
                                state=state, report=lambda _: None)
    assert result.translated == 1 and result.reused == 3
    assert "Body of the second section." in target.read_text(encoding="utf-8")


def test_structurally_broken_section_is_a_failure(doc) -> None:
    source, target = doc
    bad = NullProvider(handler=lambda r: "no heading marker here\n\n")
    result = translate_document(source, target, "pl", bad, model="m",
                                state={}, report=lambda _: None)
    assert not result.ok and not target.exists()


def test_validate_section_flags_lost_urls_and_fences() -> None:
    from llm_localizator.pipeline.documents import validate_section

    assert validate_section("## A\nsee https://x.io/a.", "## B\nsiehe https://x.io/a.") is None
    assert "URL" in validate_section("see https://x.io/a", "siehe https://x.io/b")
    assert "fence" in validate_section("```\ncode\n```\n", "code\n")


def test_result_carries_a_per_section_report(doc, provider) -> None:
    source, target = doc
    state: dict = {}
    first = translate_document(source, target, "pl", provider, model="m",
                               state=state, report=lambda _: None)
    assert [r["status"] for r in first.report] == ["translated"] * 3
    again = translate_document(source, target, "pl", provider, model="m",
                               state=state, report=lambda _: None)
    assert [r["status"] for r in again.report] == ["reused"] * 3


def test_failed_section_is_reported_with_its_problem(doc) -> None:
    source, target = doc
    bad = NullProvider(handler=lambda r: "no heading marker here\n\n")
    result = translate_document(source, target, "pl", bad, model="m",
                                state={}, report=lambda _: None)
    assert result.report[-1]["status"] == "failed" and "heading" in result.report[-1]["problem"]


def test_document_ids_include_html(tmp_path: Path) -> None:
    from llm_localizator.ops.documents import document_ids, resolve_document_path

    en = tmp_path / "en"
    en.mkdir()
    (en / "terms.md").write_text("## A\n", encoding="utf-8")
    help_dir = en / "help"
    help_dir.mkdir()
    (help_dir / "blackjack.html").write_text(
        "<html><body><h1>Blackjack</h1><p>Rules.</p></body></html>\n",
        encoding="utf-8",
    )
    assert document_ids(en) == ["help/blackjack", "terms"]
    html = resolve_document_path(en, "help/blackjack")
    assert html is not None and html.suffix == ".html"
    assert resolve_document_path(en, "terms").suffix == ".md"


def test_execute_documents_translates_html(tmp_path: Path, make_config, provider) -> None:
    from llm_localizator.ops.documents import execute_documents

    root = tmp_path
    help_en = root / "help" / "en"
    help_en.mkdir(parents=True)
    (help_en / "game.html").write_text(
        "<html><body><p>Hello rules.</p></body></html>\n", encoding="utf-8",
    )
    cfg = make_config(root, documents_dir=root / "help", targets=["pl"])
    out = execute_documents(cfg, locales=["pl"], docs=["game"], doc_dir=root / "help")
    assert out.ok, out.summary
    target = root / "help" / "pl" / "game.html"
    assert target.is_file()
    assert "Hello" in target.read_text(encoding="utf-8") or "[xx]" in target.read_text(encoding="utf-8")


def test_validate_document_reports_ok_invalid_and_missing(doc, provider) -> None:
    from llm_localizator.pipeline.documents import validate_document

    source, target = doc
    translate_document(source, target, "pl", provider, model="m",
                       state={}, report=lambda _: None)
    assert {r["status"] for r in validate_document(source, target)} == {"ok"}
    text = target.read_text(encoding="utf-8").replace("## Second", "Second", 1)
    target.write_text(text.split("Second")[0], encoding="utf-8")
    rows = validate_document(source, target)
    assert rows[-1]["status"] == "missing"
    assert validate_document(source, target.with_name("nope.md"))[0]["status"] == "missing"
