"""The flush guard must not treat a new key or the run's own English fill as an outside edit.

Regression: a consumer's first pl translate wrote 0/204 ("198 edited outside
the run") because the target file did not exist yet (baseline "" vs on-disk
None) and an earlier flush had filled pending keys with the source text.
"""

from __future__ import annotations

from llm_localizator.pipeline.checkpoint import _filter_external_edits


class _Catalog:
    source_locale = "en"

    def __init__(self, data: dict) -> None:
        self.data = data

    def invalidate(self) -> None:
        pass

    def load(self, locale, ns):
        return dict(self.data.get((locale, ns), {}))


def _run(on_disk_pl: dict, baselines: dict) -> tuple[dict, list]:
    catalog = _Catalog({("en", "app"): {"a": "Save", "b": "Open"}, ("pl", "app"): on_disk_pl})
    pending = {("app", "pl"): {"a": "Zapisz", "b": "Otwórz"}}
    return _filter_external_edits(catalog, pending, {("app", "pl"): baselines})


def test_missing_target_with_empty_baseline_is_written() -> None:
    kept, skipped = _run({}, {"a": "", "b": None})
    assert kept == {("app", "pl"): {"a": "Zapisz", "b": "Otwórz"}}
    assert skipped == []


def test_english_fill_from_an_earlier_flush_is_not_an_edit() -> None:
    kept, skipped = _run({"a": "Save", "b": "Open"}, {"a": None, "b": ""})
    assert kept == {("app", "pl"): {"a": "Zapisz", "b": "Otwórz"}}
    assert skipped == []


def test_real_outside_edit_is_still_skipped() -> None:
    kept, skipped = _run({"a": "Zachowaj", "b": "Open"}, {"a": None, "b": "Open"})
    assert kept == {("app", "pl"): {"b": "Otwórz"}}
    assert skipped == [("pl", "app", "a")]
