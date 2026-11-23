"""A cloud scorer back-translates in big parallel requests; a local one keeps small serial batches."""

from __future__ import annotations

import json
import threading

from llm_localizator.catalog import ScoreStore
from llm_localizator.pipeline.scoring import PendingScoreItem, rescore_items


class _FakeScorer:
    """Back-translates by echoing the source text; records request sizes and threads."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.last_usage = None
        self.sizes: list[int] = []
        self.threads: set[int] = set()
        self.copies = 0
        self._lock = threading.Lock()

    def __copy__(self):
        clone = _FakeScorer(self.kind)
        clone.sizes, clone.threads, clone._lock = self.sizes, self.threads, self._lock
        with self._lock:
            self.copies += 1
        return clone

    def complete(self, request):
        with self._lock:
            self.sizes.append(len(request.source_texts))
            self.threads.add(threading.get_ident())
        return json.dumps([f"back {t}" for t in request.source_texts])


def _items(n: int) -> list[PendingScoreItem]:
    return [PendingScoreItem("pl", "app", f"k{i}", f"Source {i}", f"Cel {i}") for i in range(n)]


def _run(make_config, project_root, tmp_path, kind, n, **overrides):
    cfg = make_config(project_root, scores_dir=tmp_path / "scores", score_model="scoremodel", judge_risky=False, **overrides)
    provider = _FakeScorer(kind)
    store = ScoreStore(tmp_path / "scores")
    updated, _ = rescore_items(provider, cfg, store, {}, _items(n))
    return provider, store, updated


def test_cloud_scorer_uses_big_batches_and_every_key_is_scored(project_root, make_config, tmp_path) -> None:
    provider, store, updated = _run(
        make_config, project_root, tmp_path, "anthropic", 120, translate_cloud_batch_size=50,
    )
    assert sorted(provider.sizes) == [20, 50, 50]
    assert updated == 120
    assert all(store.get("pl", "app", f"k{i}") is not None for i in range(120))
    assert provider.copies == 3  # one provider copy per request, so usage is never shared


def test_cloud_batch_size_can_be_set_for_the_scorer_only(project_root, make_config, tmp_path) -> None:
    provider, _, _ = _run(
        make_config, project_root, tmp_path, "anthropic", 60,
        translate_cloud_batch_size=50, bt_cloud_batch_size=30,
    )
    assert sorted(provider.sizes) == [30, 30]


def test_local_scorer_keeps_small_serial_batches(project_root, make_config, tmp_path) -> None:
    provider, _, updated = _run(make_config, project_root, tmp_path, "ollama", 12)
    assert provider.sizes == [5, 5, 2]
    assert provider.copies == 0
    assert len(provider.threads) == 1
    assert updated == 12


def test_one_worker_scores_serially(project_root, make_config, tmp_path) -> None:
    provider, _, updated = _run(
        make_config, project_root, tmp_path, "anthropic", 100, translate_cloud_batch_size=50, bt_workers=1,
    )
    assert provider.copies == 0 and updated == 100


def _prefetched(make_config, project_root, tmp_path, items, scorer, **overrides):
    from llm_localizator.pipeline.scoring import BtPrefetcher

    cfg = make_config(project_root, scores_dir=tmp_path / "scores", score_model="scoremodel", judge_risky=False,
                      translate_cloud_batch_size=50, **overrides)
    pre = BtPrefetcher(cfg, scorer, "scoremodel", lambda _m: None)
    pre.submit(items)
    store = ScoreStore(tmp_path / "scores")
    return cfg, pre, store


def test_prefetched_back_translations_are_used_and_not_repeated(project_root, make_config, tmp_path) -> None:
    items = _items(30)
    scorer = _FakeScorer("anthropic")
    cfg, pre, store = _prefetched(make_config, project_root, tmp_path, items, scorer)
    pre._pool.shutdown(wait=True)
    calls_after_prefetch = len(scorer.sizes)
    updated, _ = rescore_items(scorer, cfg, store, {}, items, prefetcher=pre)
    assert updated == 30
    assert calls_after_prefetch == 1 and len(scorer.sizes) == 1  # phase B made no BT call of its own
    assert all(store.get("pl", "app", f"k{i}") is not None for i in range(30))


def test_prefetch_is_ignored_when_the_text_changed(project_root, make_config, tmp_path) -> None:
    items = _items(10)
    scorer = _FakeScorer("anthropic")
    cfg, pre, store = _prefetched(make_config, project_root, tmp_path, items, scorer)
    changed = [PendingScoreItem(i.locale, i.namespace, i.key, i.source, i.translated + "!") for i in items]
    assert not pre.covers(changed)
    updated, _ = rescore_items(scorer, cfg, store, {}, changed, prefetcher=pre)
    pre._pool.shutdown(wait=True)
    assert updated == 10 and len(scorer.sizes) == 2  # the prefetch, then one inline request


def test_failed_prefetch_falls_back_to_an_inline_request(project_root, make_config, tmp_path) -> None:
    items = _items(10)

    class Flaky(_FakeScorer):
        def __copy__(self):
            clone = Flaky(self.kind)
            clone.sizes, clone.threads, clone._lock = self.sizes, self.threads, self._lock
            clone.broken = True
            return clone

        broken = False

        def complete(self, request):
            if self.broken:
                raise RuntimeError("boom")
            return super().complete(request)

    scorer = Flaky("anthropic")
    cfg, pre, store = _prefetched(make_config, project_root, tmp_path, items, scorer)
    pre._pool.shutdown(wait=True)
    assert pre.get(items) is None
    updated, _ = rescore_items(scorer, cfg, store, {}, items, prefetcher=pre)
    assert updated == 10 and len(scorer.sizes) == 1


def test_phase_b_judges_short_labels_like_the_inline_path(project_root, make_config, tmp_path, monkeypatch) -> None:
    """judge_risky (default on): one- and two-word keys go to the judge, not to back-translation alone."""
    from llm_localizator.pipeline import scoring
    from llm_localizator.core.quality import QualityResult

    judged: list[str] = []

    def fake_candidate(provider, *, source, **kwargs):
        judged.append(source)
        return QualityResult(0.5, ["judged"], {}, scorer="lqs")

    monkeypatch.setattr(scoring, "score_candidate", fake_candidate)
    cfg = make_config(project_root, scores_dir=tmp_path / "scores", score_model="scoremodel")
    items = [
        PendingScoreItem("pl", "app", "a", "Download result", "Wynik pobierania"),
        PendingScoreItem("pl", "app", "b", "Please choose a model for this image", "Wybierz model dla obrazu"),
    ]
    rescore_items(_FakeScorer("ollama"), cfg, ScoreStore(tmp_path / "scores"), {}, items)
    assert judged == ["Download result"]


def test_cloud_judge_calls_for_short_keys_run_in_parallel(project_root, make_config, tmp_path, monkeypatch) -> None:
    import threading

    from llm_localizator.core.quality import QualityResult
    from llm_localizator.pipeline import scoring

    seen_threads: set[int] = set()
    barrier = threading.Barrier(2, timeout=5)

    def fake_candidate(provider, *, source, **kwargs):
        barrier.wait()  # only passes when two judge calls are in flight at once
        seen_threads.add(threading.get_ident())
        return QualityResult(0.9, [], {}, scorer="lqs")

    monkeypatch.setattr(scoring, "score_candidate", fake_candidate)
    cfg = make_config(project_root, scores_dir=tmp_path / "scores", score_model="scoremodel")
    items = [PendingScoreItem("pl", "app", f"k{i}", "Save", f"Zapisz {i}") for i in range(2)]
    updated, _ = rescore_items(_FakeScorer("anthropic"), cfg, ScoreStore(tmp_path / "scores"), {}, items)
    assert updated == 2 and len(seen_threads) == 2
