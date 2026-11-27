"""Read-only report of hardcoded product strings for an external agent.

The engine does not rewrite consumer source and does not invent keys.
``scan`` still writes usage artefacts; this command writes nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from functools import partial
from datetime import datetime, timezone
from pathlib import Path

from ..projects import ProjectConfig
from ..providers._prompt_utils import parse_json_array
from ..scan import scan_settings, scanner_from_config
from ..scan.tiers import coverage_summary
from ..scan.base import (
    SKIP_DIR_PARTS, SOFT_SKIP_PARTS, HardcodedString, ScanResult, count_unsupported, drop_brand_hits,
)
from .types import AgentHardcodedRequest, OpResult
from ..catalog.io import read_json
from ..projects.paths import project_path

__all__ = ["op_agent_hardcoded", "catalogue_gap_audit", "scan_cache_status"]

# Bump when a scanner change should invalidate every stored per-file result.
_SCAN_VERSION = 71  # bump on any scanner change; history: docs/scanners.md "Scanner versions"

_PROMPT = (
    "List user-visible string literals in this source file that are NOT already "
    "passed to a translation function (t, i18n.t, data-i18n). Any human language. "
    "Reply with a JSON array of objects {{\"text\", \"line\", \"reason\"}}. "
    "If none, reply [].\n\nFILE {path}\n{body}"
)


#: Files that change scan results without being scanned: Go module path (TUI/CLI detection), Apple catalogues and
#: the Xcode project (routed SwiftUI keys), package.json (brand names) — M2, audit ops cache keys.
_SIDE_NAMES = frozenset({"go.mod", "package.json", "project.pbxproj", "Info.plist"})
_SIDE_SUFFIXES = (".strings", ".xcstrings")
_SIDE_SKIP = frozenset({".git", "node_modules", "Pods", "build", "DerivedData", ".build", "Carthage", ".venv", "dist"})


def _collect_side_sigs(root: Path) -> dict[str, str]:
    """Relative path → ``mtime|size`` for side files that affect scan results."""
    import os

    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SIDE_SKIP and not d.startswith(".llm"))
        for name in sorted(filenames):
            if name in _SIDE_NAMES or name.endswith(_SIDE_SUFFIXES):
                try:
                    stat = os.stat(os.path.join(dirpath, name))
                except OSError:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
                out[rel] = f"{stat.st_mtime_ns}|{stat.st_size}"
    return out


def _digest_sigs(sigs: dict[str, str]) -> str:
    digest = hashlib.sha1()
    for rel in sorted(sigs):
        digest.update(f"{rel}|{sigs[rel]}\n".encode("utf-8"))
    return digest.hexdigest()


def _side_files_digest(root: Path) -> str:
    return _digest_sigs(_collect_side_sigs(root))


def _settings_key(cfg: ProjectConfig, adapter: str, side: str | None = None) -> str:
    """Per-file hits are reusable only while these settings and the side files are unchanged.

    *side* is a ``_side_files_digest`` the caller already has (M4: one run walked the tree for it twice).
    """
    return hashlib.sha1(json.dumps(
        [_SCAN_VERSION, *scan_settings(cfg, adapter), side if side is not None else _side_files_digest(Path(cfg.root))],
        default=str,
    ).encode("utf-8")).hexdigest()


def _scan_one(scanner, path: Path, result: ScanResult, store: dict | None, live: dict[str, None], scan_fn) -> None:
    """Scan *path* into *result*, reusing its stored hits when mtime and size match."""
    sig = None
    name = path.as_posix()
    if store is not None:
        try:
            stat = path.stat()
            sig = f"{stat.st_mtime_ns}|{stat.st_size}"
        except OSError:
            return
        live[name] = None
        entry = store.get(name)
        if isinstance(entry, dict) and entry.get("sig") == sig:
            result.files_scanned += int(entry.get("scanned", 0))
            result.suppressed += int(entry.get("suppressed", 0))
            result.hardcoded.extend(HardcodedString(**h) for h in entry.get("hits", []))
            return
    from ..scan.base import scan_file_hits

    suppressed_before = result.suppressed
    kept = scan_file_hits(scanner, path, result, scan_fn)   # the same per-file steps as Scanner.scan (M2)
    if kept is None:
        if store is not None:
            store.pop(name, None)
        return
    if store is not None:
        store[name] = {
            "sig": sig, "scanned": 1, "suppressed": result.suppressed - suppressed_before,
            "hits": [asdict(h) for h in kept],
        }


def _scan_files(
    scanner, limit: int | None, store: dict | None = None,
) -> tuple[ScanResult, list[Path]]:
    from ..scan.usage_calls import EXTRA_ROUTED

    token = EXTRA_ROUTED.set(frozenset(getattr(scanner, "t_functions", ()) or ()))   # [scan] t_functions (M2)
    try:
        return _scan_files_routed(scanner, limit, store)
    finally:
        EXTRA_ROUTED.reset(token)


def _scan_files_routed(
    scanner, limit: int | None, store: dict | None = None,
) -> tuple[ScanResult, list[Path]]:
    result = ScanResult()
    files = list(scanner.iter_files())
    if limit is not None and limit >= 0:
        files = files[:limit]
    seen: set[Path] = set()
    live: dict[str, None] = {}   # cached file names in scan order (the cache rebuilds the hit list from it)
    for path in files:
        seen.add(path)   # the literal pass walks the same tree, so plain equality matches (M4: no resolve())
        _scan_one(scanner, path, result, store, live, scanner.scan_file)
    # Literal languages (Go, Python, ...) are not owned by a framework adapter.
    remaining = None if limit is None or limit < 0 else max(limit - len(files), 0)
    if remaining != 0:
        from ..scan.literals import _literal_paths, scan_literal_file

        for path in _literal_paths(scanner):
            if path in seen:
                continue
            if remaining is not None:
                if remaining == 0:
                    break
                remaining -= 1
            _scan_one(scanner, path, result, store, live, partial(scan_literal_file, scanner))
    if store is not None and (limit is None or limit < 0):
        # Deleted files drop out of the cache. A ``--limit`` run saw only some files, so it prunes nothing (M4: it used
        # to drop every file past the limit, and the next full scan read them all again).
        for stale in set(store) - live.keys():
            del store[stale]
    drop_brand_hits(result, scanner.root)
    if store is not None:
        result.cache_order = list(live)
    return result, files


def _fingerprint(
    cfg: ProjectConfig, scanner, adapter: str, limit: int | None, side: str | None = None,
) -> str:
    """Hash of every scanned file's name, mtime and size plus the scan settings."""
    key, _meta = _fingerprint_with_meta(cfg, scanner, adapter, limit, side)
    return key


