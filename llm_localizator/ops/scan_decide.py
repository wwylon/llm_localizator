"""``scan-decide``: the user's accept / ignore decisions on scan results (ADR-55).

What accepting does follows ``[apply] mode``:

- ``manual``: the decision is recorded; ``apply --confirm`` writes it later.
- ``request``: a review ticket is opened on the source locale; closing it applies the key.
- ``auto``: the source key is written and translation is enqueued at once.

Source code is never edited here (ADR-32).
"""

from __future__ import annotations

from fnmatch import fnmatch

from ..catalog import catalog_for
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.review_queue import STATUS_DONE, open_review_queue
from ..catalog.scan_decisions import (
    ACCEPTED, APPLIED, IGNORED, KIND_COLLECTION, KIND_HIT, ScanDecisions, collection_id,
)
from ..projects import ProjectConfig
from .apply import enqueue_translate_task, plan_source_key, write_source_keys
from .types import AgentHardcodedRequest, OpResult, ScanDecideRequest

__all__ = ["REQUEST_REASON", "apply_request_ticket", "decision_counts", "op_scan_decide"]

REQUEST_REASON = "localize-request"
_ACTIONS = ("accept", "ignore", "reset", "status")


def _fail(summary: str, code: int = 64) -> OpResult:
    return OpResult(ok=False, exit_code=code, command="scan-decide", summary=summary)


def _live_hits(cfg: ProjectConfig, req: ScanDecideRequest) -> tuple[list[dict], OpResult | None]:
    from .agent_hardcoded import op_agent_hardcoded

    # Include low-confidence hits so --confidence low / --file can select them
    # (default agent-hardcoded reports still hide low unless --show-low).
    scanned = op_agent_hardcoded(cfg, AgentHardcodedRequest(
        adapter=req.adapter, limit=req.limit, fmt="json",
        catalogue_audit=False, show_ignored=True, show_low=True,
    ))
    if not scanned.ok:
        return [], scanned
    return list((scanned.data or {}).get("hits") or []), None


def _live_collections(cfg: ProjectConfig) -> list[dict]:
    from ..projects.collections import discover_collections

    rows = []
    for item in discover_collections(cfg.root):
        root = str(item.get("root") or "")
        rows.append({
            "id": collection_id(str(item["name"]), root), "name": item["name"], "root": root,
            "format": item.get("format"), "locales": item.get("locales"),
        })
    return rows


def decision_counts(cfg: ProjectConfig, hits: list[dict] | None = None) -> dict[str, int]:
    """Hit decision counts; ``pending`` and ``orphaned`` need the live hits."""
    live = {h["id"] for h in hits} if hits is not None else None
    return ScanDecisions.for_project(cfg).summary(live, KIND_HIT)


def _select(items: list[dict], req: ScanDecideRequest, decisions: dict) -> list[dict]:
    if req.ids:
        wanted = set(req.ids)
        return [i for i in items if i["id"] in wanted]
    picked = []
    for item in items:
        if item["id"] in decisions:
            continue  # only pending items are selected in bulk
        if req.confidence and item.get("confidence") != req.confidence:
            continue
        if req.file and not fnmatch(str(item.get("file", "")), req.file):
            continue
        if req.confidence or req.file or req.all_pending:
            picked.append(item)
    return picked


def _accept_hits(cfg: ProjectConfig, store: ScanDecisions, picked: list[dict],
                 req: ScanDecideRequest, by: str) -> OpResult:
    if req.key and len(picked) != 1:
        return _fail("--key applies to exactly one hit")
    cat = catalog_for(cfg)
    pending: dict[str, dict[str, str]] = {}
    entries: list[dict] = []
    for item in picked:
        if store.status_of(item["id"]) == APPLIED:
            continue
        plan = plan_source_key(
            cat, cfg.source_locale, item["text"], item["file"],
            existing_key=item.get("existing_key"), override=req.key, pending=pending,
        )
        if req.key and not plan["reuse"] and plan["key"] != req.key:
            return _fail(f"key {req.key!r} already holds different text in {plan['namespace'] or 'the catalogue'}")
        if not plan["reuse"]:
            pending.setdefault(plan["namespace"], {})[plan["key"]] = plan["text"]
        entry = store.decide(
            item["id"], ACCEPTED, by=by, note=req.note, namespace=plan["namespace"],
            key=plan["key"], reuse=plan["reuse"], text=item["text"], file=item["file"],
            existing_key=item.get("existing_key"),
        )
        entries.append({**entry, "id": item["id"]})

    mode = cfg.apply_mode
    tickets: list[str] = []
    applied = 0
    if mode == "request":
        queue = open_review_queue(cfg)
        for entry in entries:
            if entry.get("reuse"):
                store.decide(entry["id"], APPLIED, by=by)
                applied += 1
                continue
            ticket = queue.enqueue(
                locale=cfg.source_locale, namespace=entry.get("namespace") or "", key=entry["key"],
                reason=f"{REQUEST_REASON}:{entry['id']}", source=entry["text"],
            )
            tickets.append(ticket.id)
    elif mode == "auto":
        planned = write_source_keys(cfg, entries, dry_run=False)
        for plan in planned:
            store.decide(plan["id"], APPLIED, by=by, namespace=plan["namespace"], key=plan["key"])
        applied = len(planned)
        if any(p["written"] for p in planned):
            enqueue_translate_task(cfg)
    verb = {"manual": "run apply --confirm to write them",
            "request": f"{len(tickets)} review ticket(s) opened",
            "auto": f"{applied} applied"}[mode]
    return OpResult(
        ok=True, exit_code=0, command="scan-decide",
        summary=f"accepted {len(entries)} hit(s) ({mode} mode: {verb})",
        lines=[f"  {e['id']}  {e.get('namespace') or '(default)'}/{e['key']}" for e in entries],
        data={"changed": [e["id"] for e in entries], "mode": mode, "tickets": tickets, "applied": applied},
    )


