"""Gather new/changed work.

No watcher daemon (ADR-1): this is a CLI / taskqueue job that projects run on a
schedule or from CI. Chaining to translate belongs in the YAML (``on_complete``),
not an in-process ``tq`` call (taskqueue S6).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from ..catalog import Catalog, StateStore, build_catalog
from ..catalog.io import atomic_write_text
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, submit
from ..scan import scanner_from_config
from .translate import collect_work

__all__ = ["SyncResult", "current_branch", "run_sync"]

Reporter = Callable[[str], None]


@dataclass
class SyncResult:
    usages: int = 0
    hardcoded: int = 0
    missing_or_stale: int = 0
    proposed_keys: int = 0
    translate_submitted: bool = False
    dry_run: bool = False
    details: list[str] = field(default_factory=list)
    exit_code: int = 0
    escalated: int = 0
    branch_warning: str = ""
    manifest_file: str = ""
    manifest_added: int = 0
    manifest_changed: int = 0
    manifest_removed: int = 0


def supervisor_for(cfg: ProjectConfig, locale: str) -> str | None:
    """First approved Supervisor whose locale chips include ``locale`` (or have none)."""
    from ..projects.accounts import STATUS_APPROVED, AccountStore

    try:
        users = AccountStore(cfg.state_root()).list_users()
    except OSError:
        return None
    for user in users:
        if user.status == STATUS_APPROVED and user.role == "Supervisor":
            if not user.locales or locale in user.locales:
                return user.username
    return None


def escalate_overdue(cfg: ProjectConfig, locales: list[str], report: Reporter) -> int:
    """Send the ``[notify]`` webhook once for each review ticket open past the limit."""
    days = getattr(cfg, "review_escalate_after_days", 0)
    if not days:
        return 0
    from ..catalog.review_queue import open_review_queue
    from ..ops.notify import notify_project

    queue = open_review_queue(cfg)
    sent = 0
    for locale in locales:
        overdue = queue.overdue(locale, days)
        for ticket in overdue:
            notify_project(cfg, {
                "event": "review-escalation", "project": cfg.name, "locale": locale,
                "ticket": ticket.id, "namespace": ticket.namespace, "key": ticket.key,
                "assignee": ticket.assignee, "reason": ticket.reason,
                "supervisor": supervisor_for(cfg, locale),
                "open_since": ticket.created_at,
            }, wait=True)
        if overdue:
            queue.mark_escalated(locale, [t.id for t in overdue])
            sent += len(overdue)
    if sent:
        report(f"escalated {sent} review ticket(s) open longer than {days} day(s)")
    return sent


def record_source_changes(cfg: ProjectConfig, work: list, state: StateStore) -> int:
    """Log each stale key whose English changed since it was translated (ADR-52)."""
    from ..catalog.source_history import SourceHistory

    changes = []
    for item in work:
        if item.status != "stale":
            continue
        entry = state.entry(item.locale, item.namespace, item.key) or {}
        changes.append((item.namespace, item.key, entry.get("src_text") or "", item.source))
    return SourceHistory(cfg.state_root()).record_changes(changes)


def current_branch(root) -> str | None:
    """The checked-out git branch, or ``None`` outside a repository / on a detached HEAD."""
    try:
        done = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(root), capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = done.stdout.strip() if done.returncode == 0 else ""
    return name or None


def run_sync(
    cfg: ProjectConfig,
    catalog: Catalog | None = None,
    *,
    locales: list[str] | None = None,
    dry_run: bool = False,
    submit_translate: bool = False,
    strict_branch: bool = False,
    diff: bool = False,
    exit_nonzero: bool = False,
    report: Reporter = print,
) -> SyncResult:
    """Scan (if configured) and count translation work.

    ``submit_translate`` defaults to False: queue blueprints chain via
    ``on_complete``. Pass True only for interactive one-shot gather+enqueue.
    """
    result = SyncResult(dry_run=dry_run)
    expected = getattr(cfg, "source_branch", "main")
    branch = current_branch(cfg.root)
    if branch is not None and expected and branch != expected:
        result.branch_warning = (
            f"branch {branch!r} is not the source branch {expected!r}: pushing source "
            f"strings from here can delete another branch's translations"
        )
        report(f"warn: {result.branch_warning}")
        if strict_branch:
            result.exit_code = 1
    catalog = catalog or build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale
    )
    state = StateStore(cfg.state_root())
    targets = locales if locales is not None else list(cfg.active_targets())
    ns_list = cfg.namespaces_for(catalog)

    # ---- scan --------------------------------------------------------------
    if cfg.scan_adapter and cfg.scan_src_dirs:
        scanner = scanner_from_config(cfg)
        scan_result = scanner.scan()
        result.usages = len(scan_result.usages)
        result.hardcoded = len(scan_result.hardcoded)
        out_dir = cfg.scan_out_root()
        if out_dir and not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            for namespace, keys in scan_result.by_namespace().items():
                path = out_dir / f"{namespace}.json"
                atomic_write_text(path, json.dumps(keys, ensure_ascii=False, indent=2) + "\n")
            proposed = out_dir / "proposed_keys.json"
            payload = [
                {"text": h.text, "file": h.file, "line": h.line, "reason": h.reason}
                for h in scan_result.hardcoded
            ]
            atomic_write_text(proposed, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            result.proposed_keys = len(payload)
        report(
            f"scan: {scan_result.files_scanned} file(s), {result.usages} usage(s), "
            f"{result.hardcoded} hardcoded"
        )
    else:
        report("scan: skipped (no [scan] adapter / src_dirs)")

    if not dry_run:
        result.escalated = escalate_overdue(cfg, targets, report)

    # ---- translation backlog -----------------------------------------------
    work = collect_work(
        cfg, catalog, state, locales=targets, namespaces=ns_list, force=False,
    )
    result.missing_or_stale = len(work)
    if not dry_run:
        record_source_changes(cfg, work, state)
    for item in work[:50]:
        result.details.append(f"{item.locale}/{item.namespace}.{item.key}")
    if len(work) > 50:
        result.details.append(f"... and {len(work) - 50} more")

    report(f"backlog: {result.missing_or_stale} missing/stale key-locale pair(s)")

    if diff:
        from .manifest import build_manifest, write_manifest

        manifest = build_manifest(
            cfg, catalog, state, locales=targets, namespaces=ns_list, work=work,
        )
        result.manifest_added = len(manifest["added"])
        result.manifest_changed = len(manifest["changed"])
        result.manifest_removed = len(manifest["removed"])
        if dry_run:
            report("(dry-run) manifest not written")
        else:
            result.manifest_file = str(write_manifest(cfg, manifest))
            report(f"manifest: {result.manifest_file}")
        report(
            f"manifest: {result.manifest_added} added, {result.manifest_changed} changed, "
            f"{result.manifest_removed} removed, {manifest['unchanged_count']} unchanged"
        )
        if exit_nonzero and (result.manifest_added or result.manifest_changed):
            result.exit_code = 1

    if dry_run or not work:
        if dry_run:
            report("(dry-run) not submitting translate")
        elif not work:
            report("nothing to translate")
        return result

    if not getattr(cfg, "translate_enabled", True):
        report("translate disabled ([translate] enabled = false) — not submitting")
        return result

    if submit_translate:
        try:
            outcome = submit(cfg, "translate")
            result.translate_submitted = outcome.ok
            if outcome.ok:
                report(outcome.message or "submitted incremental translate job to taskqueue")
            else:
                report(f"warn: {outcome.message or f'translate submit exited {outcome.exit_code}'}")
        except TaskqueueNotFound as exc:
            report(f"warn: {exc} — run `llm-localizator run-translate` directly")
    return result
