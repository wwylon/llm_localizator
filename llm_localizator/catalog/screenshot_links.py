"""Screenshots linked to keys, with optional highlighted regions (C-012, ADR-102).

One JSON file, ``<state>/screenshot_links.json``. A link names an image under the project's
``screenshots/`` context folder, a key, and an optional rectangle as fractions of the image
(0..1), so it survives resizing. The file is advisory metadata: it never feeds state keys,
prompts or the context fingerprint (ADR-7).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .io import atomic_write_text
from .state import now_iso

__all__ = ["SCREENSHOT_LINKS_NAME", "ScreenshotLinks", "link_id", "normalize_region"]

SCREENSHOT_LINKS_NAME = "screenshot_links.json"
MAX_NOTE = 200


def normalize_region(raw: object) -> dict | None:
    """``{x, y, w, h}`` as fractions, from a dict, a list or ``"x,y,w,h"``; ``None`` for no region.

    Raises ``ValueError`` for a region that is malformed or leaves the image.
    """
    if raw in (None, "", [], {}):
        return None
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",")]
    if isinstance(raw, dict):
        raw = [raw.get(k) for k in ("x", "y", "w", "h")]
    try:
        x, y, w, h = (round(float(v), 4) for v in raw)  # type: ignore[union-attr]
    except (TypeError, ValueError) as exc:
        raise ValueError("region needs four numbers: x, y, w, h as fractions of the image") from exc
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001):
        raise ValueError("region must lie inside the image (all values between 0 and 1)")
    return {"x": x, "y": y, "w": w, "h": h}


def link_id(file: str, namespace: str, key: str, region: dict | None) -> str:
    raw = json.dumps([file, namespace, key, region], sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class ScreenshotLinks:
    def __init__(self, state_root: Path) -> None:
        self.path = Path(state_root) / SCREENSHOT_LINKS_NAME

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = data.get("links") if isinstance(data, dict) else None
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def _save(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps({"links": rows}, indent=2, ensure_ascii=False) + "\n")

    def for_key(self, namespace: str, key: str) -> list[dict]:
        return [r for r in self.all() if r.get("namespace") == namespace and r.get("key") == key]

    def add(
        self, file: str, namespace: str, key: str, region: dict | None = None,
        note: str = "", by: str = "",
    ) -> dict:
        """Add a link; the same image, key and region replaces the earlier one."""
        entry = {
            "id": link_id(file, namespace, key, region), "file": file, "namespace": namespace,
            "key": key, "region": region, "note": (note or "").strip()[:MAX_NOTE],
            "by": by or "", "ts": now_iso(),
        }
        rows = [r for r in self.all() if r.get("id") != entry["id"]]
        rows.append(entry)
        self._save(rows)
        return entry

    def remove(self, link: str) -> bool:
        rows = self.all()
        kept = [r for r in rows if r.get("id") != link]
        if len(kept) == len(rows):
            return False
        self._save(kept)
        return True