def _fingerprint_with_meta(
    cfg: ProjectConfig, scanner, adapter: str, limit: int | None, side: str | None = None,
    *, side_sigs: dict[str, str] | None = None,
) -> tuple[str, dict]:
    """Like ``_fingerprint``, also returning tree/side/dir sigs for incremental status checks."""
    from ..scan.literals import _literal_paths

    scanner.reset_tree()  # fresh walk; _scan_files then reuses it
    root = Path(cfg.root)
    if side_sigs is None:
        side_sigs = _collect_side_sigs(root)
    side_dig = side if side is not None else _digest_sigs(side_sigs)
    digest = hashlib.sha1()
    digest.update(json.dumps(
        [_SCAN_VERSION, limit, *scan_settings(cfg, adapter), side_dig],
        default=str,
    ).encode("utf-8"))
    tree_sigs: dict[str, str] = {}
    dir_mtimes: dict[str, int] = {}
    seen: set[Path] = set()
    for path in list(scanner.iter_files()) + list(_literal_paths(scanner)):
        if path in seen:
            continue
        seen.add(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        name = path.as_posix()
        sig = f"{stat.st_mtime_ns}|{stat.st_size}"
        tree_sigs[name] = sig
        digest.update(f"{name}|{sig}\n".encode("utf-8"))
        parent = path.parent.as_posix()
        if parent not in dir_mtimes:
            try:
                dir_mtimes[parent] = path.parent.stat().st_mtime_ns
            except OSError:
                pass
    meta = {
        "treeSigs": tree_sigs,
        "dirMtimes": dir_mtimes,
        "sideSigs": side_sigs,
        "sideDigest": side_dig,
    }
    return digest.hexdigest(), meta


def _cache_still_fresh(cached: dict, cfg: ProjectConfig, adapter: str) -> bool:
    """True when re-statting known dirs/files proves the cached fingerprint is still valid.

    Directory mtimes catch newly added source files without a full tree walk when
    the OS updates the parent directory on create/delete (Windows and POSIX).
    """
    tree = cached.get("treeSigs")
    dirs = cached.get("dirMtimes")
    side = cached.get("sideSigs")
    if not isinstance(tree, dict) or not isinstance(dirs, dict) or not isinstance(side, dict):
        return False
    for d, want in dirs.items():
        try:
            if Path(d).stat().st_mtime_ns != want:
                return False
        except OSError:
            return False
    for name, want in tree.items():
        try:
            st = Path(name).stat()
            if f"{st.st_mtime_ns}|{st.st_size}" != want:
                return False
        except OSError:
            return False
    root = Path(cfg.root)
    for rel, want in side.items():
        try:
            st = (root / rel).stat()
            if f"{st.st_mtime_ns}|{st.st_size}" != want:
                return False
        except OSError:
            return False
    side_dig = cached.get("sideDigest") or _digest_sigs(side)
    return _settings_key(cfg, adapter, side_dig) == cached.get("settings")


def _cache_path(cfg: ProjectConfig) -> Path:
    return cfg.state_root() / "scan_cache.json"


def _load_cache(cfg: ProjectConfig) -> dict | None:
    try:
        raw = read_json(_cache_path(cfg))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) and "key" in raw else None


def _hit_key(hit: dict) -> str:
    return f"{hit.get('file')}\x1f{hit.get('line')}\x1f{hit.get('text')}"


def _from_files(files: dict, order) -> list[dict]:
    out: list[dict] = []
    for name in order:
        entry = files.get(name)
        if isinstance(entry, dict):
            out.extend(entry.get("hits", []))
    return out


