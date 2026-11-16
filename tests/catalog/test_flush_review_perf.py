"""Write-through flush journal and append-only review queue enqueue."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from llm_localizator.catalog.flush_journal import FlushIntent, FlushJournal, flush_block_message
from llm_localizator.catalog.mutation_lock import mutation_lock
from llm_localizator.catalog.review_queue import STATUS_BLOCKED, STATUS_DONE, ReviewQueue


def _intent() -> FlushIntent:
    return FlushIntent(run_id="r", started_at="2026-01-01T00:00:00Z",
                       locales=["pl"], pending_keys=3, phase="started")


def test_set_phase_does_not_reread_file(tmp_path: Path, monkeypatch) -> None:
    j = FlushJournal(tmp_path)
    j.begin(_intent())
    monkeypatch.setattr(FlushJournal, "read",
                        lambda self: pytest.fail("set_phase re-read the journal"))
    for phase in ("catalog", "state", "scores", "history"):
        j.set_phase(phase)
    monkeypatch.undo()
    assert json.loads(j.path.read_text(encoding="utf-8"))["phase"] == "history"


def test_crash_mid_flush_is_recovered_by_new_instance(tmp_path: Path) -> None:
    j = FlushJournal(tmp_path)
    j.begin(_intent())
    j.set_phase("catalog")
    j.set_phase("state")  # crash here: nothing after
    fresh = FlushJournal(tmp_path)
    left = fresh.interrupted()
    assert left is not None and left.phase == "state"
    assert left.locales == ["pl"] and left.pending_keys == 3
    assert "phase=state" in (flush_block_message(tmp_path) or "")
    assert fresh.acknowledge() is True
    assert fresh.interrupted() is None


def test_progress_record_survives_and_does_not_block(tmp_path: Path) -> None:
    j = FlushJournal(tmp_path)
    j.begin(_intent())
    j.set_phase("done")
    j.note_progress([("pl", "ui", "a"), ("pl", "ui", "b")])
    other = FlushJournal(tmp_path)
    assert other.last_finished_key() == ("pl", "ui", "b")
    assert other.interrupted() is None


def test_set_phase_after_external_delete_is_noop(tmp_path: Path) -> None:
    j = FlushJournal(tmp_path)
    j.begin(_intent())
    FlushJournal(tmp_path).acknowledge()
    j.set_phase("catalog")
    assert not j.path.exists()


def test_checkpoint_failure_leaves_blocking_phase(tmp_path: Path) -> None:
    j = FlushJournal(tmp_path)
    j.begin(_intent())
    try:
        j.set_phase("catalog")
        raise RuntimeError("disk full")
    except RuntimeError:
        pass
    assert FlushJournal(tmp_path).interrupted().phase == "catalog"


def test_enqueue_appends_without_rewrite(tmp_path: Path, monkeypatch) -> None:
    q = ReviewQueue(tmp_path / "q")
    first = q.enqueue(locale="pl", namespace="ui", key="a", reason="r")
    monkeypatch.setattr(ReviewQueue, "_rewrite",
                        lambda *a, **k: pytest.fail("rewrote on new ticket"))
    second = q.enqueue(locale="pl", namespace="ui", key="b", reason="r")
    lines = q.path_for("pl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["id"] for x in lines] == [first.id, second.id]
    assert ReviewQueue(tmp_path / "q").find_open("pl", "ui", "b").id == second.id


def test_enqueue_dedup_refreshes_and_rewrites(tmp_path: Path) -> None:
    q = ReviewQueue(tmp_path / "q", {"ui.*": "bob"})
    t1 = q.enqueue(locale="pl", namespace="ui", key="a", reason="r1", source="S")
    t2 = q.enqueue(locale="pl", namespace="ui", key="a", reason="r2")
    assert t1.id == t2.id and t2.reason == "r2" and t2.source == "S"
    assert len(q.path_for("pl").read_text(encoding="utf-8").splitlines()) == 1
    q.set_status("pl", t1.id, STATUS_DONE)
    t3 = q.enqueue(locale="pl", namespace="ui", key="a", reason="r3")
    assert t3.id != t1.id
    assert len(ReviewQueue(tmp_path / "q").list_tickets("pl")) == 2


def test_enqueue_many_dedups_within_batch_and_across_locales(tmp_path: Path) -> None:
    q = ReviewQueue(tmp_path / "q")
    out = q.enqueue_many([
        {"locale": "pl", "namespace": "ui", "key": "a", "reason": "x"},
        {"locale": "pl", "namespace": "ui", "key": "a", "reason": "y"},
        {"locale": "de", "namespace": "ui", "key": "a", "reason": "x",
         "status": STATUS_BLOCKED},
    ])
    assert out[0].id == out[1].id and out[0].reason == "y"
    assert out[2].status == STATUS_BLOCKED
    fresh = ReviewQueue(tmp_path / "q")
    assert len(fresh.list_tickets("pl")) == 1 and len(fresh.list_tickets("de")) == 1
    assert q.enqueue_many([]) == []


def test_corrupted_trailing_line_is_isolated(tmp_path: Path) -> None:
    q = ReviewQueue(tmp_path / "q")
    a = q.enqueue(locale="pl", namespace="ui", key="a", reason="r")
    path = q.path_for("pl")
    with path.open("ab") as fh:
        fh.write(b'{"id": "torn", "locale": "pl", "ke')  # no newline: torn write
    fresh = ReviewQueue(tmp_path / "q")
    b = fresh.enqueue(locale="pl", namespace="ui", key="b", reason="r")
    again = ReviewQueue(tmp_path / "q")
    ids = [t.id for t in again.list_tickets("pl")]
    assert ids == [a.id, b.id]


def test_concurrent_appends_under_mutation_lock(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(10):
                with mutation_lock(lock, timeout_s=30):
                    ReviewQueue(tmp_path / "q").enqueue(
                        locale="pl", namespace="ui", key=f"k{n}-{i}", reason="r")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    tickets = ReviewQueue(tmp_path / "q").list_tickets("pl")
    assert len(tickets) == 40 and len({t.id for t in tickets}) == 40
