"""Crash-injection and concurrent-writer tests for the shared write primitives."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from llm_localizator.catalog import io as cio


def test_failed_write_keeps_old_content_and_leaves_no_temp(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "a.json"
    target.write_text('{"old": 1}', encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(cio.os, "replace", boom)
    with pytest.raises(OSError):
        cio.atomic_write_text(target, '{"new": 2}')
    assert target.read_text(encoding="utf-8") == '{"old": 1}'
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_crash_while_writing_payload_leaves_target_untouched(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "a.json"
    target.write_text("old", encoding="utf-8")

    real_fdopen = cio.os.fdopen

    class Exploding:
        def __init__(self, handle):
            self._h = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._h.close()

        def write(self, text):
            self._h.write(text[: len(text) // 2])
            raise KeyboardInterrupt

    monkeypatch.setattr(cio.os, "fdopen", lambda *a, **k: Exploding(real_fdopen(*a, **k)))
    with pytest.raises(KeyboardInterrupt):
        cio.atomic_write_text(target, "x" * 1000)
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_torn_jsonl_tail_is_closed_before_next_append(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_bytes(b'{"a": 1}\n{"b": ')  # crash mid-row
    cio.append_text_line(path, json.dumps({"c": 3}))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[-1]) == {"c": 3}


@pytest.mark.slow
def test_concurrent_atomic_writers_never_expose_a_partial_file(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    cio.atomic_write_text(target, json.dumps({"n": 0}))
    stop = threading.Event()
    bad: list[str] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                json.loads(target.read_text(encoding="utf-8"))
            except FileNotFoundError:
                bad.append("missing")
            except json.JSONDecodeError as exc:
                bad.append(str(exc))
            except PermissionError:
                pass  # Windows: replace in flight
            stop.wait(0.001)

    def writer(i: int) -> None:
        for j in range(25):
            cio.atomic_write_text(target, json.dumps({"n": i * 100 + j, "pad": "x" * 5000}))

    r = threading.Thread(target=reader)
    ws = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    r.start()
    for w in ws:
        w.start()
    for w in ws:
        w.join()
    stop.set()
    r.join()
    assert not bad
    assert "n" in json.loads(target.read_text(encoding="utf-8"))
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


@pytest.mark.slow
def test_concurrent_appenders_lose_no_rows(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"

    def writer(i: int) -> None:
        for j in range(50):
            cio.append_text_line(path, json.dumps({"w": i, "j": j}))

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 200
    assert {(r["w"], r["j"]) for r in rows} == {(i, j) for i in range(4) for j in range(50)}


def _proc_writer(path: str, i: int) -> None:
    for j in range(40):
        cio.append_text_line(Path(path), json.dumps({"w": i, "j": j, "pad": "y" * 300}))


@pytest.mark.slow
def test_concurrent_processes_lose_no_rows(tmp_path: Path) -> None:
    import multiprocessing as mp

    path = tmp_path / "log.jsonl"
    ctx = mp.get_context("spawn")
    ps = [ctx.Process(target=_proc_writer, args=(str(path), i)) for i in range(3)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {(r["w"], r["j"]) for r in rows} == {(i, j) for i in range(3) for j in range(40)}
