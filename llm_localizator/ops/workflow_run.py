"""Resumable block-script runner (ADR-63).

A workflow script is a tree of blocks. The runner carries a *frontier* of
``(position, keys)`` items: ``if`` blocks split a key set, terminal blocks drop
it, LLM blocks call the existing ops on exactly the keys that reached them.

Under taskqueue (ADR-15/28) an LLM op only *enqueues*. The item then parks as
``waiting`` with the queue task ids, the run is persisted, and :func:`resume_run`
(polled by the web page, or ``workflow --resume``) continues it once
``tq wait`` reports the tasks settled. Without ``tq`` — or with ``inline`` — the
op runs in-process and the script continues immediately.

A key set of ``None`` means "the whole scope" so translate / rescore are not
handed 20k key names; it is expanded the first time a block needs real keys.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from collections import Counter
from typing import TYPE_CHECKING, Any

from ..catalog import build_catalog, state_key
from ..catalog.flags import FlagStore
from ..catalog.history import HistoryStore
from ..catalog.io import atomic_write_text
from ..catalog.review_queue import open_review_queue
from ..catalog.scores import ScoreStore
from ..catalog.state import StateStore, is_verified, now_iso
from ..core.hash import src_hash
from ..core.workflow_rules import block_at, eval_cond, next_position
from ..pipeline.improve import IMPROVE_STUCK_TRIGGERS, _stuck_still_cooling
from ..projects import ProjectConfig
from ..projects.taskqueue import task_state, tq_available
from .types import (
    ImproveRequest,
    OpResult,
    RescoreRequest,
    ReviewRequest,
    TranslateRequest,
    resolve_namespaces,
)
from .verify import verify_translation

if TYPE_CHECKING:  # pragma: no cover
    from .workflow import WorkflowRequest, WorkflowSpec

__all__ = [
    "start_run",
    "resume_run",
    "cancel_run",
    "load_run",
    "describe_run",
    "latest_run",
]

RUN_ID = re.compile(r"wf_[0-9A-Za-z_-]{6,48}")
MAX_LINES = 400
KEEP_RUNS = 20
#: Persist the frontier after this many non-waiting items so a kill mid-advance
#: can resume without replaying finished work.
PERSIST_EVERY = 5
TERMINAL_STATUSES = frozenset({"done", "failed", "canceled"})
ACTIVE_STATUSES = frozenset({"running", "waiting"})
_GUARD = threading.Lock()
#: One lock and one cancel flag per run id, so a long run never blocks others.
_RUN_LOCKS: dict[str, threading.RLock] = {}
_CANCELS: dict[str, threading.Event] = {}


def _run_lock(run_id: str) -> threading.RLock:
    with _GUARD:
        return _RUN_LOCKS.setdefault(run_id, threading.RLock())


def _cancel_flag(run_id: str) -> threading.Event:
    with _GUARD:
        return _CANCELS.setdefault(run_id, threading.Event())


def _release_run(run_id: str, status: str | None) -> None:
    """Forget a run's lock and flag once it can no longer be advanced."""
    if status == "waiting":
        return
    with _GUARD:
        _RUN_LOCKS.pop(run_id, None)
        _CANCELS.pop(run_id, None)

#: Stat names mirrored into the legacy ``data`` block / last-run record.
STAT_KEYS = (
    "routed", "verified", "improved", "tickets", "flagged", "llm_reviewed",
    "skipped_cooldown", "skipped_verified", "loops_exhausted",
    "skipped_unscored", "stopped", "validated",
)


def _pos_key(pos) -> str:
    return ".".join(str(p) for p in pos)


def _runs_dir(cfg: ProjectConfig):
    return cfg.state_root() / "workflow" / "runs"


def _run_path(cfg: ProjectConfig, run_id: str):
    return _runs_dir(cfg) / f"{run_id}.json"


