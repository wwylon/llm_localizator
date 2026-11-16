"""A significant human correction grows the examples file (ADR-52)."""

from __future__ import annotations

import json

from llm_localizator.pipeline.feedback import learn_from_edit
from llm_localizator.projects.context import load_examples


def _cfg(project_root, make_config):
    return make_config(project_root, examples_file=project_root / "examples.json")


def _learn(cfg, **kw):
    args = dict(locale="pl", source="Save", previous="Zapisz zmiany teraz", text="Zapisz", score=0.9)
    args.update(kw)
    return learn_from_edit(cfg, **args)


def test_a_significant_correction_is_appended(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    assert _learn(cfg) is True
    assert load_examples(cfg.examples_file) == {"pl": [("Save", "Zapisz")]}


def test_guards(project_root, make_config) -> None:
    cfg = _cfg(project_root, make_config)
    assert _learn(cfg, previous="Zapisz.", text="Zapisz") is False  # under 20% changed
    assert _learn(cfg, source="x" * 61) is False  # long source
    assert _learn(cfg, score=0.59) is False  # the edit itself looks wrong
    assert _learn(cfg, previous=None) is False  # nothing was there before
    assert _learn(cfg, previous="") is False
    assert not cfg.examples_file.exists()

    assert _learn(cfg) is True
    assert _learn(cfg, text="Zapamiętaj") is False  # this source already has an example
    assert len(json.loads(cfg.examples_file.read_text(encoding="utf-8"))["pl"]) == 1


def test_no_examples_file_means_nothing_happens(project_root, make_config) -> None:
    assert _learn(make_config(project_root)) is False

