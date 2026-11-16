"""Per-git-branch state/scores isolation (W-10). Catalogues stay shared.

Source strings of a branch are read from git without touching the checkout
(ADR-61). State and scores are per branch; merging imports branch provenance
into main state with a three-way rule.
"""

from __future__ import annotations

import atexit
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..catalog import build_catalog
from ..catalog.io import atomic_write_text, read_json
from ..catalog.scores import ScoreStore
from ..catalog.state import (
    TRUSTED_STATUSES,
    StateStore,
    needs_translation,
    now_iso,
    parse_translated_at,
    split_operator_key,
    state_key,
)
from ..projects import ProjectConfig

__all__ = [
    "BranchRegistry",
    "track_branch",
    "list_branches",
    "branch_config",
    "sync_from_git",
    "merge_preview",
    "merge_resolve",
    "set_active_branch",
    "archive_branch",
    "delete_branch",
    "branch_source_diff",
    "branch_work_keys",
    "fetch_remote",
    "diff_payload",
]

_BRANCH_NAME = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")


class BranchRegistry:
    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root)
        self.path = self.state_root / "branches.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"branches": {}, "active": None}
        try:
            raw = read_json(self.path)
        except (OSError, json.JSONDecodeError) as exc:
            # Fail closed: a soft empty load + later save would wipe the only
            # recoverable registry (match AccountStore behaviour).
            raise ValueError(f"corrupt branch registry {self.path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"corrupt branch registry {self.path}: not an object")
        branches = raw.get("branches") or {}
        if not isinstance(branches, dict):
            raise ValueError(f"corrupt branch registry {self.path}: branches not an object")
        return {"branches": branches, "active": raw.get("active")}

    def save(self, data: dict[str, Any]) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.path, text)

    def branch_dir(self, name: str) -> Path:
        return self.state_root / "branches" / name

    def scores_dir(self, name: str) -> Path:
        return self.branch_dir(name) / "scores"


# --- git (read-only) -----------------------------------------------------

_EXPORTS: dict[tuple[str, str], tuple[Path, Any]] = {}
_EXPORT_DIRS: list[Path] = []
_EXPORT_LIMIT = 8


def _cleanup_exports() -> None:
    for path in _EXPORT_DIRS:
        shutil.rmtree(path, ignore_errors=True)


atexit.register(_cleanup_exports)


def _git(root: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_text(root: Path, *args: str) -> str | None:
    proc = _git(root, *args)
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip()


def _resolve_ref(root: Path, name: str) -> str | None:
    """Commit sha for a branch name (local, then origin/), or ``None``."""
    for ref in (name, f"origin/{name}"):
        sha = _git_text(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if sha:
            return sha
    return None


def _catalog_dir(cfg: ProjectConfig) -> str:
    """Directory (relative to the project root) that holds every catalogue file."""
    template = (cfg.catalog_path or "").replace("\\", "/")
    cut = template.find("{")
    head = template if cut < 0 else template[:cut]
    head = head.rsplit("/", 1)[0] if "/" in head else ""
    return head or "."


def _export_catalog(cfg: ProjectConfig, sha: str):
    """Catalogue as it was at ``sha``, read without touching the checkout."""
    root = Path(cfg.root)
    key = (str(root), sha)
    hit = _EXPORTS.get(key)
    if hit is not None:
        return hit[1]
    proc = _git(root, "archive", "--format=tar", sha, "--", _catalog_dir(cfg), timeout=60)
    if proc is None or proc.returncode != 0:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="llm-localizator-branch-"))
    _EXPORT_DIRS.append(tmp)
    try:
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
            tar.extractall(tmp, filter="data")
    except (tarfile.TarError, OSError):
        return None
    prefix = _git_text(root, "rev-parse", "--show-prefix") or ""
    base = tmp / prefix if prefix and (tmp / prefix).exists() else tmp
    catalog = build_catalog(
        cfg.catalog_format, base, cfg.catalog_path, cfg.source_locale,
    )
    while len(_EXPORTS) >= _EXPORT_LIMIT:
        old_key, (old_base, _old_cat) = next(iter(_EXPORTS.items()))
        _EXPORTS.pop(old_key)
        # Evicted export roots are under mkdtemp; delete immediately so disk
        # does not grow for the life of the process.
        try:
            if old_base in _EXPORT_DIRS:
                _EXPORT_DIRS.remove(old_base)
            # base may be tmp/prefix; remove the mkdtemp root.
            root_tmp = old_base
            while root_tmp.name and not root_tmp.name.startswith("llm-localizator-branch-"):
                if root_tmp.parent == root_tmp:
                    break
                root_tmp = root_tmp.parent
            shutil.rmtree(root_tmp, ignore_errors=True)
            if root_tmp in _EXPORT_DIRS:
                _EXPORT_DIRS.remove(root_tmp)
        except Exception:
            pass
    _EXPORTS[key] = (tmp, catalog)
    return catalog


