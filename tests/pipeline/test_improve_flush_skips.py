"""improve records TM and keeps scores only for keys its flush wrote (M0, audit ops #10)."""

from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.pipeline import checkpoint
from llm_localizator.pipeline.improve import _Flusher


class _Scores:
    def __init__(self) -> None:
        self.forgotten: list[tuple[str, str, str]] = []
        self.saved: list[str] = []

    def forget(self, locale, namespace, key) -> None:
        self.forgotten.append((locale, namespace, key))

    def save(self, locale) -> None:
        self.saved.append(locale)


def test_skipped_key_gets_no_tm_entry_and_loses_its_score(monkeypatch) -> None:
    monkeypatch.setattr(checkpoint, "flush_pending", lambda *a, **k: SimpleNamespace(
        skipped_external=[("pl", "common", "edited")]))
    scores = _Scores()
    fl = _Flusher(SimpleNamespace(flags_path=None), None, None, None, scores, {}, 10)
    recorded: list[str] = []
    fl.pending_tm.append((("pl", "common", "edited"), lambda: recorded.append("edited")))
    fl.pending_tm.append((("pl", "common", "fine"), lambda: recorded.append("fine")))
    fl.dirty_score_locales.add("pl")
    fl.flush()
    assert recorded == ["fine"]
    assert scores.forgotten == [("pl", "common", "edited")]
    assert scores.saved == ["pl"] and not fl.pending_tm
