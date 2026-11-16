"""``llm-localizator cycle``: one pass over the localization loop, one report (P5, ADR-126).

Runs the steps that already exist, in order, and writes
``<data home>/reports/cycle-<ts>.md`` (and ``.json``):

1. ``check-keys``: every used key exists; en-XX is current;
2. ``validate`` on the target locales (frozen layout locales: gaps are warnings);
3. translation status per locale; with ``translate=True`` the due strings are
   queued through taskqueue (``translate --submit``), never run in this process;
4. ``review-risk`` per active locale: the translations a person should read first;
5. hardcoded status: scan cache, the latest ``[qa]`` crawl, and the next step.

It changes nothing in the consumer repo. The only write is the report, and the
queue entry when ``translate`` is set.

``repair`` queues a forced retranslation of keys failing a check a retranslation can
fix. ``follow`` (A8) then waits for those queue tasks, validates only those keys, queues
the ones still failing once more, and lists the keys that fail after ``MAX_ATTEMPTS``
for a person (``set``, glossary, context note). Still one process, no new orchestrator.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["op_cycle"]


#: Findings a forced retranslation can fix (the model got the structure wrong).
REPAIRABLE = ("V03", "V04", "V43", "V46", "V47")
MAX_ATTEMPTS = 2
POLL_S = 20.0


def _wait(task_ids: list[str], timeout_s: float, *, state=None, sleep=time.sleep) -> str:
    """``done``, ``failed`` or ``timeout`` for queued tasks (polls ``task_state``)."""
    from ..projects.taskqueue import task_state

    probe = state or task_state
    deadline = time.monotonic() + timeout_s
    while True:
        status = probe(task_ids)
        if status != "pending":
            return status
        if time.monotonic() >= deadline:
            return "timeout"
        sleep(POLL_S)


def _still_failing(cfg, catalog, loc: str, keys: set[str]) -> set[str]:
    from ..pipeline.validate import run_validation

    report = run_validation(cfg, catalog, locales=[loc])
    return {k for f in report.errors if f.locale == loc and f.check in REPAIRABLE
            for k in [f"{f.namespace}.{f.key}" if f.namespace else f.key] if k in keys}


def _follow(cfg, catalog, fixable: dict[str, list[str]], first_ids: dict[str, list[str]],
            timeout_s: float, *, state=None, sleep=time.sleep, submit=None) -> dict:
    """Wait, revalidate the repaired keys, retry once, and name the stuck ones."""
    from .translate import op_translate
    from .types import TranslateRequest

    submit = submit or (lambda loc, keys: op_translate(cfg, TranslateRequest(
        locales=[loc], keys=sorted(keys), force=True, submit=True)))
    out: dict[str, dict] = {}
    for loc, keys in fixable.items():
        pending, ids, attempt = set(keys), first_ids.get(loc, []), 1
        status = "done"
        while True:
            status = _wait(ids, timeout_s, state=state, sleep=sleep)
            if status == "timeout":
                break
            pending = _still_failing(cfg, catalog, loc, pending)
            if not pending or attempt >= MAX_ATTEMPTS:
                break
            attempt += 1
            ids = list((submit(loc, pending).data or {}).get("taskIds") or [])
        out[loc] = {"status": status, "attempts": attempt, "fixed": len(set(keys)) - len(pending),
                    "stuck": sorted(pending)}
    return out


def op_cycle(cfg: ProjectConfig, *, locales: list[str] | None = None, translate: bool = False,
             repair: bool = False, review_limit: int = 15, follow: bool = False,
             follow_timeout: float = 3600.0) -> OpResult:
    from ..catalog import catalog_for
    from ..catalog.io import atomic_write_text
    from ..pipeline.validate import run_validation
    from .agent_hardcoded import scan_cache_status
    from .review_risk import op_review_risk
    from .status import collect
    from .web_runtime import op_check_keys

    active = [loc for loc in (locales or cfg.active_targets()) if loc in cfg.targets]
    catalog = catalog_for(cfg)
    stages: dict[str, dict] = {}
    md = [f"# Localization cycle — {cfg.name}", "",
          f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · locales: {', '.join(active) or '—'}", ""]

    if cfg.scan_src_dirs:
        keys = op_check_keys(cfg)
        stages["check_keys"] = {"ok": keys.ok, "summary": keys.summary,
                                "missing": len(keys.data.get("missing", {}))}
        md += ["## 1. Keys", "", keys.summary, *[f"- {line}" for line in keys.lines[:20]], ""]

    report = run_validation(cfg, catalog, locales=active or None)
    errors = [f for f in report.errors if f.locale in active]
    stages["validate"] = {"errors": len(errors), "warnings": len(report.warnings)}
    md += ["## 2. Validate", "", f"{len(errors)} error(s), {len(report.warnings)} warning(s) "
           "in the active locales.", *[f"- [{f.check}] {f.locale}/{f.key}: {f.message}" for f in errors[:25]], ""]
    fixable: dict[str, list[str]] = {}
    for f in errors:
        if f.check in REPAIRABLE:
            fixable.setdefault(f.locale, []).append(f"{f.namespace}.{f.key}" if f.namespace else f.key)
    if fixable and repair:
        from .translate import op_translate
        from .types import TranslateRequest

        stages["repair"] = {}
        first_ids: dict[str, list[str]] = {}
        for loc, keys in fixable.items():
            queued = op_translate(cfg, TranslateRequest(locales=[loc], keys=sorted(set(keys)),
                                                        force=True, submit=True))
            first_ids[loc] = list((queued.data or {}).get("taskIds") or [])
            stages["repair"][loc] = {"keys": len(set(keys)), "ok": queued.ok, "summary": queued.summary}
            md.append(f"Repair queued for {loc}: {len(set(keys))} key(s) — {queued.summary}")
        md.append("")
        if follow:
            followed = _follow(cfg, catalog, fixable, first_ids, follow_timeout)
            stages["follow"] = followed
            md += ["### Repair follow-up", ""]
            for loc, f in followed.items():
                md.append(f"- {loc}: {f['fixed']} fixed after {f['attempts']} attempt(s), "
                          f"{len(f['stuck'])} still failing ({f['status']})")
                md += [f"    - `{k}`: fix with `llm-localizator set`, a glossary entry or a context note"
                       for k in f["stuck"]]
            md.append("")
    elif fixable:
        n = sum(len(set(v)) for v in fixable.values())
        md += [f"{n} key(s) fail checks a retranslation can fix ({', '.join(REPAIRABLE)}). "
               "Rerun with `--repair` to queue them (or fix one with `llm-localizator set`).", ""]

    rows = [r for r in collect(cfg, catalog) if r.locale in active]
    pending = sum(r.missing + r.stale for r in rows)
    stages["status"] = {r.locale: {"translated": r.translated, "total": r.total,
                                   "pending": r.missing + r.stale} for r in rows}
    md += ["## 3. Translation status", ""] + [
        f"- {r.locale}: {r.translated}/{r.total} ({r.missing + r.stale} due)" for r in rows] + [""]
    if translate and pending:
        from .translate import op_translate
        from .types import TranslateRequest

        queued = op_translate(cfg, TranslateRequest(locales=active, submit=True))
        stages["translate"] = {"ok": queued.ok, "summary": queued.summary}
        md += [f"Queued: {queued.summary}", ""]
    elif pending:
        md += [f"{pending} string(s) due. Rerun with `--translate` to queue them "
               "(`llm-localizator guide` names the command for your approach).", ""]

    md += ["## 4. Review first", ""]
    stages["review"] = {}
    for loc in active:
        risk = op_review_risk(cfg, locale=loc, limit=review_limit)
        stages["review"][loc] = {"high": risk.data.get("high", 0), "total": risk.data.get("total", 0)}
        md += [f"### {loc}", "", risk.summary, ""] + [f"    {line}" for line in risk.lines] + [""]

    hc = scan_cache_status(cfg)
    stages["hardcoded"] = {"counts": hc.get("counts"), "stale": hc.get("stale"),
                           "qaCrawl": hc.get("qaCrawl"), "next": hc.get("next")}
    md += ["## 5. Hardcoded text", "",
           f"Scan: {hc.get('counts')} ({'stale' if hc.get('stale') else 'current'}).",
           *([f"Latest crawl: {hc['qaCrawl']['leftovers']} leftovers, {hc['qaCrawl']['dynamic']} dynamic "
              f"({hc['qaCrawl']['dir']})"] if hc.get("qaCrawl") else []),
           "", "Next:", *[f"- `{s['cmd']}`: {s['why']}" for s in hc.get("next") or []], ""]

    md += ["## Guides", "",
           "- Reading this report, the review sheet, before you ship: `llm-localizator help human`, section 4",
           "- What to run when a check fails: `llm-localizator help agent`, section 5",
           "- The hardcoded-text loop: `llm-localizator help agent`, section 4", ""]

    out_dir = Path(cfg.data_root()) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md_path = out_dir / f"cycle-{stamp}.md"
    atomic_write_text(md_path, "\n".join(md) + "\n")
    atomic_write_text(out_dir / f"cycle-{stamp}.json", json.dumps(stages, ensure_ascii=False, indent=2,
                                                                 default=str) + "\n")
    high = sum(v["high"] for v in stages["review"].values())
    ok = not errors and stages.get("check_keys", {}).get("ok", True)
    summary = (f"{len(errors)} validation error(s), {pending} due, {high} high-risk translation(s) "
               f"to review -> {md_path}")
    return OpResult(ok=ok, exit_code=0 if ok else 1, command="cycle", summary=summary,
                    lines=[summary], data={"report": str(md_path), **stages})
