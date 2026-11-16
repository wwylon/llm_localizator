"""bulk-clear --invalid / --latin-leftover on a project seeded with the bridge defects."""

from __future__ import annotations

from llm_localizator.catalog.provenance import provider_of  # noqa: F401  (documents the eligibility rule)
from llm_localizator.catalog.state import StateStore, make_entry
from llm_localizator.ops.dispatch import dispatch_op

from .factory import build_project
from .specs import DEFECTS, SOURCE


def _run(cfg, **body):
    out = dispatch_op(cfg, "bulk-clear", {"dry_run": True, **body}, actor_role="Admin")
    return out, {(k["locale"], k["namespace"], k["key"]): k["why"] for k in (out.get("data") or {}).get("keys", [])}


def test_invalid_lists_exactly_the_hard_defects(tmp_path) -> None:
    cfg = build_project(tmp_path, defects=DEFECTS).config()
    out, picked = _run(cfg, invalid=True)
    assert out["ok"]
    hard = {(d.locale, d.namespace, d.key) for d in DEFECTS if d.cls in {
        "backslash", "foreign-script", "placeholder", "forbidden-term", "html", "plural", "literal"}}
    assert set(picked) == hard
    assert picked[("pl", "app", "resetHint")] == "V39"
    assert picked[("ar", "play", "tableJoin")] == "foreign-script"
    assert picked[("de", "app", "boldNote")] == "V27"


def test_latin_leftover_is_separate_and_advisory_classes_are_not_invalid(tmp_path) -> None:
    cfg = build_project(tmp_path, defects=DEFECTS).config()
    _, invalid = _run(cfg, invalid=True)
    assert ("ar", "app", "signIn") not in invalid  # Latin leftover is advisory (ADR-8)
    _, latin = _run(cfg, latin_leftover=True)
    assert {k for k, why in latin.items() if why == "latin-leftover"} == {("ar", "app", "signIn"), ("ar", "play", "noTables")}


def test_import_rows_stamped_human_are_eligible_but_web_edits_are_not(tmp_path) -> None:
    project = build_project(tmp_path, defects=DEFECTS)
    cfg = project.config()
    store = StateStore(cfg.state_root())
    # the same broken text, once stamped by a person editing in the web UI and once by an import
    store.record("ar", "app", "resetHint", make_entry(SOURCE["app"]["resetHint"], "web", "human", provider="human"))
    store.save_all(["ar"])
    _, picked = _run(cfg, invalid=True)
    assert ("pl", "app", "resetHint") in picked  # provider=import, status human: hand-off copy
    assert ("ar", "app", "resetHint") not in picked  # a real human edit stays


def test_confirm_drops_state_and_keeps_text(tmp_path) -> None:
    project = build_project(tmp_path, defects=DEFECTS)
    cfg = project.config()
    out = dispatch_op(cfg, "bulk-clear", {"invalid": True, "confirm": True}, actor_role="Admin")
    assert out["ok"] and out["data"]["applied"]
    store = StateStore(cfg.state_root())
    assert store.entry("pl", "app", "resetHint") is None
    from llm_localizator.catalog import build_catalog

    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    assert catalog.load("pl", "app")["resetHint"].endswith("\\")  # text stays as a fallback
    again = dispatch_op(cfg, "bulk-clear", {"invalid": True, "dry_run": True}, actor_role="Admin")
    assert again["data"]["count"] == 0


def test_clean_project_has_nothing_to_clear(tmp_path) -> None:
    cfg = build_project(tmp_path).config()
    out, picked = _run(cfg, invalid=True, latin_leftover=True)
    assert out["ok"] and picked == {}
