"""Shared mtime-cached JSON store base for per-locale sidecar files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .io import atomic_write_text, load_json_object

__all__ = ["LocaleJsonStore"]


class LocaleJsonStore:
    """One JSON file per locale under a shared directory, with mtime caching."""

    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        # locale → (mtime_ns or -1 when missing, payload)
        self._cache: dict[str, tuple[int, dict]] = {}
        # locale → (mtime_ns, text) of our last write, so a flush that saves
        # every locale does not rewrite one whose payload did not change.
        self._written: dict[str, tuple[int, str]] = {}
        # locale → JSON text as last read / written (three-way merge base).
        # Keeping the text avoids ``copy.deepcopy`` of large score/state maps
        # on every cache miss — that dominated review-ticket and cold-load
        # latency when many ScoreStore instances each re-parsed the same file.
        self._base_text: dict[str, str] = {}

    def path_for(self, locale: str) -> Path:
        return self.dir / f"{locale}.json"

    def load(self, locale: str) -> dict:
        path = self.path_for(locale)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = -1
        hit = self._cache.get(locale)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        if mtime < 0:
            payload: dict = {}
            self._base_text[locale] = "{}"
        else:
            text = path.read_text(encoding="utf-8")
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} is not valid JSON: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"{path} must contain a JSON object at the top level")
            payload = raw
            self._base_text[locale] = text
        self._cache[locale] = (mtime, payload)
        return payload

    def invalidate(self) -> None:
        self._cache.clear()
        self._written.clear()
        self._base_text.clear()

    def save(self, locale: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(locale)
        data = self._merge_external(locale, self.load(locale))
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        last = self._written.get(locale)
        if last is not None and last[1] == text and last[0] >= 0:
            try:
                st = path.stat()
                untouched = (st.st_mtime_ns, st.st_size) == (last[0], len(text.encode("utf-8")))
            except OSError:
                untouched = False
            if untouched:
                return  # unchanged payload over a file nobody else touched
        atomic_write_text(path, text)
        try:
            atomic_write_text(self._seal_path(locale), hashlib.sha256(text.encode("utf-8")).hexdigest() + "\n")
        except OSError:
            pass  # the seal is advisory
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = -1
        self._cache[locale] = (mtime, data)
        self._written[locale] = (mtime, text)
        self._base_text[locale] = text

    def _seal_path(self, locale: str) -> Path:
        return self.dir / f"{locale}.json.sha256"

    def integrity_issues(self) -> list[str]:
        """Locales whose file no longer matches the checksum of our last save (hand edit or damage).

        A missing seal is a legacy file and is fine; the next save creates it. Advisory only.
        """
        issues: list[str] = []
        for seal in sorted(self.dir.glob("*.json.sha256")):
            target = seal.with_suffix("")  # drops ".sha256"
            try:
                want = seal.read_text(encoding="utf-8").strip()
                have = hashlib.sha256(target.read_bytes()).hexdigest()
            except OSError:
                continue
            if want != have:
                issues.append(target.name)
        return issues

    def _merge_external(self, locale: str, data: dict) -> dict:
        """Three-way merge when the file changed on disk since we read it.

        Keys we changed win; keys someone else added or edited survive instead of
        being overwritten by a stale in-memory copy (out-of-band edits, plan Part 7).
        """
        cached = self._cache.get(locale)
        path = self.path_for(locale)
        try:
            disk_mtime = path.stat().st_mtime_ns
        except OSError:
            return data
        if cached is None or cached[0] in (-1, disk_mtime):
            return data
        last = self._written.get(locale)
        if last is not None and last[0] == disk_mtime:
            return data
        try:
            disk = load_json_object(path)
        except Exception as exc:  # noqa: BLE001 - refuse overwrite on any read failure
            # Refuse to overwrite disk with a stale in-memory copy when the
            # on-disk JSON is unreadable (corruption / partial write).
            raise ValueError(
                f"cannot merge {path}: disk JSON unreadable ({exc})"
            ) from exc
        try:
            raw_base = json.loads(self._base_text.get(locale, "{}"))
            base = raw_base if isinstance(raw_base, dict) else {}
        except json.JSONDecodeError:
            base = {}
        merged = dict(disk)
        for key in set(base) | set(data):
            if data.get(key) != base.get(key):
                if key in data:
                    merged[key] = data[key]
                else:
                    merged.pop(key, None)
        data.clear()
        data.update(merged)
        return data

    def save_all(self, locales: list[str] | None = None) -> None:
        for locale in locales if locales is not None else list(self._cache):
            self.save(locale)