def _source_map(cfg: ProjectConfig, catalog) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for ns in cfg.namespaces_for(catalog):
        for key, value in catalog.load(cfg.source_locale, ns).items():
            if not cfg.is_skipped(ns, key):
                out[(ns, key)] = value
    return out


def _short(sha: str | None) -> str | None:
    return sha[:7] if sha else None


def branch_source_diff(
    cfg: ProjectConfig, name: str, base: str | None = None,
) -> dict[str, Any]:
    """Source strings added / changed / removed on ``name`` relative to ``base``."""
    root = Path(cfg.root)
    base = base or cfg.source_branch
    branch_sha = _resolve_ref(root, name)
    base_sha = _resolve_ref(root, base)
    if not branch_sha or not base_sha:
        return {"ok": False, "error": "git ref not found", "git": False}
    branch_cat = _export_catalog(cfg, branch_sha)
    base_cat = _export_catalog(cfg, base_sha)
    if branch_cat is None or base_cat is None:
        return {"ok": False, "error": "could not read catalogue from git", "git": True}
    mine = _source_map(cfg, branch_cat)
    theirs = _source_map(cfg, base_cat)
    return {
        "ok": True,
        "git": True,
        "branch_commit": branch_sha,
        "base_commit": base_sha,
        "added": sorted(k for k in mine if k not in theirs),
        "changed": sorted(k for k in mine if k in theirs and mine[k] != theirs[k]),
        "removed": sorted(k for k in theirs if k not in mine),
        "total": len(mine),
        "catalog": branch_cat,
        "source": mine,
    }


def branch_work_keys(cfg: ProjectConfig, name: str) -> list[dict[str, str]]:
    """Keys a translate run on the branch should cover (added + changed)."""
    reg = BranchRegistry(cfg.state_root())
    meta = (reg.load().get("branches") or {}).get(name) or {}
    diff = branch_source_diff(cfg, name, meta.get("base"))
    if not diff.get("ok"):
        return []
    return [{"namespace": ns, "key": key} for ns, key in diff["added"] + diff["changed"]]


def fetch_remote(cfg: ProjectConfig) -> dict[str, Any]:
    """``git fetch``: network access, so only ever called on explicit request."""
    root = Path(cfg.root)
    if not _git_text(root, "remote"):
        return {"ok": False, "error": "no git remote configured", "output": ""}
    proc = _git(root, "fetch", "--all", "--prune", timeout=120)
    if proc is None:
        return {"ok": False, "error": "git fetch failed to run", "output": ""}
    text = (proc.stdout + proc.stderr).decode("utf-8", "replace").strip()
    return {
        "ok": proc.returncode == 0,
        "output": text,
        "error": "" if proc.returncode == 0 else text,
    }


# --- registry ------------------------------------------------------------


