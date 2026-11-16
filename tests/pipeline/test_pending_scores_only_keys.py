from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.catalog.state import state_key
from llm_localizator.pipeline import scoring


class _Cat:
    def load(self, locale, ns):
        return {"a": "A", "b": "B"} if locale == "en" else {"a": "Aa", "b": "Bb"}


class _Store:
    def entry(self, *a):
        return None

    def get(self, *a):
        return None


def _collect(monkeypatch, only_keys):
    monkeypatch.setattr(scoring, "_needs_llm_rescore", lambda *a, **k: True)
    cfg = SimpleNamespace(source_locale="en", is_skipped=lambda ns, k, src=None: False, is_request_only=lambda ns, k="": False)
    return scoring.collect_pending_llm_scores(
        cfg, _Cat(), _Store(), _Store(), locales=["pl"], namespaces=["app"], only_keys=only_keys,
    )


def test_all_keys_when_unrestricted(monkeypatch) -> None:
    assert [p.key for p in _collect(monkeypatch, None)] == ["a", "b"]


def test_only_keys_limits_the_scan(monkeypatch) -> None:
    got = _collect(monkeypatch, {"pl": {state_key("app", "b")}})
    assert [p.key for p in got] == ["b"]


def test_only_keys_other_locale_is_empty(monkeypatch) -> None:
    assert _collect(monkeypatch, {"de": {state_key("app", "a")}}) == []
