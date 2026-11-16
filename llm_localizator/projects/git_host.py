"""Pull requests for catalogue changes, and ``Co-authored-by`` trailers (C-015, C-025, ADR-101).

Opt-in with ``[git_host] enabled = true``. Every git or ``gh`` call goes through an injectable
``Runner`` so tests never touch a network. Planning writes nothing; opening a PR needs an
explicit ``confirm`` and only ever stages the catalogue files by path. Trailers come from the
provenance already on history events (ADR-19, ADR-46): people by their recorded name, models by
their model id. Addresses use the reserved ``.invalid`` domain because none is recorded.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..catalog.history import HistoryStore
from ..catalog.state import parse_translated_at
from .config import ProjectConfig

__all__ = [
    "GitHostError", "RunResult", "Runner", "coauthor_trailers", "default_runner",
    "plan_pr", "open_pr", "pr_status",
]

NOREPLY_DOMAIN = "llm-localizator.invalid"
_MACHINE_PROVIDERS = {"ollama", "ctranslate2", "anthropic", "deepl", "agent"}


class GitHostError(RuntimeError):
    pass


@dataclass
class RunResult:
    code: int
    out: str = ""
    err: str = ""


Runner = Callable[[list[str], Path], RunResult]


def default_runner(argv: list[str], cwd: Path) -> RunResult:
    try:
        proc = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=120, check=False,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RunResult(127, "", f"{argv[0]}: {exc}")
    return RunResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def _must(runner: Runner, argv: list[str], cwd: Path) -> str:
    res = runner(argv, cwd)
    if res.code != 0:
        raise GitHostError(f"{' '.join(argv[:3])} failed: {(res.err or res.out).strip()[:300]}")
    return res.out


def _catalog_prefix(cfg: ProjectConfig) -> str:
    """Directory part of the catalogue path template, before the first ``{placeholder}``."""
    parts: list[str] = []
    templated = False
    for part in Path(cfg.catalog_path).parts:
        if "{" in part:
            templated = True
            break
        parts.append(part)
    if not templated and parts:
        parts = parts[:-1]  # a literal path ends in a file name
    return "/".join(parts) or "."


def changed_catalog_files(cfg: ProjectConfig, runner: Runner) -> list[str]:
    """Catalogue paths with uncommitted changes, relative to the project root."""
    out = _must(runner, ["git", "status", "--porcelain", "-uall", "--", _catalog_prefix(cfg)], Path(cfg.root))
    files: list[str] = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.append(path)
    return sorted(dict.fromkeys(files))


def _since(cfg: ProjectConfig, runner: Runner) -> datetime | None:
    host = cfg.git_host
    res = runner(["git", "log", "-1", "--format=%cI", f"{host['remote']}/{host['base']}"], Path(cfg.root))
    if res.code != 0 or not res.out.strip():
        return None
    try:
        when = datetime.fromisoformat(res.out.strip())
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".") or "user"


def coauthor_trailers(cfg: ProjectConfig, since: datetime | None = None) -> list[str]:
    """Deduplicated ``Co-authored-by:`` lines for edits newer than ``since`` (C-025).

    Editors with a recorded name become trailers by that name; machine rows by their model id.
    Plain ``human`` rows without a name, imports and empty ids are skipped.
    """
    store = HistoryStore(cfg.history_root())
    names: set[str] = set()
    for locale in cfg.targets:
        for _sk, event, _raw in store.iter_events(locale):
            if since is not None:
                when = parse_translated_at(event.ts)
                if when is None or when < since:
                    continue
            who = (event.edited_by_name or "").strip()
            provider = (event.provider or "").strip()
            model = (event.model or "").strip()
            if who:
                names.add(who)
            elif provider in _MACHINE_PROVIDERS and model and model != "human":
                names.add(model)
    return [f"Co-authored-by: {n} <{_slug(n)}@{NOREPLY_DOMAIN}>" for n in sorted(names, key=str.lower)]


def _message(cfg: ProjectConfig, files: list[str], trailers: list[str]) -> tuple[str, str]:
    locales = ", ".join(cfg.targets)
    title = f"l10n: update translations ({locales})"
    lines = [f"Update {len(files)} catalogue file(s) written by llm-localizator.", "", "Files:"]
    lines += [f"- {f}" for f in files[:50]]
    if len(files) > 50:
        lines.append(f"- ... and {len(files) - 50} more")
    body = "\n".join(lines)
    if trailers:
        body += "\n\n" + "\n".join(trailers)
    return title, body


def plan_pr(cfg: ProjectConfig, runner: Runner | None = None, *, now: datetime | None = None) -> dict:
    """What ``open_pr`` would do. Reads git status and history; writes nothing."""
    host = cfg.git_host
    if not host.get("enabled"):
        raise GitHostError("PRs are off: add [git_host] enabled = true to the project config")
    run = runner or default_runner
    files = changed_catalog_files(cfg, run)
    trailers = coauthor_trailers(cfg, _since(cfg, run))
    title, body = _message(cfg, files, trailers)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M")
    return {
        "branch": f"{host['branch_prefix']}{stamp}", "base": host["base"], "remote": host["remote"],
        "files": files, "title": title, "body": body, "trailers": trailers,
    }


def open_pr(cfg: ProjectConfig, runner: Runner | None = None, *, now: datetime | None = None) -> dict:
    """Branch, commit the catalogue files by path, push, and open the PR."""
    run = runner or default_runner
    plan = plan_pr(cfg, run, now=now)
    if not plan["files"]:
        raise GitHostError("no catalogue changes to send")
    root, branch = Path(cfg.root), plan["branch"]
    _must(run, ["git", "checkout", "-b", branch], root)
    _must(run, ["git", "add", "--", *plan["files"]], root)
    _must(run, ["git", "commit", "-m", plan["title"] + "\n\n" + plan["body"], "--", *plan["files"]], root)
    _must(run, ["git", "push", "-u", plan["remote"], branch], root)
    url = _must(run, [
        "gh", "pr", "create", "--base", plan["base"], "--head", branch,
        "--title", plan["title"], "--body", plan["body"],
    ], root).strip()
    return {**plan, "url": url}


def pr_status(cfg: ProjectConfig, branch: str, runner: Runner | None = None) -> dict:
    """On-demand PR state for ``branch`` (no polling anywhere)."""
    if not cfg.git_host.get("enabled"):
        raise GitHostError("PRs are off: add [git_host] enabled = true to the project config")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", branch or "") or branch.startswith("-"):
        raise GitHostError("branch needs a plain branch name")
    out = _must(runner or default_runner, [
        "gh", "pr", "view", branch, "--json", "number,state,url,title,reviewDecision,mergeStateStatus",
    ], Path(cfg.root))
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise GitHostError("gh returned something that is not JSON") from exc
    return {"branch": branch, **data}
