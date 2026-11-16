from llm_localizator.ops.catalogue_gaps import iter_catalogue_gaps
from llm_localizator.ops.places import op_places
from llm_localizator.projects import load_config
from tests.synth.factory import build_project


def _cfg(proj):
    return load_config(proj.config().config_path)


def test_set_never_skips_place_and_unset_restores(tmp_path):
    proj = build_project(tmp_path)
    cfg = proj.config()
    before = {g.namespace for g in iter_catalogue_gaps(cfg, reasons=["missing", "stale", "no_state", "external_edit", "empty"])}
    assert op_places(cfg, "list").data["places"]
    out = op_places(cfg, "set", "app", "never")
    assert out.ok, out.summary
    cfg2 = _cfg(proj)
    assert cfg2.place_policy("app", "x") == "never" and cfg2.is_skipped("app", "x")
    assert "app" not in {g.namespace for g in iter_catalogue_gaps(cfg2)}
    assert op_places(cfg2, "unset", "app").ok
    assert _cfg(proj).place_policy("app") == "auto"
    assert before is not None


def test_key_glob_is_more_specific_and_bad_policy_rejected(tmp_path):
    proj = build_project(tmp_path)
    cfg = proj.config()
    assert op_places(cfg, "set", "app", "request").ok
    assert op_places(cfg, "set", "app:save*", "never").ok
    c = _cfg(proj)
    assert c.place_policy("app", "saveAll") == "never" and c.place_policy("app", "cancel") == "request"
    assert not op_places(cfg, "set", "app", "bogus").ok


def test_request_place_is_only_translated_when_named(tmp_path):
    from llm_localizator.catalog import StateStore, build_catalog
    from llm_localizator.pipeline.translate import collect_work

    proj = build_project(tmp_path)
    cfg = proj.config()
    d = tmp_path / "messages" / "en" / "app.json"
    import json
    data = json.loads(d.read_text(encoding="utf-8"))
    data["brandNew"] = "Brand new"
    d.write_text(json.dumps(data), encoding="utf-8")
    assert op_places(cfg, "set", "app", "request").ok
    cfg = _cfg(proj)
    cat = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    st = StateStore(cfg.state_dir)
    assert collect_work(cfg, cat, st, locales=["pl"], namespaces=["app"]) == []
    cfg.places.clear()
    assert collect_work(cfg, cat, st, locales=["pl"], namespaces=["app"])  # auto again: brandNew is work


def test_review_place_gets_review_tier(tmp_path):
    from llm_localizator.pipeline.tiers import TIER_REVIEW, tier_for
    from llm_localizator.projects import ContextNotes

    proj = build_project(tmp_path)
    assert op_places(proj.config(), "set", "app", "review").ok
    cfg = _cfg(proj)
    assert tier_for(cfg, ContextNotes(cfg.context_dir), "app", "save") == TIER_REVIEW


def test_request_place_helper_is_false_for_auto_and_true_for_request(tmp_path):
    proj = build_project(tmp_path)
    cfg = proj.config()
    assert not cfg.is_request_only("app", "save")
    assert op_places(cfg, "set", "app", "request").ok
    cfg = _cfg(proj)
    assert cfg.is_request_only("app", "save")
    assert not cfg.is_request_only("play", "x")


def _request_cfg(tmp_path):
    proj = build_project(tmp_path)
    assert op_places(proj.config(), "set", "app", "request").ok
    return _cfg(proj)


def test_rescore_skips_request_place_unless_keys_are_named(tmp_path):
    from llm_localizator.catalog import ScoreStore, StateStore, build_catalog
    from llm_localizator.ops.rescore import collect_rescore_items

    cfg = _request_cfg(tmp_path)
    cat = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    args = (cfg, cat, StateStore(cfg.state_dir), ScoreStore(cfg.scores_dir))
    assert collect_rescore_items(*args, locales=["pl"], namespaces=["app"]) == []
    named = collect_rescore_items(*args, locales=["pl"], namespaces=["app"], keys=["app.cancel"])
    assert [i.key for i in named] == ["cancel"]


def test_improve_skips_request_place(tmp_path):
    from llm_localizator.catalog import HistoryStore, ScoreStore, StateStore, build_catalog
    from llm_localizator.pipeline.improve import collect_improve_keys

    cfg = _request_cfg(tmp_path)
    cat = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    got = collect_improve_keys(cfg, cat, StateStore(cfg.state_dir), ScoreStore(cfg.scores_dir),
                               locales=["pl"], namespaces=["app"], limit=50)
    assert got == []
