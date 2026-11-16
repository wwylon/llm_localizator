"""``discuss``: per-key threads with @mentions and a resolved state (C-019, ADR-94).

``add`` comments on a key (reopening a resolved thread), ``resolve`` and ``reopen`` change the
state, ``list`` shows threads, optionally only open ones or those that mention a person. Threads
hold no translation text and change nothing in the catalogue; nothing is sent outside the app.
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.discussions import DiscussionStore
from ..catalog.mutation_lock import project_mutation_lock
from ..projects import ProjectConfig
from .types import DiscussRequest, OpResult

__all__ = ["op_discuss"]

ACTIONS = ("list", "add", "resolve", "reopen")
MAX_TEXT = 2000


def _fail(summary: str) -> OpResult:
    return OpResult(ok=False, exit_code=64, command="discuss", summary=summary, lines=[summary])


def _row(thread: dict) -> dict:
    comments = thread.get("comments", [])
    return {
        "ref": thread["ref"], "resolved": bool(thread.get("resolved")),
        "comments": comments, "count": len(comments),
        "mentions": sorted({m for c in comments for m in c.get("mentions", [])}),
        "resolved_by": thread.get("resolved_by", ""),
    }


def op_discuss(cfg: ProjectConfig, req: DiscussRequest) -> OpResult:
    action = req.action or "list"
    if action not in ACTIONS:
        return _fail(f"unknown discuss action {action!r}")
    store = DiscussionStore.for_project(cfg)
    ref = f"{req.namespace}.{req.key}" if req.namespace and req.key else ""

    if action == "list":
        mention = req.mention.lstrip("@")
        rows = []
        for thread in store.items().values():
            row = _row(thread)
            if ref and row["ref"] != ref:
                continue
            if req.namespace and not ref and not row["ref"].startswith(req.namespace + "."):
                continue
            if req.open_only and row["resolved"]:
                continue
            if mention and mention not in row["mentions"]:
                continue
            rows.append(row)
        rows.sort(key=lambda r: (r["resolved"], r["ref"]))
        lines = []
        for r in rows:
            last = r["comments"][-1] if r["comments"] else {}
            lines.append(
                f"{r['ref']} [{'resolved' if r['resolved'] else 'open'}] {r['count']} comment(s)"
                f" - {last.get('by', '')}: {last.get('text', '')[:80]}"
            )
        return OpResult(ok=True, exit_code=0, command="discuss", summary=f"{len(rows)} thread(s)",
                        lines=lines, data={"threads": rows})

    if not ref:
        return _fail(f"discuss {action} needs a namespace and a key")
    catalog = catalog_for(cfg)
    if not isinstance(catalog.load(cfg.source_locale, req.namespace).get(req.key), str):
        return _fail(f"unknown key {ref!r}")

    if action == "add":
        text = req.text.strip()
        if not text:
            return _fail("discuss add needs text")
        if len(text) > MAX_TEXT:
            return _fail(f"comment is too long (limit {MAX_TEXT} characters)")
        with project_mutation_lock(cfg):
            thread = store.add(ref, text=text, by=req.by or "")
        return OpResult(ok=True, exit_code=0, command="discuss",
                        summary=f"comment {thread['comments'][-1]['n']} on {ref}",
                        lines=[f"{ref}: {len(thread['comments'])} comment(s), open"],
                        data={"threads": [_row(thread)]})

    resolved = action == "resolve"
    with project_mutation_lock(cfg):
        thread = store.set_resolved(ref, resolved, req.by or "")
    if thread is None:
        return _fail(f"no thread on {ref}")
    return OpResult(ok=True, exit_code=0, command="discuss",
                    summary=f"{ref} {'resolved' if resolved else 'reopened'}",
                    lines=[f"{ref} {'resolved' if resolved else 'reopened'}"],
                    data={"threads": [_row(thread)]})
