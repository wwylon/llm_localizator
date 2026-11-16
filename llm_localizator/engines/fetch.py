"""Download engine files from the project site (ADR-156, A4).

``index.json`` at the base URL lists ``{"engines": [{"id", "file", "sha256"}]}``; each file is fetched without
following redirects, capped at :data:`MAX_BYTES`, checked against the index hash, then parsed by
:func:`llm_localizator.engines.parse_engine`, which refuses any setting outside the allowlist (no privacy, budget, URL or
key can come from the network).

The index and the files come from the same host, so the index hash alone proves nothing about origin. What *is*
trusted is this package: a downloaded file whose hash equals a file shipped in this release is ``verified``. Anything
else is ``unverified`` and is only written with ``accept_unverified``. Built-in ids are never replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import _BUILTIN, EngineError, parse_engine, user_engine_dir

__all__ = ["DEFAULT_URL", "MAX_BYTES", "FetchRow", "build_index", "fetch_engines", "shipped_hashes"]

DEFAULT_URL = "https://llm-localizator.dev/engines/"
MAX_BYTES = 64 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib hook
        return None


@dataclass
class FetchRow:
    id: str
    status: str            # new | same | updated | builtin | rejected
    verified: bool = False
    detail: str = ""
    written: bool = False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def shipped_hashes() -> set[str]:
    """sha256 of every engine file shipped in this package (the trust anchor)."""
    return {_sha(p.read_bytes()) for p in _BUILTIN.glob("*.toml")}


def build_index(src: Path = _BUILTIN, out: Path | None = None) -> dict:
    """The ``index.json`` for a directory of engine files (written next to copies of them when ``out`` is given)."""
    rows = []
    for path in sorted(src.glob("*.toml")):
        data = path.read_bytes()
        parse_engine(data.decode("utf-8"), source=str(path), expect_id=path.stem)
        rows.append({"id": path.stem, "file": path.name, "sha256": _sha(data)})
        if out is not None:
            out.mkdir(parents=True, exist_ok=True)
            (out / path.name).write_bytes(data)
    index = {"version": 1, "engines": rows}
    if out is not None:
        (out / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


def _get(url: str, opener, timeout: float) -> bytes:
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        raise EngineError(f"refusing non-HTTPS engine URL {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "llm-localizator-engine-fetch"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise EngineError(f"{url}: HTTP {resp.status}")
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise EngineError(f"{url}: HTTP {exc.code} (redirects are not followed)") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise EngineError(f"{url}: {exc}") from exc
    if len(data) > MAX_BYTES:
        raise EngineError(f"{url}: larger than {MAX_BYTES} bytes")
    return data


def fetch_engines(
    base_url: str | None = None, *, write: bool = False, accept_unverified: bool = False,
    dest: Path | None = None, timeout: float = 10.0, opener=None,
) -> list[FetchRow]:
    """Fetch the index and every engine it lists; write new or changed ones to ``dest`` only when ``write``."""
    base = (base_url or os.environ.get("LLM_LOCALIZE_ENGINE_URL") or DEFAULT_URL).rstrip("/") + "/"
    opener = opener or urllib.request.build_opener(_NoRedirect())
    dest = dest or user_engine_dir()
    try:
        index = json.loads(_get(base + "index.json", opener, timeout).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise EngineError(f"{base}index.json is not valid JSON: {exc}") from exc
    entries = index.get("engines") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        raise EngineError(f"{base}index.json has no engines list")
    trusted = shipped_hashes()
    builtin_ids = {p.stem for p in _BUILTIN.glob("*.toml")}
    rows: list[FetchRow] = []
    for entry in entries:
        engine_id = str((entry or {}).get("id") or "")
        name = str((entry or {}).get("file") or "")
        if not engine_id or name != f"{engine_id}.toml" or "/" in name or "\\" in name:
            rows.append(FetchRow(engine_id or "?", "rejected", detail=f"bad index entry {entry!r}"))
            continue
        if engine_id in builtin_ids:
            rows.append(FetchRow(engine_id, "builtin", verified=True, detail="shipped with this release"))
            continue
        try:
            data = _get(base + name, opener, timeout)
            if _sha(data) != str(entry.get("sha256") or ""):
                raise EngineError("sha256 does not match index.json")
            parse_engine(data.decode("utf-8"), source=base + name, expect_id=engine_id)
        except (EngineError, UnicodeDecodeError) as exc:
            rows.append(FetchRow(engine_id, "rejected", detail=str(exc)))
            continue
        verified = _sha(data) in trusted
        target = dest / name
        old = target.read_bytes() if target.is_file() else None
        status = "new" if old is None else ("same" if old == data else "updated")
        row = FetchRow(engine_id, status, verified=verified,
                       detail="" if verified else "not shipped in this release: check it before use")
        if write and status != "same" and (verified or accept_unverified):
            dest.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            row.written = True
        rows.append(row)
    return rows
