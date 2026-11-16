"""Cross-locale hard-key report."""

from __future__ import annotations

import re

from llm_localizator.catalog import ScoreStore
from llm_localizator.ops.hard_keys import collect_hard_keys, op_hard_keys
from llm_localizator.ops.types import HardKeysRequest

_PCT_RE = re.compile(r"\((\d+(?:\.\d+)?)%\)")


def test_collect_hard_keys_source_hard(project_root, make_config, make_catalog) -> None:
    setup = _scores_fixture(project_root, make_config, make_catalog)
    keys = collect_hard_keys(
        setup["cfg"], setup["catalog"], setup["scores"],
        locales=["pl", "de", "fr", "cs"],
        namespaces=["app"],
        threshold=0.7,
        min_locales=4,
    )
    tags = {row["key"]: row["tag"] for row in keys}
    assert tags.get("ambiguous") == "source_hard"


def test_collect_hard_keys_locale_outlier(project_root, make_config, make_catalog) -> None:
    setup = _scores_fixture(project_root, make_config, make_catalog)
    keys = collect_hard_keys(
        setup["cfg"], setup["catalog"], setup["scores"],
        locales=["pl", "de", "fr", "cs"],
        namespaces=["app"],
        threshold=0.7,
        min_locales=4,
    )
    tags = {row["key"]: row["tag"] for row in keys}
    assert tags.get("locale_specific") == "locale_outlier"


def test_op_hard_keys_emits_taskqueue_progress(
    project_root, make_config, make_catalog, capsys,
) -> None:
    setup = _scores_fixture(project_root, make_config, make_catalog)
    result = op_hard_keys(
        setup["cfg"],
        HardKeysRequest(threshold=0.7, min_locales=4, dry_run=True),
        report=print,
    )
    assert result.ok
    out = capsys.readouterr().out
    assert _PCT_RE.search(out)
    assert "TQ_METRIC" in out


def _scores_fixture(project_root, make_config, make_catalog):
    from tests.pipeline.test_translate import setup_project

    setup_project(
        project_root,
        {
            "ambiguous": "Save your changes",
            "locale_specific": "Continue",
            "ok": "Settings",
        },
    )
    cfg = make_config(project_root, scores_dir=project_root / ".llm-scores")
    catalog = make_catalog(cfg)
    scores = ScoreStore(cfg.scores_dir)

    def record(locale: str, key: str, score: float) -> None:
        scores.record(locale, "app", key, score=score, signals=[], text=key)

    for loc in ("pl", "de", "fr", "cs"):
        record(loc, "ambiguous", 0.55)
    record("pl", "locale_specific", 0.5)
    for loc in ("de", "fr", "cs"):
        record(loc, "locale_specific", 0.9)
    for loc in ("pl", "de", "fr", "cs"):
        record(loc, "ok", 0.95)
    scores.save_all(["pl", "de", "fr", "cs"])
    return {"cfg": cfg, "catalog": catalog, "scores": scores}
