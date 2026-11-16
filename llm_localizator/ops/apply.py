"""Apply mode: write catalogue additions from a hardcoded-string scan.

This is the highest-impact operation: it modifies the consumer project's
catalogue files.  Safety gates:

- Requires ``req.confirm = True``; dry-run shows what *would* change.
- Only creates **new** keys (source text); never overwrites existing translations.
- Hardcoded strings the user accepted with ``scan-decide`` (ADR-55) become source-locale
  keys here; nothing is written for a string nobody accepted.
- Source-file edits (replacing hardcoded literals with ``t()`` calls) are **not**
  performed automatically — they are shown in the report for a developer or AI
  agent to apply.  Automatic source rewriting is intentionally out of scope
  (ADR-32: the engine does not rewrite consumer source).
- New target-locale placeholders get no state entry, so ``translate`` sees them as
  missing and picks them up.
- If ``req.enqueue_translate`` is True and the taskqueue is available, a
  translate task is enqueued for the new keys.
"""

from __future__ import annotations

from ..catalog import catalog_for
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.scan_decisions import ACCEPTED, APPLIED, KIND_HIT, ScanDecisions, hit_id
from ..projects import ProjectConfig
from ..scan import scanner_from_config
from .agent_hardcoded import _scan_files, catalogue_gap_audit
from .patch import _namespace_from_path, select_patches, suggest_key
from .types import ApplyRequest, OpResult

__all__ = ["enqueue_translate_task", "op_apply", "plan_source_key", "write_source_keys"]


def _apply_catalogue_gaps(
    cfg: ProjectConfig,
    gap_records: list[dict],
    dry_run: bool,
) -> tuple[int, list[str]]:
    """Create missing catalogue entries (source text only).

    Returns (keys_written, log_lines).
    """
    cat = catalog_for(cfg)
    # Group gaps by namespace and locale
    by_ns: dict[str, dict[str, list[dict]]] = {}
    for g in gap_records:
        by_ns.setdefault(g["namespace"], {}).setdefault(g["locale"], []).append(g)

    written = 0
    log: list[str] = []

    for ns, locale_gaps in by_ns.items():
        for locale, recs in locale_gaps.items():
            if locale == cfg.source_locale:
                continue
            try:
                existing = cat.load(locale, ns or None)
            except Exception as exc:
                # A failed read must never fall back to {}: saving the merge
                # would overwrite the whole namespace with only the new keys.
                log.append(f"  skip {ns or '(default)'}/{locale}: cannot read catalogue ({exc})")
                continue
            updates: dict[str, str] = {}
            for r in recs:
                key = r["key"]
                if key in existing and existing[key].strip():
                    continue  # already translated, skip
                # Write source text as placeholder — triggers translate later
                updates[key] = r["source_text"]
                written += 1
                log.append(f"  add  {ns or '(default)'}/{locale}/{key}")
            if updates and not dry_run:
                cat.write(locale, ns or None, updates)

    return written, log


def _flat_catalogue(cat) -> bool:
    """True for catalogues with no namespaces, where a key needs no path-derived prefix."""
    try:
        names = set(cat.namespaces())
    except Exception:
        return False
    return bool(names) and names <= {""}