def track_branch(
    cfg: ProjectConfig,
    name: str,
    *,
    base: str | None = None,
    auto_translate: bool = True,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name or not _BRANCH_NAME.match(name) or ".." in name:
        return {"ok": False, "error": "invalid branch name"}
    base = (base or cfg.source_branch or "main").strip()
    if not _BRANCH_NAME.match(base) or ".." in base:
        return {"ok": False, "error": "invalid base branch name"}
    reg = BranchRegistry(cfg.state_root())
    data = reg.load()
    existing = (data.get("branches") or {}).get(name) or {}
    branch_dir = reg.branch_dir(name)
    scores_dir = reg.scores_dir(name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    scores_dir.mkdir(parents=True, exist_ok=True)
    data["branches"][name] = {
        "name": name,
        # Re-tracking keeps the first timestamp: three-way merge compares main
        # entries against it.
        "tracked_at": existing.get("tracked_at") or now_iso(),
        "state_dir": str(branch_dir),
        "scores_dir": str(scores_dir),
        "base": base,
        "base_commit": _short(_resolve_ref(Path(cfg.root), base)),
        "auto_translate": bool(auto_translate),
        "archived": False,
        "merged_at": None,
    }
    if not data.get("active"):
        data["active"] = name
    reg.save(data)
    return {"ok": True, "branch": data["branches"][name], "branches": list_branches(cfg)}


def _pct(done: int, total: int) -> int:
    return int(round(100 * done / total)) if total else 0


def _branch_coverage(cfg, diff, main_state, branch_state) -> dict[str, Any]:
    """Per-locale coverage of the branch catalogue, plus whether its work keys are done."""
    catalog = diff["catalog"]
    source = diff["source"]
    work = set(diff["added"]) | set(diff["changed"])
    coverage: dict[str, int] = {}
    work_done = True
    for locale in cfg.targets:
        target_ns: dict[str, dict] = {}
        done = 0
        for (ns, key), text in source.items():
            target = target_ns.get(ns)
            if target is None:
                target = target_ns[ns] = catalog.load(locale, ns)
            entry = branch_state.entry(locale, ns, key) or main_state.entry(locale, ns, key)
            if key in target and entry is not None and not needs_translation(text, entry):
                done += 1
            elif (ns, key) in work:
                work_done = False
        coverage[locale] = _pct(done, len(source))
    return {"coverage": coverage, "work_done": work_done}


def _branch_row(
    cfg, name, meta, active, main_state, *, detail: bool = True,
) -> dict[str, Any]:
    reg = BranchRegistry(cfg.state_root())
    row: dict[str, Any] = {
        "name": name,
        "tracked_at": meta.get("tracked_at"),
        "active": active == name,
        "state_dir": str(reg.branch_dir(name)),
        "scores_dir": str(reg.scores_dir(name)),
        "catalogues_shared": True,
        "base": meta.get("base") or cfg.source_branch,
        "base_commit": meta.get("base_commit"),
        "auto_translate": bool(meta.get("auto_translate", True)),
        "archived": bool(meta.get("archived")),
        "merged_at": meta.get("merged_at"),
        "git": False,
        "commit": None,
        "new_strings": None,
        "changed_strings": None,
        "removed_strings": None,
        "coverage": {},
        "conflicts": None,
    }
    if row["merged_at"]:
        row["status"] = "merged"
        return row
    if row["archived"]:
        row["status"] = "archived"
        return row
    if not detail:
        # List endpoint: registry metadata only. Git archive + merge-preview
        # belong on Sync / merge-preview (multi-second each).
        row["status"] = "tracked"
        return row
    preview = merge_preview(cfg, name)
    if preview.get("ok"):
        row["conflicts"] = preview["conflicts"]
    diff = branch_source_diff(cfg, name, row["base"])
    if not diff.get("ok"):
        row["status"] = "unknown"
        row["git_error"] = diff.get("error")
        return row
    cov = _branch_coverage(cfg, diff, main_state, StateStore(reg.branch_dir(name)))
    work = len(diff["added"]) + len(diff["changed"])
    row.update(
        git=True,
        commit=_short(diff["branch_commit"]),
        new_strings=len(diff["added"]),
        changed_strings=len(diff["changed"]),
        removed_strings=len(diff["removed"]),
        coverage=cov["coverage"],
    )
    if not work:
        row["status"] = "synced"
    elif cov["work_done"] and not row["conflicts"]:
        row["status"] = "ready"
    else:
        row["status"] = "in_progress"
    return row


def _source_string_count(cfg: ProjectConfig, catalog) -> int:
    total = 0
    for ns in cfg.namespaces_for(catalog):
        for key, src in catalog.load(cfg.source_locale, ns).items():
            if isinstance(src, str) and not cfg.is_skipped(ns, key):
                total += 1
    return total


def _main_row(
    cfg: ProjectConfig,
    active: str | None,
    *,
    catalog=None,
    status_rows=None,
) -> dict[str, Any]:
    """Main-branch summary.

    Never runs ``collect()`` itself — that walk is multi-second on large
    projects and stalled ``/api/branches``. Pass warm ``status_rows`` for
    coverage chips; otherwise count source strings from the catalogue only.
    """
    if catalog is None:
        catalog = build_catalog(
            cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
        )
    if status_rows is not None:
        source_strings = status_rows[0].total if status_rows else 0
        coverage = {r.locale: _pct(r.translated, r.total) for r in status_rows}
    else:
        source_strings = _source_string_count(cfg, catalog)
        coverage = {}
    # Short timeout: a hung git must not stall the Branches page.
    commit = None
    proc = _git(Path(cfg.root), "rev-parse", "--short", "HEAD", timeout=5)
    if proc is not None and proc.returncode == 0:
        commit = proc.stdout.decode("utf-8", "replace").strip() or None
    return {
        "name": cfg.source_branch,
        "default": True,
        "active": not active,
        "status": "default",
        "source_strings": source_strings,
        "coverage": coverage,
        "commit": commit,
    }


def list_branches(
    cfg: ProjectConfig,
    *,
    catalog=None,
    status_rows=None,
    detail: bool = True,
) -> dict[str, Any]:
    """Tracked branches + main summary.

    Pass warm ``status_rows`` for main coverage chips. With ``detail=False``
    (web list), skip git archive / merge-preview per branch so the page
    stays interactive; Sync and merge-preview fill the heavy fields.
    """
    if catalog is None:
        catalog = build_catalog(
            cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
        )
    reg = BranchRegistry(cfg.state_root())
    data = reg.load()
    active = data.get("active")
    main_state = StateStore(cfg.state_root()) if detail else None
    rows = [
        _branch_row(
            cfg, name, meta, active, main_state, detail=detail,
        )
        for name, meta in sorted((data.get("branches") or {}).items())
    ]
    return {
        "ok": True,
        "active": active,
        "main": _main_row(
            cfg, active, catalog=catalog, status_rows=status_rows,
        ),
        "branches": rows,
        "targets": list(cfg.targets),
        "detail": detail,
    }


def branch_config(cfg: ProjectConfig, name: str) -> ProjectConfig | None:
    """Return a config overlay whose state/scores live under the branch dir."""
    reg = BranchRegistry(cfg.state_root())
    data = reg.load()
    if name not in (data.get("branches") or {}):
        return None
    return replace(
        cfg,
        state_dir=reg.branch_dir(name),
        scores_dir=reg.scores_dir(name),
    )


def set_active_branch(cfg: ProjectConfig, name: str | None) -> dict[str, Any]:
    reg = BranchRegistry(cfg.state_root())
    data = reg.load()
    if name is None or name == "" or name == cfg.source_branch:
        data["active"] = None
        reg.save(data)
        return {"ok": True, "active": None, **list_branches(cfg)}
    if name not in (data.get("branches") or {}):
        return {"ok": False, "error": f"branch {name!r} is not tracked"}
    data["active"] = name
    reg.save(data)
    return {"ok": True, "active": name, **list_branches(cfg)}


def archive_branch(cfg: ProjectConfig, name: str, archived: bool = True) -> dict[str, Any]:
    reg = BranchRegistry(cfg.state_root())
    data = reg.load()
    meta = (data.get("branches") or {}).get(name)
    if meta is None:
        return {"ok": False, "error": f"branch {name!r} is not tracked"}
    meta["archived"] = bool(archived)
    if not archived:
        meta["merged_at"] = None
    elif data.get("active") == name:
        data["active"] = None
    reg.save(data)
    return {"ok": True, **list_branches(cfg)}


def delete_branch(cfg: ProjectConfig, name: str, *, confirm: bool = False) -> dict[str, Any]:
    """Forget a branch and remove its state. Permanent, so ``confirm`` is required."""
    reg = BranchRegistry(cfg.state_root())
    data = reg.load()
    if name not in (data.get("branches") or {}):
        return {"ok": False, "error": f"branch {name!r} is not tracked"}
    if not confirm:
        return {"ok": False, "error": "delete requires confirm=true"}
    del data["branches"][name]
    if data.get("active") == name:
        data["active"] = None
    reg.save(data)
    shutil.rmtree(reg.branch_dir(name), ignore_errors=True)
    return {"ok": True, **list_branches(cfg)}


def sync_from_git(cfg: ProjectConfig, *, base: str = "HEAD") -> dict[str, Any]:
    """Read-only git status/diff → keys whose source catalogue files changed."""
    root = Path(cfg.root)
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        diff = subprocess.run(
            ["git", "diff", "--name-only", base],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "keys": [], "files": []}

    files: list[str] = []
    for line in (status.stdout or "").splitlines():
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if path:
            files.append(path.replace("\\", "/"))
    for line in (diff.stdout or "").splitlines():
        path = line.strip().replace("\\", "/")
        if path and path not in files:
            files.append(path)

    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    # Map changed files under the catalogue template to namespaces when possible.
    keys: list[dict[str, str]] = []
    catalog_hint = (cfg.catalog_path or "").replace("\\", "/")
    source_locale = cfg.source_locale
    for rel in files:
        if source_locale not in rel:
            continue
        if "messages/" not in rel and "{locale}" not in catalog_hint:
            # Still consider json under project that look like locale files.
            if not rel.endswith(".json"):
                continue
        ns = Path(rel).stem
        for key in catalog.load(source_locale, ns):
            keys.append({"namespace": ns, "key": key, "file": rel})
        if not list(catalog.load(source_locale, ns)):
            keys.append({"namespace": ns, "key": "", "file": rel})

    # Per-branch picture from git objects (still read-only, no fetch).
    reg = BranchRegistry(cfg.state_root())
    tracked = []
    for name, meta in sorted((reg.load().get("branches") or {}).items()):
        d = branch_source_diff(cfg, name, meta.get("base"))
        tracked.append({
            "name": name,
            "git": bool(d.get("ok")),
            "commit": _short(d.get("branch_commit")),
            "added": len(d.get("added") or []),
            "changed": len(d.get("changed") or []),
            "removed": len(d.get("removed") or []),
        })

    return {
        "ok": True,
        "files": files,
        "keys": keys,
        "branches": tracked,
        "has_remote": bool(_git_text(root, "remote")),
        "committed": False,
        "status_code": status.returncode,
        "diff_code": diff.returncode,
    }


# --- merge ---------------------------------------------------------------

_MERGE_FIELDS = ("src_sha", "model", "status", "provider")


def _untouched_since(main_entry: dict, tracked_at: str | None) -> bool:
    """Main entry predates tracking, so main did not change it independently."""
    when = parse_translated_at(main_entry.get("translated_at"))
    since = parse_translated_at(tracked_at)
    return bool(when and since and when < since)


def _classify(main_entry: dict | None, entry: dict, tracked_at: str | None) -> str:
    if main_entry is None:
        return "new"
    if all(main_entry.get(f) == entry.get(f) for f in _MERGE_FIELDS):
        return "same"
    if _untouched_since(main_entry, tracked_at):
        # A trusted copy (human, agent, imported ...) of an unchanged source is
        # never overwritten by a machine re-translation without a decision.
        protected = (
            str(main_entry.get("status")) in TRUSTED_STATUSES
            and main_entry.get("src_sha") == entry.get("src_sha")
        )
        if not protected:
            return "take"
    return "conflict"


def merge_preview(cfg: ProjectConfig, branch: str) -> dict[str, Any]:
    """Three-way view of branch state against main state.

    ``new`` and ``take`` rows apply automatically; ``conflict`` rows never do.
    """
    bcfg = branch_config(cfg, branch)
    if bcfg is None:
        return {"ok": False, "error": f"branch {branch!r} is not tracked"}
    reg = BranchRegistry(cfg.state_root())
    tracked_at = ((reg.load().get("branches") or {}).get(branch) or {}).get("tracked_at")
    main = StateStore(cfg.state_root())
    other = StateStore(bcfg.state_root())
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    namespaces = set(cfg.namespaces_for(catalog))
    rows: list[dict[str, Any]] = []
    for locale in cfg.targets:
        branch_data = other.load(locale)
        main_data = main.load(locale)
        for sk, entry in sorted(branch_data.items()):
            main_entry = main_data.get(sk)
            kind = _classify(main_entry, entry, tracked_at)
            if kind == "same":
                continue
            ns, key = split_operator_key(sk, namespaces)
            rows.append({
                "locale": locale,
                "namespace": ns,
                "key": key,
                "kind": kind,
                "branch": entry,
                "main": main_entry,
                "source": catalog.load(cfg.source_locale, ns).get(key),
            })
    return {
        "ok": True,
        "branch": branch,
        "rows": rows,
        "conflicts": sum(1 for r in rows if r["kind"] == "conflict"),
        "new": sum(1 for r in rows if r["kind"] == "new"),
        "take": sum(1 for r in rows if r["kind"] == "take"),
    }


def diff_payload(cfg: ProjectConfig, branch: str) -> dict[str, Any]:
    """Downloadable merge diff: source changes plus state rows."""
    preview = merge_preview(cfg, branch)
    if not preview.get("ok"):
        return preview
    diff = branch_source_diff(cfg, branch)
    source = None
    if diff.get("ok"):
        def pairs(keys):
            return [{"namespace": n, "key": k} for n, k in keys]

        source = {
            "added": pairs(diff["added"]),
            "changed": pairs(diff["changed"]),
            "removed": pairs(diff["removed"]),
        }
    return {
        "ok": True,
        "branch": branch,
        "source": source,
        "state": preview["rows"],
        "conflicts": preview["conflicts"],
    }


def merge_resolve(
    cfg: ProjectConfig,
    branch: str,
    *,
    choices: list[dict[str, str]],
) -> dict[str, Any]:
    """Apply a merge into main state.

    ``new`` and ``take`` rows are applied unless a choice says ``main``.
    ``conflict`` rows change only when the operator picks ``branch``. The branch
    is marked merged once no conflict is left without a choice.
    """
    bcfg = branch_config(cfg, branch)
    if bcfg is None:
        return {"ok": False, "error": f"branch {branch!r} is not tracked"}
    preview = merge_preview(cfg, branch)
    if not preview.get("ok"):
        return preview
    picked: dict[tuple[str, str, str], str] = {}
    for choice in choices:
        side = str(choice.get("side") or "")
        if side in ("branch", "main"):
            picked[(
                str(choice.get("locale") or ""),
                str(choice.get("namespace") or ""),
                str(choice.get("key") or ""),
            )] = side
    main = StateStore(cfg.state_root())
    other = StateStore(bcfg.state_root())
    main_scores = ScoreStore(cfg.scores_root())
    branch_scores = ScoreStore(bcfg.scores_root())
    applied = skipped = unresolved = 0
    touched: set[str] = set()
    scored: set[str] = set()
    for row in preview["rows"]:
        ident = (row["locale"], row["namespace"], row["key"])
        side = picked.get(ident)
        if row["kind"] == "conflict":
            take = side == "branch"
            if side is None:
                unresolved += 1
        else:
            take = side != "main"
        if not take:
            skipped += 1
            continue
        entry = dict(other.entry(*ident) or {})
        if not entry:
            skipped += 1
            continue
        main.record(*ident, entry)
        touched.add(row["locale"])
        score = branch_scores.get(*ident)
        if score:
            main_scores.load(row["locale"])[state_key(row["namespace"], row["key"])] = dict(score)
            scored.add(row["locale"])
        applied += 1
    for locale in touched:
        main.save(locale)
    for locale in scored:
        main_scores.save(locale)
    merged = unresolved == 0
    if merged:
        reg = BranchRegistry(cfg.state_root())
        data = reg.load()
        meta = (data.get("branches") or {}).get(branch)
        if meta is not None:
            meta["merged_at"] = now_iso()
            if data.get("active") == branch:
                data["active"] = None
            reg.save(data)
    return {
        "ok": True,
        "applied": applied,
        "skipped": skipped,
        "unresolved": unresolved,
        "merged": merged,
        "preview": merge_preview(cfg, branch),
    }
