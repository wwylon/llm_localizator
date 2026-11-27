"""Phase 3 split of _run_improve_locked: keys dropped at flush leave details too (B6)."""

from __future__ import annotations

from types import SimpleNamespace

from llm_localizator.pipeline.improve import ImproveResult, _finish_improve, _ImproveCtx


class _Fl:
    def __init__(self) -> None:
        self.skipped_external_at_flush = 1
        self.skipped_external_keys = [("pl", "app", "a")]

    def has_work(self) -> bool:
        return False


class _Manifest:
    def finish(self, **_k) -> None:
        pass

    def write(self, _root) -> None:
        pass


def test_finish_prunes_details_for_keys_skipped_at_flush(monkeypatch) -> None:
    import llm_localizator.pipeline.improve as imp

    monkeypatch.setattr(imp, "report_run_summary", lambda _m: None)
    result = ImproveResult()
    result.improved = 2
    result.details = ["pl/app.a: 0.50 -> 0.90", "pl/app.ab: 0.40 -> 0.80"]
    ctx = _ImproveCtx(
        cfg=SimpleNamespace(state_root=lambda: None), catalog=None, provider=None,
        scorer=None, result=result, glossary=None, examples_by_locale=None, notes=None,
        state=None, history=None, scores=None, tm=None, improve_model="m", n_samples=1,
        back_translate=None, flagged={}, pending={}, total=2, report=lambda _m: None, fl=_Fl(),
    )
    _finish_improve(ctx, _Manifest())
    assert result.improved == 1
    assert result.details == ["pl/app.ab: 0.40 -> 0.80"]
    assert result.skipped_external_edit == 1
