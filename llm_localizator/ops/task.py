"""``task``: named work packages of keys with one assignee per locale (C-009, ADR-92).

``create`` picks keys (named, or a namespace, optionally only those still unverified in an
assigned locale); ``list`` shows each task with per-locale progress read from the state store
and an overdue mark; ``delete`` removes one. Tasks hold no text and change no translation.
"""

from __future__ import annotations

from datetime import date

from ..catalog import catalog_for
from ..catalog.discussions import DiscussionStore
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import is_verified
from ..catalog.tasks import TaskStore, task_progress
from ..pipeline.recording import provenance_stores
from ..projects import ProjectConfig
from .types import OpResult, TaskRequest

__all__ = ["op_task"]

ACTIONS = ("list", "create", "delete")
MAX_KEYS = 2000


def _fail(summary: str) -> OpResult:
    return OpResult(ok=False, exit_code=64, command="task", summary=summary, lines=[summary])


def _assignees(pairs: list[str] | None) -> dict[str, str] | None:
    out: dict[str, str] = {}
    for pair in pairs or []:
        locale, _, user = pair.partition("=")
        if not locale.strip() or not user.strip():
            return None
        out[locale.strip()] = user.strip()
    return out


def _row(task: dict, progress: dict, today: str, open_threads: int = 0) -> dict:
    done = bool(progress) and all(p["done"] >= p["total"] for p in progress.values())
    return {
        "id": task["id"], "name": task["name"], "due": task.get("due", ""),
        "assignees": task.get("assignees", {}), "keys": len(task.get("keys", [])),
        "progress": progress, "done": done,
        "overdue": bool(task.get("due")) and task["due"] < today and not done,
        "created_by": task.get("created_by", ""), "open_threads": open_threads,
    }


def op_task(cfg: ProjectConfig, req: TaskRequest) -> OpResult:
    action = req.action or "list"
    if action not in ACTIONS:
        return _fail(f"unknown task action {action!r}")
    store = TaskStore.for_project(cfg)

    if action == "list":
        state = provenance_stores(cfg).state
        today = date.today().isoformat()
        rows = []
        open_refs = set(DiscussionStore.for_project(cfg).open_counts())
        for task in store.items().values():
            if req.assignee and req.assignee not in task.get("assignees", {}).values():
                continue
            threads = len(open_refs.intersection(task.get("keys", [])))
            rows.append(_row(task, task_progress(task, state), today, threads))
        rows.sort(key=lambda r: (r["done"], r["due"] or "9999", r["id"]))
        lines = []
        for r in rows:
            prog = ", ".join(f"{loc} {p['done']}/{p['total']}" for loc, p in r["progress"].items())
            who = ", ".join(f"{loc}:{u}" for loc, u in r["assignees"].items())
            lines.append(
                f"{r['id']} {r['name']} [{who}] {prog}"
                + (f" due {r['due']}" if r["due"] else "")
                + (f"  {r['open_threads']} open thread(s)" if r["open_threads"] else "")
                + ("  OVERDUE" if r["overdue"] else "") + ("  done" if r["done"] else "")
            )
        return OpResult(ok=True, exit_code=0, command="task", summary=f"{len(rows)} task(s)",
                        lines=lines, data={"tasks": rows})

    if action == "delete":
        if not req.id:
            return _fail("task delete needs an id")
        with project_mutation_lock(cfg):
            gone = store.delete(req.id)
        if not gone:
            return _fail(f"no task {req.id}")
        return OpResult(ok=True, exit_code=0, command="task", summary=f"deleted {req.id}",
                        lines=[f"deleted {req.id}"], data={"deleted": req.id})

    assignees = _assignees(req.assign)
    if not req.name.strip():
        return _fail("task create needs a name")
    if not assignees:
        return _fail("task create needs --assign locale=user (one or more)")
    unknown = [loc for loc in assignees if loc not in cfg.targets]
    if unknown:
        return _fail(f"unknown target locale {unknown[0]!r}")
    if req.due:
        try:
            date.fromisoformat(req.due)
        except ValueError:
            return _fail("due must be a date like 2026-12-31")
    catalog = catalog_for(cfg)
    state = provenance_stores(cfg).state
    keys: list[str] = []
    if req.keys:
        for ref in req.keys:
            ns, _, key = ref.partition(".")
            if not (ns and key and isinstance(catalog.load(cfg.source_locale, ns).get(key), str)):
                return _fail(f"unknown key {ref!r}")
            keys.append(ref)
    else:
        for ns in cfg.namespaces_for(catalog):
            if req.namespace and ns != req.namespace:
                continue
            for key, text in catalog.load(cfg.source_locale, ns).items():
                if isinstance(text, str):
                    keys.append(f"{ns}.{key}")
    if req.unverified:
        keys = [
            k for k in keys
            if any(not is_verified(state.entry(loc, *k.partition(".")[::2])) for loc in assignees)
        ]
    if not keys:
        return _fail("no keys match")
    if len(keys) > MAX_KEYS:
        return _fail(f"{len(keys)} keys is too many for one task (limit {MAX_KEYS}); narrow it")
    with project_mutation_lock(cfg):
        task = store.create(
            name=req.name.strip(), keys=keys, assignees=assignees, due=req.due or "",
            by=req.by or "",
        )
    return OpResult(
        ok=True, exit_code=0, command="task",
        summary=f"created {task['id']} with {len(task['keys'])} key(s)",
        lines=[f"{task['id']} {task['name']}"],
        data={"tasks": [_row(task, task_progress(task, state), date.today().isoformat())]},
    )