def _cached_hits(stored: dict) -> list[dict]:
    """The hits of a stored scan: the old ``hits`` list, or rebuilt from per-file entries (``order`` + ``dropped``)."""
    if "hits" in stored:
        return list(stored.get("hits") or [])
    dropped = set(stored.get("dropped") or [])
    return [h for h in _from_files(stored.get("files") or {}, stored.get("order") or []) if _hit_key(h) not in dropped]


def _save_cache(
    cfg: ProjectConfig, key: str, result: ScanResult, limit: int | None = None,
    *, settings: str = "", file_store: dict | None = None, meta: dict | None = None,
) -> None:
    payload = {
        "key": key,
        "limit": limit,
        "settings": settings,
        "files": file_store or {},
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filesScanned": result.files_scanned,
        "suppressed": result.suppressed,
    }
    if meta:
        for field in ("treeSigs", "dirMtimes", "sideSigs", "sideDigest"):
            if field in meta:
                payload[field] = meta[field]
    hits = [asdict(hit) for hit in result.hardcoded]
    order = getattr(result, "cache_order", None)
    if file_store and order is not None:
        # M4: each hit is stored once, under its file; the run's list is the files in scan order minus what the brand
        # filter dropped. Kept only when it rebuilds the list exactly (minified-bundle hits have no file entry).
        payload["order"] = list(order)
        payload["dropped"] = sorted({_hit_key(h) for h in _from_files(file_store, order)} - {_hit_key(h) for h in hits})
        if _cached_hits(payload) != hits:
            del payload["order"], payload["dropped"]
    if "order" not in payload:
        payload["hits"] = hits
    try:
        from ..catalog.io import atomic_write_text

        path = _cache_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False))
    except OSError:
        pass


def _flat_locale_path(cfg: ProjectConfig, locale: str) -> Path | None:
    """Path to a flat/nested catalogue file for *locale*, or None if untemplated."""
    template = (cfg.catalog_path or "").replace("\\", "/")
    if "{locale}" not in template:
        return None
    filled = template.replace("{locale}", locale)
    if "{namespace}" in filled:
        filled = filled.replace("{namespace}", "common")
    return cfg.root / filled


def _json_key_count(path: Path | None) -> int | None:
    """Top-level key count for a JSON object file; None if missing/unreadable."""
    if path is None or not path.is_file():
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    return len(data) if isinstance(data, dict) else None


def _en_xx_chrome_status(cfg: ProjectConfig) -> dict:
    """Chrome catalogue parity for the en-XX marker locale."""
    src = cfg.source_locale or "en"
    en_n = _json_key_count(_flat_locale_path(cfg, src))
    xx_n = _json_key_count(_flat_locale_path(cfg, "en-XX"))
    present = xx_n is not None
    lagging = bool(present and en_n is not None and xx_n < en_n) or (
        en_n is not None and en_n > 0 and not present
    )
    return {
        "present": present,
        "keyCount": xx_n,
        "enKeyCount": en_n,
        "lagging": lagging,
    }


def _help_en_xx_status(cfg: ProjectConfig) -> dict | None:
    """Nested help/{locale}.json marker presence when [collections.help] exists."""
    from ..projects.collections import configured_collections

    help_root = None
    for coll in configured_collections(cfg):
        if coll.name == "help" and coll.root is not None:
            help_root = coll.root
            break
    if help_root is None:
        return None
    src = cfg.source_locale or "en"
    en_n = _json_key_count(help_root / f"{src}.json")
    xx_path = help_root / "en-XX.json"
    xx_n = _json_key_count(xx_path)
    present = xx_n is not None
    lagging = bool(present and en_n is not None and xx_n < en_n) or (
        en_n is not None and en_n > 0 and not present
    )
    return {
        "present": present,
        "keyCount": xx_n,
        "enKeyCount": en_n,
        "lagging": lagging,
        "path": (
            str(xx_path.relative_to(cfg.root))
            if xx_path.is_file() and cfg.root in xx_path.parents
            else str(xx_path)
        ),
    }