def op_scan_decide(cfg: ProjectConfig, req: ScanDecideRequest) -> OpResult:
    action = (req.action or "status").lower()
    if action not in _ACTIONS:
        return _fail(f"unknown action {action!r}; use one of {', '.join(_ACTIONS)}")
    kind = req.kind or KIND_HIT
    if kind not in (KIND_HIT, KIND_COLLECTION):
        return _fail(f"unknown kind {kind!r}")
    by = (req.by or "").strip() or "cli"
    store = ScanDecisions.for_project(cfg)

    hits: list[dict] = []
    items: list[dict] = []
    if kind == KIND_HIT:
        hits, failure = _live_hits(cfg, req)
        if failure is not None and (action in ("accept", "status") or not req.ids):
            return failure
        items = hits
    else:
        items = _live_collections(cfg)

    if action == "status":
        counts = store.summary({i["id"] for i in items}, kind)
        return OpResult(
            ok=True, exit_code=0, command="scan-decide",
            summary=(f"{counts['pending']} pending, {counts['accepted']} accepted, "
                     f"{counts['ignored']} ignored, {counts['applied']} applied"
                     + (f", {counts['orphaned']} orphaned" if counts["orphaned"] else "")),
            data={"counts": counts, "mode": cfg.apply_mode, "kind": kind},
        )

    decisions = store.items()
    picked = _select(items, req, decisions)
    if action == "reset" and req.ids:
        picked = [{"id": i} for i in req.ids]
    if not picked:
        return _fail("nothing selected: pass --ids, --confidence, --file or --all-pending")

    with project_mutation_lock(cfg):
        if action == "reset":
            gone = [p["id"] for p in picked if store.reset(p["id"])]
            return OpResult(
                ok=True, exit_code=0, command="scan-decide",
                summary=f"reset {len(gone)} decision(s)", data={"changed": gone},
            )
        if action == "ignore":
            for item in picked:
                store.decide(item["id"], IGNORED, kind=kind, by=by, note=req.note,
                             text=item.get("text") or item.get("name"), file=item.get("file"))
            return OpResult(
                ok=True, exit_code=0, command="scan-decide",
                summary=f"ignored {len(picked)} {kind}(s)",
                data={"changed": [p["id"] for p in picked]},
            )
        if kind == KIND_COLLECTION:
            for item in picked:
                store.decide(item["id"], ACCEPTED, kind=kind, by=by, note=req.note,
                             text=item["name"], file=item["root"])
            lines = [f"  {i['name']}: add `{i['root'] or '.'}` to .llm-localize.toml" for i in picked]
            return OpResult(
                ok=True, exit_code=0, command="scan-decide",
                summary=f"accepted {len(picked)} collection(s); copy each root into the config",
                lines=lines, data={"changed": [p["id"] for p in picked]},
            )
        return _accept_hits(cfg, store, picked, req, by)


def apply_request_ticket(cfg: ProjectConfig, ticket) -> dict | None:
    """Apply the decision behind a closed ``localize-request`` ticket (request mode).

    Safe to call for any ticket and more than once: only a done ticket whose decision is
    still ``accepted`` writes anything.
    """
    prefix = REQUEST_REASON + ":"
    if not str(ticket.reason).startswith(prefix) or ticket.status != STATUS_DONE:
        return None
    item_id = str(ticket.reason)[len(prefix):].strip()
    with project_mutation_lock(cfg):
        store = ScanDecisions.for_project(cfg)
        entry = store.get(item_id)
        if not entry or entry.get("status") != ACCEPTED:
            return None
        plan = write_source_keys(cfg, [{**entry, "id": item_id}], dry_run=False)[0]
        store.decide(item_id, APPLIED, by=entry.get("by", ""), namespace=plan["namespace"], key=plan["key"])
    if plan["written"]:
        enqueue_translate_task(cfg)
    return plan