def plan_source_key(
    cat,
    source_locale: str,
    text: str,
    file: str,
    *,
    existing_key: str | None = None,
    override: str | None = None,
    pending: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Pick the source-locale key for a hardcoded string, never clobbering another string.

    ``pending`` holds keys already planned in this batch, per namespace, so two hits
    cannot take the same key. Text already in the catalogue is reused, not duplicated.
    """
    text = text.strip()
    if existing_key and not override:
        return {"namespace": "", "key": existing_key, "reuse": True, "text": text}
    ns = "" if _flat_catalogue(cat) else _namespace_from_path(file)
    try:
        current = dict(cat.load(source_locale, ns or None))
    except FileNotFoundError:  # a new namespace has nothing to collide with
        current = {}
    current.update((pending or {}).get(ns, {}))
    base = override or suggest_key(text)
    key, n = base, 2
    while key in current:
        if str(current[key]).strip() == text:
            return {"namespace": ns, "key": key, "reuse": True, "text": text}
        key, n = f"{base}{n}", n + 1
    return {"namespace": ns, "key": key, "reuse": False, "text": text}


def write_source_keys(cfg: ProjectConfig, items: list[dict], dry_run: bool) -> list[dict]:
    """Add accepted strings to the source catalogue; caller holds the mutation lock.

    ``items`` are decision entries (``id``, ``text``, ``file``, optional ``existing_key``,
    ``key``). Returns one plan dict per item with ``id``, ``namespace``, ``key`` and
    ``written``.
    """
    cat = catalog_for(cfg)
    pending: dict[str, dict[str, str]] = {}
    results: list[dict] = []
    for item in items:
        if item.get("reuse"):
            plan = {
                "namespace": item.get("namespace") or "", "key": item.get("key", ""),
                "reuse": True, "text": item["text"].strip(),
            }
        else:
            plan = plan_source_key(
                cat, cfg.source_locale, item["text"], item["file"],
                existing_key=item.get("existing_key"), override=item.get("key"), pending=pending,
            )
        plan["id"] = item.get("id", "")
        plan["written"] = not plan["reuse"]
        if plan["written"]:
            pending.setdefault(plan["namespace"], {})[plan["key"]] = plan["text"]
        results.append(plan)
    if not dry_run:
        for ns, added in pending.items():
            # No fallback to {}: a read error must abort rather than overwrite.
            existing = dict(cat.load(cfg.source_locale, ns or None))
            existing.update(added)
            cat.save(cfg.source_locale, ns or None, existing)
    return results


def enqueue_translate_task(cfg: ProjectConfig) -> bool:
    try:
        from ..projects.taskqueue import tq_available, submit as tq_submit

        if tq_available():
            tq_submit(cfg, "translate", {})
            return True
    except Exception:
        pass
    return False


def op_apply(cfg: ProjectConfig, req: ApplyRequest) -> OpResult:
    """Scan + apply catalogue additions.

    Writes only the catalogue; never rewrites consumer source files.
    Requires ``req.confirm = True`` (or ``--dry-run`` for preview).
    """
    if not req.confirm and not req.dry_run:
        return OpResult(
            ok=False, exit_code=64, command="apply",
            summary="apply mode requires --confirm (or --dry-run to preview)",
            lines=[
                "Pass --confirm to apply changes, or --dry-run to preview.",
                "Source-file edits are shown but NOT applied automatically.",
            ],
        )

    adapter = req.adapter or cfg.scan_adapter
    if not adapter:
        return OpResult(
            ok=False, exit_code=64, command="apply",
            summary="no scan adapter configured",
            lines=["Set [scan] adapter in .llm-localize.toml or pass --adapter."],
        )
    if not cfg.scan_src_dirs:
        return OpResult(
            ok=False, exit_code=64, command="apply",
            summary="no [scan] src_dirs configured",
            lines=[],
        )

    try:
        scanner = scanner_from_config(cfg, adapter)
    except ValueError as exc:
        return OpResult(ok=False, exit_code=64, command="apply", summary=str(exc))

    result, _ = _scan_files(scanner, req.limit)
    hits = [
        {"text": h.text, "file": h.file, "line": h.line,
         "reason": h.reason, "source": "regex"}
        for h in result.hardcoded
    ]
    hc_patches = select_patches(cfg, hits, scanner.routing_note)
    gap_records, _ = catalogue_gap_audit(cfg)

    store = ScanDecisions.for_project(cfg)
    accepted = [
        {**entry, "id": item_id}
        for item_id, entry in store.items().items()
        if entry.get("kind", KIND_HIT) == KIND_HIT and entry.get("status") == ACCEPTED
    ]
    live_ids = {hit_id(h["file"], h["text"]) for h in hits}
    accepted = [a for a in accepted if a["id"] in live_ids]

    def _write() -> tuple[int, list[str], list[dict]]:
        # Apply catalogue gap additions, then accepted hardcoded strings.
        n, log = _apply_catalogue_gaps(cfg, gap_records, req.dry_run)
        planned = write_source_keys(cfg, accepted, req.dry_run) if accepted else []
        for plan in planned:
            verb = "add" if plan["written"] else "reuse"
            log.append(f"  {verb}  {cfg.source_locale}/{plan['namespace'] or '(default)'}/{plan['key']}")
        n += sum(1 for p in planned if p["written"])
        if not req.dry_run:
            by_id = {a["id"]: a for a in accepted}
            for plan in planned:
                store.decide(
                    plan["id"], APPLIED, by=by_id[plan["id"]].get("by", ""),
                    namespace=plan["namespace"], key=plan["key"],
                )
        return n, log, planned

    if req.dry_run:
        keys_written, write_log, planned = _write()
    else:
        with project_mutation_lock(cfg):
            keys_written, write_log, planned = _write()

    # Enqueue translate for new keys (live run only)
    tq_submitted = False
    if not req.dry_run and req.enqueue_translate and keys_written > 0:
        tq_submitted = enqueue_translate_task(cfg)

    # Build report
    dry_label = "[DRY-RUN] " if req.dry_run else ""
    lines: list[str] = [
        f"# {dry_label}Apply report — {cfg.name}",
        "",
        f"Catalogue keys {'would be' if req.dry_run else ''} added: {keys_written}",
        "",
    ]

    if write_log:
        lines.append("## Catalogue writes")
        lines.append("")
        lines.extend(write_log)
        lines.append("")

    if hc_patches:
        lines += [
            "## Source-file edits required (not applied automatically)",
            "",
            f"Routing: {scanner.routing_note or 'use the project translation function.'}",
            "",
        ]
        by_file: dict[str, list[dict]] = {}
        for p in hc_patches:
            by_file.setdefault(p["file"], []).append(p)
        for path, patches in by_file.items():
            lines.append(f"### {path}")
            lines.append("")
            for p in patches:
                lines.append(
                    f"- line {p['line']}: replace `{p['text']!r}` "
                    f"→ use `{p['suggested_catalogue_key']}`"
                )
            lines.append("")

    if tq_submitted:
        lines += ["Translate task enqueued for new keys.", ""]

    summary = (
        f"{dry_label}{keys_written} catalogue key(s) {'would be ' if req.dry_run else ''}"
        f"added, {len(hc_patches)} source edit(s) pending"
    )

    return OpResult(
        ok=True, exit_code=0, command="apply", summary=summary,
        lines=lines,
        data={
            "keysWritten": keys_written,
            "dryRun": req.dry_run,
            "hardcodedPatches": hc_patches,
            "catalogueGaps": gap_records,
            "sourceKeys": planned,
            "tqSubmitted": tq_submitted,
        },
    )
