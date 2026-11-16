"""Hermetic smoke run of a fresh flat-catalogue consumer (plan Part C, C8).

The shape that broke in production: a json-flat consumer with no target file
yet, batches of one, a frozen locale, ICU plural/select messages and a short
placeholder frame. The fake provider answers like a competent translator
(Polish plural categories, tags kept), so every failure here is the engine's.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import CompletionRequest, NullProvider
from llm_localizator.providers.null import _numbered_lines

SOURCE = {
    "app.save": "Save changes",
    "app.title": "Settings",
    "card.name": "{rank} of {suit}",
    "files.count": "{n, plural, one {# file} other {# files}}",
    "game.result": "{who, select, you {You won} other {They won}}",
    "help.long": "Pick an image, choose a model and press the button to start.",
}
PL_CATEGORIES = ("one", "few", "many", "other")


def _polish(text: str) -> str:
    """A stand-in translator: tag prose, expand ICU plurals to Polish categories."""
    def plural(m: re.Match) -> str:
        head, body = m.group(1), m.group(2)
        branches = dict(re.findall(r"(=?\w+)\s*\{([^{}]*)\}", body))
        base = branches.get("other") or next(iter(branches.values()), "")
        return head + " ".join(f"{c} {{pl {branches.get(c, base)}}}" for c in PL_CATEGORIES) + "}"

    out = re.sub(r"(\{\w+, plural,\s*)((?:=?\w+\s*\{[^{}]*\}\s*)+)\}", plural, text)
    out = re.sub(r"(\{\w+, select,\s*)((?:[\w-]+\s*\{[^{}]*\}\s*)+)\}",
                 lambda m: m.group(1) + re.sub(r"\{([^{}]*)\}", r"{pl \1}", m.group(2)) + "}", out)
    if out == text:
        out = "PL " + text  # plain prose; {placeholders} stay as they are
    return out


def _handler(request: CompletionRequest) -> str:
    if "back to English" in request.prompt:
        return request.prompt.strip().splitlines()[-1].replace("PL ", "", 1)
    if request.schema is not None:
        return json.dumps([_polish(s) for s in _numbered_lines(request.prompt)], ensure_ascii=False)
    return _polish(request.prompt.strip().splitlines()[-1])


@pytest.fixture
def consumer(tmp_path: Path, make_config):
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps(SOURCE, indent=2), encoding="utf-8")
    cfg = make_config(
        tmp_path,
        catalog_format="json-flat",
        catalog_path="locales/{locale}.json",
        targets=["pl", "zh"],
        frozen=["zh"],
        state_dir=tmp_path / ".state",
    )
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    return cfg, catalog


def _run(cfg, catalog, **kw):
    return run_translation(cfg, catalog, NullProvider(handler=_handler), batch_size=1,
                           report=kw.pop("report", lambda *_a, **_k: None), **kw)


def test_fresh_consumer_writes_every_plain_key(consumer) -> None:
    cfg, catalog = consumer
    result = _run(cfg, catalog)
    pl = catalog.load("pl", None)
    for key in ("app.save", "app.title", "help.long"):
        assert pl.get(key, "").startswith("PL "), (key, pl.get(key))
    assert "edited outside" not in json.dumps(getattr(result, "__dict__", {}), default=str)


def test_frozen_locale_is_left_alone_by_default(consumer) -> None:
    cfg, catalog = consumer
    _run(cfg, catalog)
    assert not (cfg.root / "locales" / "zh.json").exists() or catalog.load("zh", None) == {}


def test_frozen_locale_runs_when_named(consumer) -> None:
    cfg, catalog = consumer
    cfg.write_floor = 0.0  # the fake answers "PL …" in zh; this test is about selection
    _run(cfg, catalog, locales=["zh"])
    assert catalog.load("zh", None).get("app.save", "").startswith("PL ")


def test_icu_plural_gets_every_polish_category(consumer) -> None:
    cfg, catalog = consumer
    _run(cfg, catalog)
    value = catalog.load("pl", None).get("files.count", "")
    assert all(f"{c} {{" in value for c in PL_CATEGORIES), value


def test_icu_select_keeps_its_kind_and_arguments(consumer) -> None:
    cfg, catalog = consumer
    _run(cfg, catalog)
    value = catalog.load("pl", None).get("game.result", "")
    assert value.startswith("{who, select,"), value
    assert "{pl You won}" in value, value


def test_placeholder_frame_keeps_placeholders_and_adds_no_prose(consumer) -> None:
    cfg, catalog = consumer
    _run(cfg, catalog)
    value = catalog.load("pl", None).get("card.name", "")
    assert "{rank}" in value and "{suit}" in value, value
    outside = re.sub(r"\{[^{}]*\}", " ", value)
    assert len(re.findall(r"[^\W\d_]+", outside)) <= 4, value


def test_second_run_rewrites_nothing(consumer) -> None:
    cfg, catalog = consumer
    _run(cfg, catalog)
    before = (cfg.root / "locales" / "pl.json").read_text(encoding="utf-8")
    again = _run(cfg, catalog)
    assert again.written == 0
    assert (cfg.root / "locales" / "pl.json").read_text(encoding="utf-8") == before


def test_failed_key_is_rescued_by_the_secondary_model(consumer) -> None:
    """A candidate that keeps failing validation gets one secondary-model try (ADR-21)."""
    from llm_localizator.projects.config import LocaleRole

    cfg, catalog = consumer
    cfg.roles = {"pl": LocaleRole(primary="testmodel", secondary="bigger-model")}
    calls: list[str] = []

    def handler(request: CompletionRequest) -> str:
        calls.append(request.model)
        if "back to English" in request.prompt:
            return request.prompt.strip().splitlines()[-1].replace("PL ", "", 1)
        if request.model == "bigger-model":
            return "PL Zapisz zmiany"
        # The primary model keeps answering with a line break (a hard reject).
        if request.schema is not None:
            return json.dumps(["pl Zapisz\nzmiany" for _ in _numbered_lines(request.prompt)])
        return "pl Zapisz\nzmiany"

    result = run_translation(cfg, catalog, NullProvider(handler=handler), batch_size=1,
                             locales=["pl"], named_keys=["app.save"], force=True,
                             report=lambda *_a, **_k: None)
    assert catalog.load("pl", None).get("app.save") == "PL Zapisz zmiany"
    assert any(e.endswith("app.save") for e in result.escalated), result
    assert "bigger-model" in calls and not result.rejected


def test_forced_rerun_with_a_worse_candidate_keeps_the_current_text(consumer) -> None:
    """E8: a weaker forced rerun used to overwrite a correct translation."""
    from llm_localizator.catalog.drafts import DraftStore

    cfg, catalog = consumer
    _run(cfg, catalog, locales=["pl"])
    before = catalog.load("pl", None)["help.long"]

    def worse(request: CompletionRequest) -> str:
        if "back to English" in request.prompt:
            return "Bananas are yellow and grow on tall plants."
        if request.schema is not None:
            return json.dumps(["Banany rosną na drzewach." for _ in _numbered_lines(request.prompt)])
        return "Banany rosną na drzewach."

    result = run_translation(cfg, catalog, NullProvider(handler=worse), batch_size=1,
                             locales=["pl"], named_keys=["help.long"], force=True,
                             report=lambda *_a, **_k: None)
    assert catalog.load("pl", None)["help.long"] == before
    assert result.held, result
    assert any(d["key"] == "help.long" for d in DraftStore.for_project(cfg).items().values())


# --- ADR-124: whole-message ICU and placeholder frames ---------------------------

WHOLE = "Translate one complete ICU MessageFormat message"
FRAGMENT = "ICU fragment:"


def test_icu_messages_are_translated_whole(consumer) -> None:
    """Plural and select go out as one message; no fragment prompts, nothing icu_failed."""
    cfg, catalog = consumer
    prompts: list[str] = []

    def handler(request: CompletionRequest) -> str:
        prompts.append(f"{request.system or ''}\n{request.prompt}")
        return _handler(request)

    result = run_translation(cfg, catalog, NullProvider(handler=handler), batch_size=1,
                             locales=["pl"], report=lambda *_a, **_k: None)
    pl = catalog.load("pl", None)
    assert pl["files.count"].startswith("{n, plural,")
    assert all(f"{c} {{" in pl["files.count"] for c in PL_CATEGORIES), pl["files.count"]
    assert pl["game.result"].startswith("{who, select,") and "{pl You won}" in pl["game.result"]
    assert sum(WHOLE in p for p in prompts) == 2
    assert not any(FRAGMENT in p for p in prompts)
    assert not result.icu_failed and not result.skipped


def test_rejected_whole_message_falls_back_to_fragments(consumer) -> None:
    cfg, catalog = consumer
    prompts: list[str] = []

    def handler(request: CompletionRequest) -> str:
        prompts.append(request.prompt)
        if WHOLE in (request.system or ""):
            return "{n, select, one {pl plik} other {pl pliki}}"  # select for plural: V47
        return _handler(request)

    result = run_translation(cfg, catalog, NullProvider(handler=handler), batch_size=1,
                             locales=["pl"], named_keys=["files.count"],
                             report=lambda *_a, **_k: None)
    value = catalog.load("pl", None).get("files.count", "")
    assert value.startswith("{n, plural,") and all(f"{c} {{" in value for c in PL_CATEGORIES)
    assert any(FRAGMENT in p for p in prompts)
    assert not result.icu_failed


def test_icu_failure_escalates_then_flags_icu_failed(consumer) -> None:
    """Whole, fragments and the secondary all fail: flagged icu_failed, not a provider skip."""
    from llm_localizator.catalog import FlagStore
    from llm_localizator.projects.config import LocaleRole

    cfg, catalog = consumer
    cfg.roles = {"pl": LocaleRole(primary="testmodel", secondary="bigger-model")}
    cfg.flags_path = cfg.root / ".state" / "flags.jsonl"
    models: list[str] = []

    def handler(request: CompletionRequest) -> str:
        models.append(request.model)
        if "back to English" in request.prompt:
            return "files"
        return "{count, plural, one {plik} other {pliki}}"  # renamed argument, every time

    result = run_translation(cfg, catalog, NullProvider(handler=handler), batch_size=1,
                             locales=["pl"], named_keys=["files.count"],
                             report=lambda *_a, **_k: None)
    assert "files.count" not in catalog.load("pl", None)
    assert len(result.icu_failed) == 1 and result.icu_failed[0].endswith("files.count"), result
    assert not result.skipped and not result.rejected
    assert "bigger-model" in models
    flags = [r for r in FlagStore(cfg.flags_path).rows() if r.get("key") == "files.count"]
    assert flags and flags[-1]["reason"] == "icu_failed", flags


def test_placeholder_frame_prompt_shows_sample_values(consumer) -> None:
    """'{rank} of {suit}' is shown as 'Ace of Spades'; the answer keeps the placeholders."""
    cfg, catalog = consumer
    seen: list[str] = []

    def handler(request: CompletionRequest) -> str:
        if "Ace of Spades" in request.prompt:
            seen.append(request.prompt)
            # A Polish card name is "<rank> <suit>": the frame word disappears.
            return " ".join(t for t in request.prompt.strip().splitlines()[-1].split() if t != "of")
        return _handler(request)

    run_translation(cfg, catalog, NullProvider(handler=handler), batch_size=1,
                    locales=["pl"], named_keys=["card.name"], report=lambda *_a, **_k: None)
    assert seen, "frame prompt did not carry the sample values"
    assert catalog.load("pl", None).get("card.name") == "{rank} {suit}"