def latest_qa_report(cfg: ProjectConfig, *, items: int = 0) -> dict | None:
    """The newest ``[qa]`` crawl report under the data home (ADR-119), or ``None``.

    ``items`` > 0 also returns up to that many ``dynamic_text.json`` rows: visible
    English that is no literal in the source (server, API or runtime text).
    """
    import json
    from datetime import datetime, timezone

    try:
        base = Path(cfg.data_root()) / "qa"
    except Exception:  # noqa: BLE001
        return None
    if not base.is_dir():
        return None
    runs = sorted((d for d in base.iterdir() if (d / "summary.json").is_file()), key=lambda d: d.name)
    if not runs:
        return None
    latest = runs[-1]
    try:
        summary = json.loads((latest / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    out = {
        "dir": str(latest), "ts": latest.name,
        "leftovers": summary.get("leftovers", 0), "dynamic": summary.get("dynamic", 0),
        "layout": summary.get("layout", {}),
    }
    try:
        stamp = datetime.strptime(latest.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        out["ageHours"] = round((datetime.now(timezone.utc) - stamp).total_seconds() / 3600, 1)
    except ValueError:
        pass
    if items > 0:
        try:
            dyn = json.loads((latest / "dynamic_text.json").read_text(encoding="utf-8"))
            out["dynamicItems"] = [
                {"page": i.get("page"), "selector": i.get("selector"), "text": i.get("text")}
                for i in (dyn.get("items") or [])[:items]
            ]
        except (OSError, ValueError):
            out["dynamicItems"] = []
    return out


def _hardcoded_next_steps(
    cfg: ProjectConfig,
    *,
    cached: bool,
    stale: bool,
    counts: dict[str, int],
    en_xx: dict,
    help_xx: dict | None,
) -> list[dict[str, str]]:
    """Ordered shell hints for agents / guide."""
    next_steps: list[dict[str, str]] = []
    name = cfg.name or ""
    proj = f" {name}" if name else ""
    high_med = int(counts.get("high") or 0) + int(counts.get("medium") or 0)
    if not cfg.scan_adapter:
        next_steps.append({
            "cmd": "# set [scan] adapter + src_dirs in .llm-localize.toml",
            "why": "No scanner configured",
        })
        return next_steps
    if not cached or stale:
        next_steps.append({
            "cmd": (
                f"llm-localizator agent-hardcoded{proj} --split auto --refresh"
            ),
            "why": "Scan cache missing or stale",
        })
    elif high_med > 0:
        next_steps.append({
            "cmd": (
                f"llm-localizator agent-hardcoded{proj} --split auto --refresh"
            ),
            "why": f"{high_med} high/medium hardcoded hit(s) to wire or decide",
        })
    if high_med > 0:
        next_steps.append({
            "cmd": f"llm-localizator check-keys{proj}",
            "why": "After wiring: every used key must exist in the source catalogue (exit 1 = fix)",
        })
    report = latest_qa_report(cfg)
    if getattr(cfg, "qa", None) is not None:
        if high_med == 0 and cached and not stale and (report is None or report.get("ageHours", 0) > 24):
            next_steps.append({
                "cmd": f"llm-localizator hardcoded-hunt{proj} --serve",
                "why": "Static clear: run the en-XX crawl (ask the user first; it starts the app)",
            })
        if report and report.get("dynamic"):
            next_steps.append({
                "cmd": f"# review {report['dir']}/dynamic_text.json",
                "why": f"{report['dynamic']} visible English string(s) are no literal in the source: "
                       "fix them where the server or API produces them",
            })
        if not next_steps:
            next_steps.append({
                "cmd": f"llm-localizator guide{proj} --json",
                "why": "No hardcoded next step from scan status",
            })
        return next_steps
    qa = list(getattr(cfg, "qa_locales", None) or [])
    if "en-XX" in qa or "en-XA" in qa:
        if en_xx.get("lagging"):
            next_steps.append({
                "cmd": f"llm-localizator pseudo{proj} --locale en-XX",
                "why": "Chrome en-XX lags EN (stale marker looks like hardcoded)",
            })
        if help_xx and help_xx.get("lagging"):
            next_steps.append({
                "cmd": "# regenerate locales/help/en-XX.json (nested help; chrome pseudo skips it)",
                "why": "Help en-XX missing or lags EN help articles",
            })
        if not en_xx.get("lagging") and high_med == 0 and cached and not stale:
            next_steps.append({
                "cmd": (
                    "python experiments/hardcoded_visible/crawl.py --no-serve"
                    if (cfg.root / "experiments" / "hardcoded_visible" / "crawl.py").is_file()
                    else "# browse /en-XX/app… on llm-localizator web"
                ),
                "why": "Static clear — run visual leftover hunt",
            })
    elif cfg.scan_adapter and high_med == 0 and cached and not stale:
        next_steps.append({
            "cmd": "# optional: describe the app in [qa] (docs/configuration.md#qa), then "
                   f"llm-localizator hardcoded-hunt{proj} --serve",
            "why": "Static clear; the en-XX crawl finds what the scanner cannot see (ADR-119)",
        })
    if not next_steps:
        next_steps.append({
            "cmd": f"llm-localizator guide{proj} --json",
            "why": "No hardcoded next step from scan status",
        })
    for step in next_steps:  # C2 (ADR-136): where the agent guide explains the loop
        step.setdefault("guide", "llm-localizator help agent, section 4")
    return next_steps


#: (root, cache path) -> (monotonic time, cache mtime_ns, answer) for ``scan_cache_status(max_age=...)``.
_STATUS_MEMO: dict[tuple[str, str], tuple[float, int, dict]] = {}


def scan_cache_status(cfg: ProjectConfig, *, max_age: float = 0.0) -> dict:
    """Cache age and counts without scanning; ``stale`` when a source file changed since.

    Also reports QA marker readiness (``qaLocales``, ``enXx``, optional ``helpEnXx``)
    and ordered ``next`` command hints for agents.

    *max_age* > 0 reuses an answer that young while the cache file is unchanged (M4: the web dashboard polls this and
    each answer stats every scanned file). The default always computes afresh, so CLI, agents and tests see edits.
    """
    if max_age > 0:
        import copy
        import time

        path = _cache_path(cfg)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = -1
        key = (str(cfg.root), str(path))
        hit = _STATUS_MEMO.get(key)
        now = time.monotonic()
        if hit is not None and now - hit[0] < max_age and hit[1] == mtime:
            return copy.deepcopy(hit[2])
        answer = scan_cache_status(cfg)
        _STATUS_MEMO[key] = (now, mtime, copy.deepcopy(answer))
        return answer
    qa_locales = list(getattr(cfg, "qa_locales", None) or [])
    en_xx = _en_xx_chrome_status(cfg)
    help_xx = _help_en_xx_status(cfg)
    cached = _load_cache(cfg)
    if cached is None:
        counts: dict[str, int] = {}
        next_steps = _hardcoded_next_steps(
            cfg, cached=False, stale=True, counts=counts, en_xx=en_xx, help_xx=help_xx,
        )
        out = {
            "cached": False, "stale": True, "counts": counts, "ts": None,
            "qaLocales": qa_locales, "enXx": en_xx, "next": next_steps,
            "qaCrawl": latest_qa_report(cfg),
        }
        if help_xx is not None:
            out["helpEnXx"] = help_xx
        return out
    stale = True
    adapter = cfg.scan_adapter
    if adapter and cfg.scan_src_dirs:
        try:
            if _cache_still_fresh(cached, cfg, adapter):
                stale = False
            else:
                scanner = scanner_from_config(cfg, adapter)
                stale = _fingerprint(cfg, scanner, adapter, cached.get("limit")) != cached["key"]
        except ValueError:
            pass
    counts = {"high": 0, "medium": 0, "low": 0}
    for hit in _cached_hits(cached):
        level = hit.get("confidence", "medium")
        counts[level] = counts.get(level, 0) + 1
    from ..catalog.scan_decisions import ScanDecisions, hit_id

    live = {hit_id(h.get("file", ""), h.get("text", "")) for h in _cached_hits(cached)}
    next_steps = _hardcoded_next_steps(
        cfg, cached=True, stale=stale, counts=counts, en_xx=en_xx, help_xx=help_xx,
    )
    out = {
        "decisions": ScanDecisions.for_project(cfg).summary(live),
        "cached": True, "stale": stale, "counts": counts, "ts": cached.get("ts"),
        "filesScanned": cached.get("filesScanned", 0), "total": sum(counts.values()),
        "qaLocales": qa_locales, "enXx": en_xx, "next": next_steps,
        "qaCrawl": latest_qa_report(cfg),
    }
    if help_xx is not None:
        out["helpEnXx"] = help_xx
    return out


DEFAULT_HIT_PAGE = 500


def cached_hit_rows(
    cfg: ProjectConfig,
    *,
    offset: int = 0,
    limit: int | None = DEFAULT_HIT_PAGE,
    confidence: str | None = None,
) -> dict:
    """Hits of the last stored scan with decision ids; never scans (W5 findings page).

    ``id`` is :func:`hit_id` (file + text), the id ``scan-decide`` takes. Ignored hits stay in the list so the page can
    show and reset them. ``limit`` defaults to :data:`DEFAULT_HIT_PAGE`; pass ``limit=None`` for every hit.
    """
    from ..catalog.scan_decisions import ScanDecisions, hit_id

    cached = _load_cache(cfg)
    if cached is None:
        return {
            "cached": False, "ts": None, "hits": [], "filesScanned": 0,
            "total": 0, "filteredTotal": 0, "offset": 0, "limit": limit,
        }
    decided = ScanDecisions.for_project(cfg).items()
    hits = []
    for raw in _cached_hits(cached):
        h = dict(raw)
        h["id"] = hit_id(str(h.get("file", "")), str(h.get("text", "")))
        entry = decided.get(h["id"])
        h["decision"] = entry.get("status") if entry else None
        hits.append(h)
    total = len(hits)
    if confidence and confidence != "all":
        hits = [h for h in hits if (h.get("confidence") or "medium") == confidence]
    filtered = len(hits)
    start = max(0, int(offset or 0))
    if limit is None:
        page = hits[start:]
    else:
        page = hits[start:start + max(0, int(limit))]
    return {
        "cached": True, "ts": cached.get("ts"), "hits": page,
        "filesScanned": cached.get("filesScanned", 0),
        "total": total, "filteredTotal": filtered, "offset": start, "limit": limit,
    }


def _parse_llm(raw: str) -> tuple[list[dict], str | None]:
    """Parse a model reply. A non-list JSON value is an error line, not ``[]``."""
    stripped = raw.strip()
    if not stripped:
        return [], None
    # Detect valid JSON that is not a list before attempting array extraction
    if not stripped.startswith("["):
        try:
            val = json.loads(stripped)
            if not isinstance(val, list):
                return [], f"model returned {type(val).__name__}, not a list"
        except json.JSONDecodeError:
            pass
    data = parse_json_array(stripped)
    if data is None:
        return [], None
    items = [
        item for item in data
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return items, None


def _llm_hits(cfg: ProjectConfig, files: list[Path], root: Path, provider) -> tuple[list[dict], list[str]]:
    from ..providers import CompletionRequest, metered_complete

    model = cfg.model_for("")
    hits: list[dict] = []
    notes: list[str] = []
    for path in files:
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        numbered = "\n".join(
            f"{n}: {line}" for n, line in enumerate(body.splitlines()[:400], 1)
        )
        rel = path.relative_to(root).as_posix()
        raw = metered_complete(cfg, provider, "", CompletionRequest(
            prompt=_PROMPT.format(
                path=json.dumps(rel, ensure_ascii=False),
                body=numbered[:8000],
            ),
            model=model,
            timeout_s=120,
        ))
        items, err = _parse_llm(raw or "")
        if err:
            notes.append(f"{rel}: {err}")
        for item in items:
            try:
                line = int(item.get("line") or 1)
            except (TypeError, ValueError):
                line = 1
            hits.append({
                "text": str(item["text"]).strip(),
                "file": rel,
                "line": line,
                "reason": str(item.get("reason") or "local model"),
                "source": "llm",
            })
    return hits, notes


def catalogue_gap_audit(cfg: ProjectConfig) -> tuple[list[dict], list[str]]:
    """Return (gap_records, report_lines) of keys missing in target locales.

    gap_records: [{namespace, locale, key, source_text}]
    report_lines: human-readable markdown section
    """
    from ..catalog import catalog_for

    gaps: list[dict] = []
    lines: list[str] = []
    try:
        cat = catalog_for(cfg)
        namespaces = cat.namespaces()
        targets = list(cfg.targets)
    except Exception as exc:
        return [], [f"Could not audit catalogue: {exc}"]
    if not targets:
        return [], []
    for ns in namespaces:
        try:
            src = cat.load(cfg.source_locale, ns or None)
        except Exception:
            continue
        if not src:
            continue
        for locale in targets:
            try:
                tgt = cat.load(locale, ns or None)
            except Exception:
                tgt = {}
            missing = [k for k in src if k not in tgt or not (tgt.get(k) or "").strip()]
            if not missing:
                continue
            for k in missing:
                gaps.append({"namespace": ns, "locale": locale, "key": k, "source_text": src[k]})
            ns_label = ns or "(default)"
            lines.append(f"## Catalogue gaps: {ns_label} / {locale}  ({len(missing)} keys)")
            lines.append("")
            for k in missing[:20]:
                lines.append(f"  - `{k}`: {src[k][:80]!r}")
            if len(missing) > 20:
                lines.append(f"  … and {len(missing) - 20} more")
            lines.append("")
    if gaps:
        lines.insert(0, f"# Catalogue gaps ({len(gaps)} total missing key-locale pairs)\n")
    return gaps, lines


def _prompt(
    cfg: ProjectConfig, note: str, hits: list[dict], unsupported: dict | None = None, coverage: dict | None = None,
) -> str:
    skips = ", ".join([*SKIP_DIR_PARTS, *SOFT_SKIP_PARTS, "README", "CHANGELOG", "CONTRIBUTING"])
    parts = [
        f"# Hardcoded strings — {cfg.name}",
        "",
        "The engine did not edit these files and will not invent keys.",
        "Add English source strings only, routing each literal through the "
        "project's translation function. Then run `llm-localizator translate` "
        "for the other locales.",
        "",
        f"How to route: {note or 'use the project translation function.'}",
        f"Skipped while scanning: {skips}.",
    ]
    if coverage:
        listed = ", ".join(f"{lang} {info['files']} file(s) [{info['tier']}]" for lang, info in coverage.items())
        parts.append(f"Scanned: {listed}. Tiers: docs/scanners.md.")
    if unsupported:
        listed = ", ".join(f"{ext} ({n})" for ext, n in unsupported.items())
        parts.append(f"NOT scanned (file types no scanner reads; check them by hand): {listed}.")
    parts.append("")
    if not hits:
        parts.append("No hardcoded product strings in the scanned files.")
        return "\n".join(parts).rstrip() + "\n"
    by_file: dict[str, list[dict]] = defaultdict(list)
    for hit in hits:
        by_file[hit["file"]].append(hit)
    for path, rows in by_file.items():
        parts.append(f"## {path}")
        parts.append("")
        for row in rows:
            existing = row.get("existing_key")
            if existing:
                parts.append(
                    f"- {path}:{row['line']}  {row['text']!r}  "
                    f"→ already at `{existing}` (reuse this key, do not create a new one)"
                )
            else:
                parts.append(
                    f"- {path}:{row['line']}  {row['text']!r}  "
                    f"({row['source']}) {row['reason']}"
                )
        parts.append("")
    parts.extend(_dynamic_text_section(cfg))
    return "\n".join(parts).rstrip() + "\n"


def _dynamic_text_section(cfg: ProjectConfig) -> list[str]:
    """Visible English from the latest en-XX crawl that no source literal explains."""
    report = latest_qa_report(cfg, items=40)
    items = (report or {}).get("dynamicItems") or []
    if not items:
        return []
    out = [
        "## Server / runtime text (en-XX crawl)",
        "",
        f"From {report['dir']}: these strings were painted in English but are no literal in "
        "the scanned source. They come from the server, an API response or string building "
        "at runtime. Find the producer and route it there; user data (names, titles, ids) "
        "stays as it is.",
        "",
    ]
    for item in items:
        out.append(f"- {item.get('page')} `{item.get('selector') or ''}`  {item.get('text')!r}")
    if report.get("dynamic", 0) > len(items):
        out.append(f"- … and {report['dynamic'] - len(items)} more in dynamic_text.json")
    out.append("")
    return out


def op_agent_hardcoded(
    cfg: ProjectConfig,
    req: AgentHardcodedRequest,
    *,
    provider=None,
) -> OpResult:
    adapter = req.adapter or cfg.scan_adapter
    if not adapter:
        return OpResult(
            ok=False, exit_code=64, command="agent-hardcoded",
            summary="no scan adapter configured",
            lines=["Set [scan] adapter or pass adapter."],
        )
    if not cfg.scan_src_dirs:
        return OpResult(
            ok=False, exit_code=64, command="agent-hardcoded",
            summary="no [scan] src_dirs configured",
            lines=[],
        )

    if req.llm and req.submit and not req.dry_run and provider is None:
        from ..projects.taskqueue import tq_available, submit

        if tq_available():
            overrides: dict[str, str] = {}
            if req.adapter:
                overrides["--adapter"] = req.adapter
            if req.limit is not None:
                overrides["--limit"] = str(req.limit)
            outcome = submit(cfg, "agent-hardcoded", overrides)
            return OpResult(
                ok=outcome.exit_code == 0,
                exit_code=outcome.exit_code,
                command="agent-hardcoded",
                summary=outcome.message,
                lines=[outcome.message] if outcome.message else [],
                data={"submitted": outcome.exit_code == 0, "taskIds": list(outcome.task_ids)},
            )

    try:
        scanner = scanner_from_config(cfg, adapter)
    except ValueError as exc:
        return OpResult(
            ok=False, exit_code=64, command="agent-hardcoded", summary=str(exc),
        )

    cache_key = None
    cached_at = None
    result = None
    settings = ""
    file_store: dict = {}
    files: list[Path] = []
    cache_meta: dict | None = None
    if not req.llm:
        side_sigs = _collect_side_sigs(Path(cfg.root))
        side = _digest_sigs(side_sigs)
        cache_key, cache_meta = _fingerprint_with_meta(
            cfg, scanner, adapter, req.limit, side, side_sigs=side_sigs,
        )
        stored = None if req.refresh else _load_cache(cfg)
        settings = _settings_key(cfg, adapter, side)
        if stored and stored.get("settings") == settings and isinstance(stored.get("files"), dict):
            file_store = dict(stored["files"])  # unchanged files are not rescanned
        if stored and stored.get("key") == cache_key:
            result = ScanResult(
                files_scanned=int(stored.get("filesScanned", 0)),
                suppressed=int(stored.get("suppressed", 0)),
            )
            result.hardcoded = [HardcodedString(**hit) for hit in _cached_hits(stored)]
            cached_at = stored.get("ts")
            # Refresh incremental meta even on a full cache hit so status can skip walks.
            _save_cache(
                cfg, cache_key, result, req.limit, settings=settings,
                file_store=stored.get("files") if isinstance(stored.get("files"), dict) else file_store,
                meta=cache_meta,
            )
    if result is None:
        result, files = _scan_files(scanner, req.limit, file_store if cache_key else None)
        if cache_key is not None:
            _save_cache(
                cfg, cache_key, result, req.limit, settings=settings, file_store=file_store,
                meta=cache_meta,
            )
    if req.dry_run and req.llm:
        rels = [p.relative_to(cfg.root).as_posix() for p in files]
        return OpResult(
            ok=True, exit_code=0, command="agent-hardcoded",
            summary=f"{len(rels)} file(s) would be sent to the local model",
            lines=rels,
            data={"files": rels, "dryRun": True},
        )

    # Build reverse map source_text → "namespace.key" for existing-key annotation.
    _reverse: dict[str, str] = {}
    try:
        from ..catalog import catalog_for
        _cat = catalog_for(cfg)
        for _ns in _cat.namespaces():
            try:
                _src = _cat.load(cfg.source_locale, _ns or None)
            except Exception:
                continue
            for _key, _text in (_src or {}).items():
                if _text and str(_text).strip():
                    _prefix = f"{_ns}." if _ns else ""
                    _reverse[str(_text).strip()] = f"{_prefix}{_key}"
    except Exception:
        pass

    _CONF_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

    hits = sorted(
        [
            {
                "text": h.text, "file": h.file, "line": h.line,
                "reason": h.reason, "source": "regex",
                "confidence": h.confidence,
                "existing_key": _reverse.get(h.text.strip()),
                **{k: v for k, v in (
                    ("key_hint", h.key_hint), ("note", h.note), ("max_length", h.max_length),
                    ("dnt", h.dnt), ("namespace_hint", h.namespace_hint),
                ) if v},
            }
            for h in result.hardcoded
        ],
        key=lambda h: _CONF_ORDER.get(h.get("confidence", "medium"), 1),
    )
    if req.llm and not req.dry_run:
        # Built only on the model path. The default report never constructs one.
        if provider is None:
            from ..providers import project_provider

            provider = project_provider(cfg)
        seen = {(h["file"], h["line"], h["text"]) for h in hits}
        extra_hits, parse_notes = _llm_hits(cfg, files, scanner.root, provider)
        for extra in extra_hits:
            key = (extra["file"], extra["line"], extra["text"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(extra)
    else:
        parse_notes = []

    from ..catalog.scan_decisions import IGNORED, ScanDecisions, hit_id

    decided = ScanDecisions.for_project(cfg).items()
    for h in hits:
        h["id"] = hit_id(h["file"], h["text"])
        entry = decided.get(h["id"])
        h["decision"] = entry.get("status") if entry else None
        if entry and entry.get("key"):
            h["decidedKey"] = f"{entry.get('namespace')}.{entry['key']}" if entry.get("namespace") else entry["key"]
    decision_counts = ScanDecisions.for_project(cfg).summary({h["id"] for h in hits})
    ignored_hidden = 0
    if not req.show_ignored:
        ignored_hidden = sum(1 for h in hits if h["decision"] == IGNORED)
        hits = [h for h in hits if h["decision"] != IGNORED]
    low_hidden = 0
    if not req.show_low:
        low_hidden = sum(1 for h in hits if h.get("confidence") == "low")
        hits = [h for h in hits if h.get("confidence") != "low"]

    unsupported = count_unsupported(scanner)
    coverage = coverage_summary(scanner)
    prompt = _prompt(cfg, scanner.routing_note, hits, unsupported, coverage)
    if parse_notes:
        prompt = prompt.rstrip() + "\n\n" + "\n".join(parse_notes) + "\n"

    gap_records: list[dict] = []
    if req.catalogue_audit:
        gap_records, gap_lines = catalogue_gap_audit(cfg)
        if gap_lines:
            prompt = prompt.rstrip() + "\n\n" + "\n".join(gap_lines) + "\n"

    hi  = sum(1 for h in hits if h.get("confidence") == "high")
    med = sum(1 for h in hits if h.get("confidence") == "medium")
    lo  = sum(1 for h in hits if h.get("confidence") == "low")
    summary = (
        f"{len(hits)} hardcoded string(s) in {result.files_scanned} file(s)"
        + (f" ({hi} high / {med} medium / {lo} low)" if hits else "")
        + (f", {len(gap_records)} catalogue gap(s)" if gap_records else "")
        + (f", {ignored_hidden} ignored hidden" if ignored_hidden else "")
        + (f", {low_hidden} low hidden" if low_hidden else "")
        + (f", {result.suppressed} suppressed by directive" if result.suppressed else "")
        + (f", {sum(unsupported.values())} file(s) of unsupported types not scanned" if unsupported else "")
    )

    # ADR-105: oversized reports auto-split into agent-sized parts (md + json).
    auto_split = False
    if not req.split and req.fmt != "json":  # JSON callers get every hit inline
        if len(hits) > req.max_hits or len(prompt) > req.budget_tokens * 4:
            auto_split = True
    if req.split or auto_split:
        from .report_split import pack_hits, write_parts

        skips = ", ".join([*SKIP_DIR_PARTS, *SOFT_SKIP_PARTS, "README", "CHANGELOG", "CONTRIBUTING"])
        parts = pack_hits(hits, req.budget_tokens, req.max_hits)
        # Reports go to the engine data home, never into the consumer repo (ADR-112, AGENTS.md).
        out_dir = project_path(cfg.root, req.out_dir) or Path(cfg.data_root()) / "reports" / "hardcoded"
        index = write_parts(
            out_dir, cfg.name, parts, scanner.routing_note, skips,
            write_json=True,
        )
        note = " (auto)" if auto_split else ""
        return OpResult(
            ok=True, exit_code=0, command="agent-hardcoded",
            summary=f"{summary}; {len(parts)} part(s){note} in {out_dir}",
            lines=[f"Wrote {len(parts)} part(s) and index.md to {out_dir}"],
            data={
                "index": index,
                "outDir": str(out_dir),
                "parts": len(parts),
                "autoSplit": auto_split,
                "hits": hits if req.fmt == "json" else None,
                "lowHidden": low_hidden,
            },
        )

    if req.fmt == "json":
        return OpResult(
            ok=True, exit_code=0, command="agent-hardcoded", summary=summary,
            lines=[],
            data={
                "hits": hits,
                "catalogueGaps": gap_records,
                "filesScanned": result.files_scanned,
                "routingNote": scanner.routing_note,
                "cachedAt": cached_at,
                "decisions": decision_counts,
                "ignoredHidden": ignored_hidden,
                "suppressedByDirective": result.suppressed,
                "unsupportedFiles": unsupported,
                "coverage": coverage,
                "applyMode": cfg.apply_mode,
            },
        )

    return OpResult(
        ok=True,
        exit_code=0,
        command="agent-hardcoded",
        summary=summary,
        lines=prompt.splitlines(),
        data={
            "hits": hits,
            "catalogueGaps": gap_records,
            "filesScanned": result.files_scanned,
            "routingNote": scanner.routing_note,
            "cachedAt": cached_at,
            "decisions": decision_counts,
            "ignoredHidden": ignored_hidden,
            "unsupportedFiles": unsupported,
            "coverage": coverage,
            "applyMode": cfg.apply_mode,
            "prompt": prompt,
        },
    )
