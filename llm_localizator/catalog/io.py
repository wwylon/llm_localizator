"""Small persistence helpers shared by catalog and sidecar stores."""

from __future__ import annotations

import errno
import json
import os
import random
import tempfile
import threading
import time
from pathlib import Path

# Windows often denies ``os.replace`` while another handle (web UI, AV, indexer)
# still has the target open. A short backoff retry is enough in practice.
# A locked file should fail in a few seconds, not tens.
_REPLACE_RETRIES = 5
_REPLACE_BASE_DELAY_S = 0.05
_REPLACE_MAX_DELAY_S = 0.4


def _replace_access_denied(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        if exc.errno in (errno.EACCES, errno.EPERM):
            return True
        if getattr(exc, "winerror", None) == 5:
            return True
    return False


def _atomic_replace(src: str, dst: os.PathLike[str] | str) -> None:
    last: BaseException | None = None
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            if not _replace_access_denied(exc):
                raise
            last = exc
            if attempt + 1 >= _REPLACE_RETRIES:
                break
            delay = min(_REPLACE_BASE_DELAY_S * (2**attempt), _REPLACE_MAX_DELAY_S)
            time.sleep(delay + random.uniform(0, _REPLACE_BASE_DELAY_S))
    assert last is not None
    raise PermissionError(
        f"could not replace {dst} (file locked or denied): {last}"
    ) from last


def read_json(path: Path):
    """Parse *path* as UTF-8 JSON. The one place catalogue JSON is decoded."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_json_dict(path: Path) -> dict | None:
    """The JSON object at *path*, or ``None`` when unreadable or not an object."""
    try:
        raw = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def load_json_object(path: Path) -> dict:
    """Read *path* as a JSON object; raise ``ValueError`` on malformed input."""
    try:
        raw = read_json(path)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object at the top level")
    return raw


_APPEND_LOCK = threading.Lock()


def append_text_line(path: Path, line: str) -> None:
    """Append one JSONL *line*, first closing a torn (newline-less) last line.

    A crash mid-append leaves a partial row without ``\\n``; a bare append
    would glue the next row onto it and lose both.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = line if line.endswith("\n") else line + "\n"
    lock_path = path.with_name(path.name + ".lock")
    with _APPEND_LOCK, lock_path.open("a+b") as lock_fh, path.open("a+b") as fh:
        _lock_file(lock_fh)
        try:
            size = fh.seek(0, os.SEEK_END)
            if size:
                fh.seek(size - 1)
                if fh.read(1) != b"\n":
                    text = "\n" + text
            fh.seek(0, os.SEEK_END)
            fh.write(text.encode("utf-8"))
            fh.flush()
        finally:
            _unlock_file(lock_fh)


# Cross-process exclusion for appends: an OS lock on byte 0 (locks past EOF are
# allowed), held only for the torn-tail check and the write.
if os.name == "nt":
    import msvcrt

    def _lock_file(fh) -> None:
        fh.seek(0)
        while True:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.01)

    def _unlock_file(fh) -> None:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock_file(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock_file(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    """Replace *path* atomically after writing the complete payload."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o644
    if path.exists():
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o644
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            if os.environ.get("LLM_LOCALIZE_FSYNC", "").strip() not in ("", "0"):
                os.fsync(handle.fileno())
        _atomic_replace(tmp_name, path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, data, *, indent: int | None = 2, ensure_ascii: bool = False,
                      sort_keys: bool = False, newline: bool = True) -> None:
    """``atomic_write_text`` of ``json.dumps(data)``: a reader never sees half a file (M3)."""
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
    atomic_write_text(path, text + ("\n" if newline else ""))


def rewrite_text_locked(path: Path, text: str) -> None:
    """Atomic rewrite while holding the same cross-process lock as appends.

    Compaction (history/TM/flags/review) must not race with ``append_text_line``.
    Uses a sibling ``.lock`` file so Windows can still ``os.replace`` the target.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with _APPEND_LOCK, lock_path.open("a+b") as fh:
        _lock_file(fh)
        try:
            atomic_write_text(path, text)
        finally:
            _unlock_file(fh)


def update_text_locked(path: Path, transform) -> None:
    """Read, transform and rewrite *path* under the append lock: rows appended meanwhile are not lost.

    ``transform(text) -> text``. Use instead of read → slow work → ``rewrite_text_locked`` when other threads or
    processes append to the same file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with _APPEND_LOCK, lock_path.open("a+b") as fh:
        _lock_file(fh)
        try:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            atomic_write_text(path, transform(current))
        finally:
            _unlock_file(fh)


def decode_import_bytes(raw: bytes) -> str:
    """Decode an uploaded text file: UTF-8 (BOM ok) or BOM-marked UTF-16/32.

    Excel's "Unicode text" export is UTF-16; decoding it as UTF-8 would fail or
    garble every cell.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")
