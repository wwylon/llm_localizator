"""``open-pr``: send changed catalogue files as a pull request (C-015, C-025, ADR-101).

``plan`` (the default) shows the branch, files, title and body with ``Co-authored-by`` trailers
and writes nothing. ``open`` branches, commits the catalogue files by path, pushes and runs
``gh pr create``; it needs ``confirm`` and ``[git_host] enabled = true``. ``status`` asks ``gh``
about one branch, once, on demand.
"""

from __future__ import annotations

from ..projects import ProjectConfig
from ..projects.git_host import GitHostError, Runner, open_pr, plan_pr, pr_status
from .types import OpenPrRequest, OpResult

__all__ = ["op_open_pr"]

ACTIONS = ("plan", "open", "status")


def _fail(summary: str, code: int = 64) -> OpResult:
    return OpResult(ok=False, exit_code=code, command="open-pr", summary=summary, lines=[summary])


def op_open_pr(cfg: ProjectConfig, req: OpenPrRequest, runner: Runner | None = None) -> OpResult:
    action = req.action or "plan"
    if action not in ACTIONS:
        return _fail(f"unknown open-pr action {action!r}")
    try:
        if action == "status":
            data = pr_status(cfg, req.branch, runner)
            return OpResult(
                ok=True, exit_code=0, command="open-pr",
                summary=f"PR {data.get('state', '?')}: {data.get('title', '')}",
                lines=[f"{k}: {data[k]}" for k in ("number", "state", "url", "reviewDecision", "mergeStateStatus") if k in data],
                data=data,
            )
        if action == "open":
            if not req.confirm:
                return _fail("open-pr open needs confirm (it pushes a branch and opens a PR); run plan first")
            data = open_pr(cfg, runner)
            return OpResult(
                ok=True, exit_code=0, command="open-pr", summary=f"opened {data['url']}",
                lines=[data["url"]], data=data,
            )
        data = plan_pr(cfg, runner)
    except GitHostError as exc:
        return _fail(str(exc), 1)
    lines = [f"branch: {data['branch']} -> {data['base']}", f"title: {data['title']}"]
    lines += [f"file: {f}" for f in data["files"]] or ["no catalogue changes"]
    lines += data["trailers"]
    return OpResult(
        ok=True, exit_code=0, command="open-pr",
        summary=f"{len(data['files'])} file(s) ready" if data["files"] else "nothing to send",
        lines=lines, data=data,
    )