def load_run(cfg: ProjectConfig, run_id: str) -> dict[str, Any] | None:
    if not RUN_ID.fullmatch(run_id or ""):
        return None
    try:
        data = json.loads(_run_path(cfg, run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _prune_old_runs(cfg: ProjectConfig) -> None:
    """Drop surplus *terminal* run files; never delete running/waiting ones."""
    runs = _runs_dir(cfg)
    try:
        files = sorted(runs.glob("wf_*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    terminal: list = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            terminal.append(path)  # unreadable → treat as disposable
            continue
        status = data.get("status") if isinstance(data, dict) else None
        if status in ACTIVE_STATUSES:
            continue
        if status in TERMINAL_STATUSES or status is None:
            terminal.append(path)
    for old in terminal[:-KEEP_RUNS]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass


def _save_run(cfg: ProjectConfig, rec: dict[str, Any]) -> None:
    atomic_write_text(_run_path(cfg, rec["id"]), json.dumps(rec, ensure_ascii=False))
    try:
        _prune_old_runs(cfg)
    except OSError:
        pass


def latest_run(cfg: ProjectConfig, name: str | None = None) -> dict[str, Any] | None:
    """Newest persisted run (optionally of one workflow)."""
    try:
        files = sorted(
            _runs_dir(cfg).glob("wf_*.json"), key=lambda p: p.stat().st_mtime, reverse=True,
        )
    except OSError:
        return None
    for path in files:
        rec = load_run(cfg, path.stem)
        if rec and (name is None or rec.get("workflow") == name):
            return rec
    return None


def describe_run(rec: dict[str, Any]) -> dict[str, Any]:
    """The browser-facing view of a run record (no key lists)."""
    waiting = [
        {"at": it["wait"].get("at"), "kind": it["wait"].get("kind"),
         "tasks": it["wait"].get("tasks") or []}
        for it in rec.get("frontier") or [] if it.get("wait")
    ]
    return {
        "id": rec["id"],
        "workflow": rec.get("workflow"),
        "status": rec.get("status"),
        "dryRun": bool(rec.get("dryRun")),
        "counts": rec.get("counts") or {},
        "stats": rec.get("stats") or {},
        "lines": (rec.get("lines") or [])[-60:],
        "waiting": waiting,
        "message": rec.get("message") or "",
        "started": rec.get("started"),
        "finished": rec.get("finished"),
    }


def _improve_attempts(history: HistoryStore, locale: str) -> Counter:
    """Failed/kept improve passes per ``(state_key, src_sha)`` for one locale."""
    counts: Counter = Counter()
    for sk, event, raw in history.iter_events(locale):
        if raw.get("trigger") in IMPROVE_STUCK_TRIGGERS:
            counts[(sk, event.src_sha)] += 1
    return counts


def _ops():
    """Late-bound op functions so tests can patch them on ``ops.workflow``."""
    from . import workflow as wf

    return wf


class _Run:
    def __init__(self, cfg: ProjectConfig, spec: "WorkflowSpec", rec: dict[str, Any]):
        self.cfg = cfg
        self.spec = spec
        self.rec = rec
        self.script = spec.active_script()
        self.dry = bool(rec.get("dryRun"))
        self.stats: Counter = Counter(rec.get("stats") or {})
        self.counts: dict[str, int] = dict(rec.get("counts") or {})
        self.use_queue = bool(rec.get("useQueue"))
        self._catalog = None
        self._scores = None
        self._state = None
        self._history = None
        self._flags = None
        self._ns_cache: dict[tuple[str, str], dict] = {}

    # -- stores ------------------------------------------------------------
    @property
    def catalog(self):
        if self._catalog is None:
            c = self.cfg
            self._catalog = build_catalog(c.catalog_format, c.root, c.catalog_path, c.source_locale)
        return self._catalog

    @property
    def scores(self):
        if self._scores is None:
            self._scores = ScoreStore(self.cfg.scores_root())
        return self._scores

    @property
    def state(self):
        if self._state is None:
            self._state = StateStore(self.cfg.state_root())
        return self._state

    @property
    def history(self):
        if self._history is None:
            self._history = HistoryStore(self.cfg.history_root())
        return self._history

    @property
    def flags(self):
        if self._flags is None:
            self._flags = FlagStore(self.cfg.flags_path)
        return self._flags

    def _load(self, locale: str, ns: str) -> dict:
        got = self._ns_cache.get((locale, ns))
        if got is None:
            got = self._ns_cache[(locale, ns)] = self.catalog.load(locale, ns)
        return got

    # -- bookkeeping -------------------------------------------------------
    def log(self, text: str) -> None:
        lines = self.rec.setdefault("lines", [])
        if len(lines) < MAX_LINES:
            lines.append(text)

    def count(self, pos, n: int | None) -> None:
        """``None`` / negative = whole scope (size unknown)."""
        key = _pos_key(pos)
        if n is None:
            self.counts[key] = -1
        elif self.counts.get(key, 0) >= 0:
            self.counts[key] = self.counts.get(key, 0) + n

    def leave(self, n: int) -> None:
        self.stats["routed"] += n

    def scope_locales(self) -> list[str]:
        return list(self.rec["scope"].get("locales") or self.cfg.active_targets())

    def scope_namespaces(self) -> list[str]:
        ns = resolve_namespaces(
            self.rec["scope"].get("namespace"), self.rec["scope"].get("namespaces"),
        )
        return ns or list(self.cfg.namespaces_for(self.catalog))

    def expand(self) -> list[list[str]]:
        out: list[list[str]] = []
        for locale in self.scope_locales():
            for ns in self.scope_namespaces():
                for key in self._load(self.cfg.source_locale, ns):
                    if is_verified(self.state.entry(locale, ns, key) or {}):
                        self.stats["skipped_verified"] += 1
                        continue
                    out.append([locale, ns, key])
        return out

    @staticmethod
    def named(ns: str, key: str) -> str:
        return f"{ns}.{key}" if ns else key

    def by_locale(self, keys: list[list[str]]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for locale, ns, key in keys:
            grouped.setdefault(locale, []).append(self.named(ns, key))
        return grouped

    def score_of(self, locale: str, ns: str, key: str) -> float | None:
        row = self.scores.get(locale, ns, key)
        if not row or row.get("quality_score") is None:
            return None
        return float(row["quality_score"])

    def tag(self, locale: str, ns: str, key: str) -> str:
        score = self.score_of(locale, ns, key)
        suffix = f" (score={score:.2f})" if score is not None else ""
        return f"{locale}/{ns}.{key}", suffix

    # -- actions -----------------------------------------------------------
    def ticket(self, locale: str, ns: str, key: str, why: str = "") -> None:
        tag, suffix = self.tag(locale, ns, key)
        self.stats["tickets"] += 1
        self.log(f"{tag}: review ticket{why or suffix}")
        if self.dry:
            return
        src = self._load(self.cfg.source_locale, ns).get(key)
        open_review_queue(self.cfg).enqueue(
            locale=locale,
            namespace=ns,
            key=key,
            reason="low_score",
            source=(src if isinstance(src, str) else None) or None,
            current=self._load(locale, ns).get(key),
        )

    def _items(self, pos, keys, wait=None) -> list[dict[str, Any]]:
        """Continue at ``pos`` — or finish the keys when the script is over."""
        if pos is None:
            if wait is None:
                self.leave(len(keys or []))
                return []
            return [{"pos": None, "keys": keys, "wait": wait}]
        return [{"pos": list(pos), "keys": keys, "wait": wait}]

    # -- block execution ---------------------------------------------------
    def exec_item(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        pos = tuple(item["pos"])
        block = block_at(self.script, pos)
        kind = block["type"]
        keys = item["keys"]
        nxt = next_position(self.script, pos)

        if kind == "if":
            return self._exec_if(pos, block, keys, nxt)
        if kind in ("translate", "rescore"):
            return self._exec_scope_op(kind, pos, keys, nxt)
        if kind == "improve":
            return self._exec_improve(pos, keys, nxt, block)
        if kind == "llm_review":
            return self._exec_review(pos, keys, nxt)
        if kind == "validate":
            return self._exec_validate(pos, keys, nxt)

        keys = self.expand() if keys is None else keys
        self.count(pos, len(keys))
        if kind == "stop":
            self.stats["stopped"] += len(keys)
            self.leave(len(keys))
            return []
        if kind == "verify":
            for locale, ns, key in keys:
                if is_verified(self.state.entry(locale, ns, key) or {}):
                    self.stats["skipped_verified"] += 1
                    continue
                tag, suffix = self.tag(locale, ns, key)
                if self.dry:
                    self.stats["verified"] += 1
                    self.log(f"{tag}: verify{suffix}")
                    continue
                result = verify_translation(
                    self.cfg, locale=locale, namespace=ns, key=key, verified_by="workflow",
                )
                if result.get("ok"):
                    self.stats["verified"] += 1
                    self.log(f"{tag}: verify{suffix}")
            self.leave(len(keys))
            return []
        if kind == "review_ticket":
            for locale, ns, key in keys:
                if is_verified(self.state.entry(locale, ns, key) or {}):
                    self.stats["skipped_verified"] += 1
                    continue
                self.ticket(locale, ns, key)
            self.leave(len(keys))
            return []
        if kind == "flag":
            for locale, ns, key in keys:
                tag, suffix = self.tag(locale, ns, key)
                if not self.dry:
                    self.flags.append({
                        "locale": locale, "namespace": ns, "key": key,
                        "reason": f"workflow {self.spec.name}: flagged{suffix}",
                    })
                self.stats["flagged"] += 1
                self.log(f"{tag}: flagged{suffix}")
            return self._items(nxt, keys)
        if kind == "notify":
            if not self.dry:
                from .notify import notify_project

                notify_project(self.cfg, {
                    "event": "workflow.notify",
                    "workflow": self.spec.name,
                    "keys": len(keys),
                    "block": _pos_key(pos),
                })
            self.log(f"notify: {len(keys)} keys at block {_pos_key(pos)}")
            return self._items(nxt, keys)
        raise ValueError(f"unknown block type {kind!r}")

    def _hardcoded_total(self) -> float | None:
        """High+medium hardcoded hits from the last scan cache (for ``if hardcoded``)."""
        if hasattr(self, "_hc_total"):
            return self._hc_total
        try:
            from .agent_hardcoded import scan_cache_status

            st = scan_cache_status(self.cfg)
            counts = st.get("counts") or {}
            self._hc_total = float(
                int(counts.get("high", 0)) + int(counts.get("medium", 0))
            )
        except Exception:  # noqa: BLE001 - missing cache → treat as unscored
            self._hc_total = None
        return self._hc_total

    def _exec_if(self, pos, block, keys, nxt) -> list[dict[str, Any]]:
        keys = self.expand() if keys is None else keys
        self.count(pos, len(keys))
        yes: list[list[str]] = []
        no: list[list[str]] = []
        for locale, ns, key in keys:
            score = self.score_of(locale, ns, key)
            if block["field"] == "score" and score is None:
                self.stats["skipped_unscored"] += 1
                continue
            hc = self._hardcoded_total() if block["field"] == "hardcoded" else None
            if block["field"] == "hardcoded" and hc is None:
                self.stats["skipped_unscored"] += 1
                continue
            finding_n = 0.0
            if block["field"] == "findings":
                bad = getattr(self, "_finding_keys", None)
                if bad is None:
                    self.stats["skipped_unscored"] += 1
                    continue
                finding_n = 1.0 if (locale, ns, key) in bad else 0.0
            entry = self.state.entry(locale, ns, key) or {}
            ctx = {
                "score": score,
                "hardcoded": hc,
                "findings": finding_n,
                "status": entry.get("status") or "machine",
                "locale": locale,
                "namespace": ns,
            }
            (yes if eval_cond(block, ctx) else no).append([locale, ns, key])
        out: list[dict[str, Any]] = []
        for branch, subset in (("then", yes), ("else", no)):
            if not subset:
                continue
            start = (*pos, branch, 0) if block.get(branch) else nxt
            out.extend(self._items(start, subset))
        return out

    def _submit_or_run(self, kind: str, keys: list[list[str]] | None):
        """Call the op; returns ``(ok, summary, task_ids, data)``."""
        wf = _ops()
        make, fn = {
            "translate": (TranslateRequest, wf.op_translate),
            "rescore": (RescoreRequest, wf.op_rescore),
            "improve": (ImproveRequest, wf.op_improve),
            "llm_review": (ReviewRequest, wf.op_review),
        }[kind]
        scope = self.rec["scope"]
        groups: list[tuple[list[str], list[str] | None]]
        if keys is None:
            groups = [(self.scope_locales(), None)]
        else:
            groups = [([loc], named) for loc, named in self.by_locale(keys).items()]
        tasks: list[str] = []
        ok = True
        summary = ""
        data: dict[str, Any] = {}
        for locales, named in groups:
            req = make(
                locales=locales,
                namespace=scope.get("namespace"),
                namespaces=scope.get("namespaces"),
                keys=named,
            )
            if self.use_queue:
                req.submit = True
            else:
                req.inline = True
            res: OpResult = fn(self.cfg, req)
            self.log(f"{kind}: {res.summary}")
            for line in res.lines[:6]:
                self.log(f"  {line}")
            ok = ok and res.ok
            summary = summary or res.summary
            tasks.extend(str(t) for t in (res.data.get("taskIds") or []))
            for k, v in res.data.items():
                if isinstance(v, int) and not isinstance(v, bool):
                    data[k] = data.get(k, 0) + v
        return ok, summary, list(dict.fromkeys(tasks)), data

    def _after_llm(self, kind, pos, keys, nxt, must_succeed: bool) -> list[dict[str, Any]]:
        if self.dry:
            n = "all keys" if keys is None else f"{len(keys)} keys"
            self.log(f"dry-run: {kind} would run on {n}")
            return self._items(nxt, keys)
        ok, summary, tasks, data = self._submit_or_run(kind, keys)
        if not ok and must_succeed:
            raise RuntimeError(f"{kind} failed: {summary}")
        if kind == "improve":
            self.stats["improved"] += int(data.get("improved") or 0)
            self.stats["skipped_cooldown"] += int(data.get("skippedRecent") or 0)
        if kind == "llm_review" and keys is not None:
            self.stats["llm_reviewed"] += len(keys)
        if tasks and self.use_queue:
            wait = {"tasks": tasks, "kind": kind, "at": _pos_key(pos)}
            return self._items(nxt, keys, wait)
        return self._items(nxt, keys)

    def _exec_scope_op(self, kind, pos, keys, nxt) -> list[dict[str, Any]]:
        if self.rec.get("routeOnly"):
            self.log(f"{kind}: skipped (route only)")
            return self._items(nxt, keys)
        self.count(pos, None if keys is None else len(keys))
        return self._after_llm(kind, pos, keys, nxt, must_succeed=True)

    def _exec_validate(self, pos, keys, nxt) -> list[dict[str, Any]]:
        """Run the catalogue checks on the scope; findings are logged, keys continue.

        Also fills ``_finding_keys`` so a later ``if findings ge 1`` can branch.
        """
        keys = self.expand() if keys is None else keys
        self.count(pos, len(keys))
        if self.dry or not keys:
            self.log(f"dry-run: validate would check {len(keys)} keys" if self.dry else "validate: no keys")
            return self._items(nxt, keys)
        from .types import ValidateRequest
        from .validate import op_validate

        scope = self.rec["scope"]
        res = op_validate(self.cfg, ValidateRequest(
            locales=sorted(self.by_locale(keys)),
            namespace=scope.get("namespace"), namespaces=scope.get("namespaces"),
        ))
        bad: set[tuple[str, str, str]] = set()
        for row in res.data.get("findings") or []:
            if not isinstance(row, dict):
                continue
            loc, ns, key = row.get("locale"), row.get("namespace"), row.get("key")
            if loc is None or key is None:
                continue
            bad.add((str(loc), str(ns or ""), str(key)))
        self._finding_keys = bad
        findings = len(bad)
        self.stats["validated"] += len(keys)
        self.log(f"validate: {res.summary}")
        for line in res.lines[:6]:
            self.log(f"  {line}")
        if findings:
            self.log(
                f"validate: {findings} key(s) with findings; "
                "branch with `if findings ge 1` then Flag / review_ticket"
            )
        return self._items(nxt, keys)

    def _exec_review(self, pos, keys, nxt) -> list[dict[str, Any]]:
        keys = self.expand() if keys is None else keys
        self.count(pos, len(keys))
        if not keys:
            return self._items(nxt, keys)
        return self._after_llm("llm_review", pos, keys, nxt, must_succeed=False)

    def _exec_improve(self, pos, keys, nxt, block=None) -> list[dict[str, Any]]:
        keys = self.expand() if keys is None else keys
        self.count(pos, len(keys))
        cooldown_h = int(getattr(self.cfg, "improve_reject_cooldown_hours", 168))
        max_loops = (block or {}).get("max_loops")
        if max_loops is None:
            max_loops = self.spec.max_improve_loops
        survivors: list[list[str]] = []
        attempts: dict[str, Counter] = {}
        latest: dict[str, dict] = {}
        for locale, ns, key in keys:
            sk = state_key(ns, key)
            src = self._load(self.cfg.source_locale, ns).get(key)
            src_text = src if isinstance(src, str) else ""
            if locale not in attempts:
                attempts[locale] = _improve_attempts(self.history, locale)
                latest[locale] = self.history.latest_by_key(locale)
            tag, suffix = self.tag(locale, ns, key)
            if attempts[locale][(sk, src_hash(src_text))] >= max_loops:
                self.stats["loops_exhausted"] += 1
                self.ticket(locale, ns, key, f" (improve loops exhausted){suffix}")
                self.leave(1)
                continue
            if _stuck_still_cooling(
                latest[locale].get(sk), source=src_text, cooldown_hours=cooldown_h,
            ):
                self.stats["skipped_cooldown"] += 1
                self.log(f"{tag}: improve skipped (cooldown)")
                self.leave(1)
                continue
            self.log(f"{tag}: improve{suffix}")
            survivors.append([locale, ns, key])
        if not survivors:
            return []
        return self._after_llm("improve", pos, survivors, nxt, must_succeed=False)

    # -- driver ------------------------------------------------------------
    def advance(self) -> None:
        """Run ready items until the frontier is empty or only waiting items remain."""
        frontier: list[dict[str, Any]] = self.rec.get("frontier") or []
        self.rec["status"] = "running"
        steps = 0
        try:
            while True:
                if _cancel_flag(self.rec["id"]).is_set():
                    self.rec["status"] = "canceled"
                    self.rec["message"] = "canceled"
                    self.rec["frontier"] = []
                    self.log("canceled")
                    self._finish()
                    return
                idx = next((i for i, it in enumerate(frontier) if not it.get("wait")), None)
                if idx is None:
                    break
                item = frontier.pop(idx)
                frontier[idx:idx] = self.exec_item(item)
                self.rec["frontier"] = frontier
                steps += 1
                if steps % PERSIST_EVERY == 0:
                    self._persist()
        except Exception as exc:  # noqa: BLE001 - surfaced on the run record
            self.rec["status"] = "failed"
            self.rec["message"] = str(exc)
            self.rec["frontier"] = []
            self.log(f"failed: {exc}")
            self._finish()
            return
        self.rec["frontier"] = frontier
        if frontier:
            self.rec["status"] = "waiting"
            self.rec["message"] = "waiting for taskqueue: " + ", ".join(
                dict.fromkeys(t for it in frontier for t in it["wait"]["tasks"])
            )
            self._persist()
            return
        self.rec["status"] = "done"
        self.rec["message"] = ""
        self._finish()

    def probe_waiting(self) -> bool:
        """Release waiting items whose tasks settled. Returns False when a task failed."""
        frontier = self.rec.get("frontier") or []
        keep: list[dict[str, Any]] = []
        for item in frontier:
            wait = item.get("wait")
            if not wait:
                keep.append(item)
                continue
            state = task_state(wait["tasks"])
            if state == "pending":
                keep.append(item)
            elif state == "failed":
                self.rec["status"] = "failed"
                self.rec["message"] = f"{wait['kind']} task failed: {', '.join(wait['tasks'])}"
                self.log(self.rec["message"])
                self.rec["frontier"] = []
                self._finish()
                return False
            else:
                self.log(f"{wait['kind']}: queue tasks finished")
                item = {**item, "wait": None}
                if item["pos"] is None:
                    self.leave(len(item["keys"] or []))
                    continue
                keep.append(item)
        self.rec["frontier"] = keep
        return True

    def _persist(self) -> None:
        self.rec["stats"] = dict(self.stats)
        self.rec["counts"] = self.counts
        if not self.dry:
            _save_run(self.cfg, self.rec)

    def _finish(self) -> None:
        self.rec["finished"] = now_iso()
        self._persist()
        if self.dry or self.rec["status"] != "done":
            return
        wf = _ops()
        s = self.stats
        wf._save_last_run(self.cfg, self.spec.name, {
            "ts": self.rec["finished"],
            "runId": self.rec["id"],
            "counts": self.counts,
            **{k: int(s.get(k, 0)) for k in (
                "routed", "verified", "improved", "tickets", "flagged", "llm_reviewed",
            )},
        })
        if self.spec.notify == "webhook" and (s.get("tickets") or s.get("flagged")):
            from .notify import notify_project

            notify_project(self.cfg, {
                "event": "workflow.routed",
                "workflow": self.spec.name,
                "tickets": int(s.get("tickets", 0)),
                "flagged": int(s.get("flagged", 0)),
            })


def _result(spec: "WorkflowSpec", rec: dict[str, Any]) -> OpResult:
    stats = {k: int(rec.get("stats", {}).get(k, 0)) for k in STAT_KEYS}
    status = rec.get("status")
    dry = bool(rec.get("dryRun"))
    if status == "failed":
        summary = f"workflow {spec.name} failed: {rec.get('message')}"
    elif status == "waiting":
        summary = f"workflow {spec.name} {rec.get('message')}"
    else:
        summary = (
            f"workflow {spec.name}: verified={stats['verified']} improved={stats['improved']} "
            f"tickets={stats['tickets']} flagged={stats['flagged']} "
            f"llm_reviewed={stats['llm_reviewed']} cooldown_skip={stats['skipped_cooldown']}"
            + (" (dry-run)" if dry else "")
        )
    return OpResult(
        ok=status != "failed",
        exit_code=1 if status == "failed" else 0,
        command="workflow",
        summary=summary,
        lines=(rec.get("lines") or [])[:200],
        data={
            "workflow": spec.name,
            "high": spec.high,
            "low": spec.low,
            **stats,
            "skipped_cooldown": stats["skipped_cooldown"],
            "dry_run": dry,
            "runId": rec["id"],
            "status": status,
            "counts": rec.get("counts") or {},
            "run": describe_run(rec),
        },
    )


def start_run(cfg: ProjectConfig, spec: "WorkflowSpec", req: "WorkflowRequest") -> OpResult:
    rec = {
        "id": f"wf_{now_iso().replace(':', '').replace('-', '')[:15]}_{secrets.token_hex(3)}",
        "workflow": spec.name,
        "status": "running",
        "dryRun": bool(req.dry_run),
        "routeOnly": bool(req.route_only),
        "useQueue": bool(
            not req.dry_run and not req.inline and (req.submit or tq_available())
        ),
        "scope": {
            "locales": list(req.locales or []) or None,
            "namespace": req.namespace,
            "namespaces": req.namespaces,
        },
        "frontier": [{"pos": [0], "keys": None, "wait": None}] if spec.active_script() else [],
        "counts": {},
        "stats": {},
        "lines": [],
        "message": "",
        "started": now_iso(),
        "finished": None,
    }
    run = _Run(cfg, spec, rec)
    with _run_lock(rec["id"]):
        run._persist()  # visible (and cancelable) while it is still running
        run.advance()
    _release_run(rec["id"], rec.get("status"))
    return _result(spec, rec)


def resume_run(cfg: ProjectConfig, spec: "WorkflowSpec", run_id: str) -> OpResult | None:
    """Continue a waiting or stalled running run; idempotent. ``None`` if unknown."""
    if not RUN_ID.fullmatch(run_id or ""):
        return None
    with _run_lock(run_id):
        rec = load_run(cfg, run_id)
        if rec is None:
            return None
        status = rec.get("status")
        if status == "waiting":
            run = _Run(cfg, spec, rec)
            if run.probe_waiting():
                run.advance()
        elif status == "running":
            # Process died mid-advance: frontier was checkpointed; continue it.
            run = _Run(cfg, spec, rec)
            run.advance()
        result = _result(spec, rec)
    _release_run(run_id, rec.get("status"))
    return result


def cancel_run(cfg: ProjectConfig, run_id: str) -> dict[str, Any] | None:
    if not RUN_ID.fullmatch(run_id or ""):
        return None
    lock = _run_lock(run_id)
    if not lock.acquire(blocking=False):
        # Mid-run in another thread: it stops at the next item boundary.
        _cancel_flag(run_id).set()
        rec = load_run(cfg, run_id)
        return describe_run(rec) if rec else None
    try:
        rec = load_run(cfg, run_id)
        if rec is None:
            return None
        if rec.get("status") in ("waiting", "running"):
            rec["status"] = "canceled"
            rec["frontier"] = []
            rec["message"] = "canceled"
            rec["finished"] = now_iso()
            _save_run(cfg, rec)
        return describe_run(rec)
    finally:
        lock.release()
        _release_run(run_id, "canceled")
