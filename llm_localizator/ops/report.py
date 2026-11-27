"""``llm-localizator report``: one shareable page on where localization stands (ADR-163).

For people who do not run the CLI (product owners, translators, reviewers) and for
CI to attach to a pull request. Strictly read-only: it gathers what ``status``,
``validate``, ``check-keys``, the hardcoded scan cache, ``review-risk``, drafts, the
budget ledger and run records already know, and renders one page with a verdict.

Unlike ``cycle`` (ADR-126), it never queues work and writes nothing except the
``--out`` file the caller names.

Verdict:
* ``no-go``: a used key is missing from the catalogue, or an active locale has
  validation errors;
* ``go-with-notes``: anything a person should look at (warnings, high-risk keys,
  drafts, hardcoded hits in the last scan, stale scan);
* ``go``: none of the above.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any

from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["op_report", "gather", "render_markdown", "render_html", "REPORT_FORMATS"]

REPORT_FORMATS = ("md", "html", "json")


def gather(cfg: ProjectConfig, *, locales: list[str] | None = None, review_limit: int = 5) -> dict[str, Any]:
    """Collect the report facts. Read-only."""
    from ..catalog import catalog_for
    from ..catalog.budget import BudgetStore
    from ..catalog.drafts import DraftStore
    from ..pipeline.run_manifest import iter_run_records
    from ..pipeline.validate import run_validation
    from .agent_hardcoded import scan_cache_status
    from .review_risk import op_review_risk
    from .status import collect

    active = [loc for loc in (locales or cfg.active_targets()) if loc in cfg.targets]
    catalog = catalog_for(cfg)
    facts: dict[str, Any] = {
        "project": cfg.name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source_locale": cfg.source_locale,
        "active": active,
        "frozen": [loc for loc in cfg.targets if loc in set(cfg.frozen or [])],
    }

    # "Has text" counts values with no state record too: for a reader the string is
    # translated; the missing record is bookkeeping (`adopt`), shown in its own column.
    facts["coverage"] = [
        {"locale": r.locale, "translated": r.translated, "total": r.total,
         "has_text": r.translated + r.no_record,
         "pct": round(100.0 * (r.translated + r.no_record) / r.total, 1) if r.total else 100.0,
         "missing": r.missing, "stale": r.stale, "no_record": r.no_record, "frozen": r.frozen}
        for r in collect(cfg, catalog)
    ]

    if cfg.scan_src_dirs:
        from .web_runtime import op_check_keys

        keys = op_check_keys(cfg)
        facts["keys"] = {"ok": keys.ok, "summary": keys.summary,
                         "missing": len((keys.data or {}).get("missing", {}) or {})}
    else:
        facts["keys"] = None

    report = run_validation(cfg, catalog, locales=active or None)
    errors = [f for f in report.errors if f.locale in active]
    warnings = [f for f in report.warnings if f.locale in active]
    by_check: dict[str, int] = {}
    for f in errors:
        by_check[f.check] = by_check.get(f.check, 0) + 1
    facts["validate"] = {
        "errors": len(errors), "warnings": len(warnings),
        "errors_by_check": dict(sorted(by_check.items(), key=lambda kv: -kv[1])),
        "examples": [f"[{f.check}] {f.locale} {f.namespace + '.' if f.namespace else ''}{f.key}: {f.message}"
                     for f in errors[:10]],
    }

    hc = scan_cache_status(cfg)
    facts["hardcoded"] = {"counts": hc.get("counts") or {}, "stale": bool(hc.get("stale")),
                          "cached": bool(hc.get("cached"))}

    review: dict[str, Any] = {}
    for loc in active:
        risk = op_review_risk(cfg, locale=loc, limit=review_limit)
        if risk.ok:
            review[loc] = {"high": risk.data.get("high", 0), "total": risk.data.get("total", 0),
                           "top": [{"key": r.get("key"), "risk": r.get("risk"),
                                    "why": r.get("why") or r.get("reasons")}
                                   for r in (risk.data.get("rows") or [])[:review_limit]]}
    facts["review"] = review

    drafts: dict[str, int] = {}
    for item in DraftStore.for_project(cfg).items().values():
        loc = str(item.get("locale") or "")
        drafts[loc] = drafts.get(loc, 0) + 1
    facts["drafts"] = drafts

    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    if cap > 0:
        store = BudgetStore(cfg.budget_root())
        facts["spend"] = {"month_usd": round(store.month_total(), 4), "cap_usd": cap,
                          "remaining_usd": round(store.remaining(cap), 4)}
    else:
        facts["spend"] = None

    facts["runs"] = [
        {"command": r.get("command"), "started_at": r.get("started_at"),
         "locales": r.get("locales") or [], "model": r.get("model"),
         "counts": {k: v for k, v in (r.get("counts") or {}).items() if k in ("written", "total", "work", "skipped")}}
        for r in iter_run_records(cfg.state_root())[:5]
    ]

    facts["verdict"], facts["reasons"], facts["notes"] = _verdict(facts)
    return facts


def _verdict(f: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    notes: list[str] = []
    if f["keys"] is not None and f["keys"]["missing"]:
        reasons.append(f"code uses {f['keys']['missing']} key(s) missing from the catalogue")
    elif f["keys"] is not None and not f["keys"]["ok"]:
        # check-keys also fails on a stale pseudo-locale; that is upkeep, not a missing key.
        notes.append(f"check-keys: {f['keys']['summary']}")
    if f["validate"]["errors"]:
        reasons.append(f"{f['validate']['errors']} validation error(s) in active locales")
    if f["validate"]["warnings"]:
        notes.append(f"{f['validate']['warnings']} validation warning(s)")
    high = sum(v["high"] for v in f["review"].values())
    if high:
        notes.append(f"{high} high-risk translation(s) worth a human read")
    if any(f["drafts"].get(loc) for loc in f["active"]):
        notes.append(f"{sum(f['drafts'].get(loc, 0) for loc in f['active'])} draft(s) waiting for a reviewer")
    counts = f["hardcoded"]["counts"]
    if counts.get("high") or counts.get("medium"):
        notes.append(f"{counts.get('high', 0)} high / {counts.get('medium', 0)} medium hardcoded hit(s) "
                     "in the last scan: wire them or record why not")
    if f["hardcoded"]["stale"]:
        notes.append("hardcoded scan is missing or out of date (`llm-localizator agent-hardcoded --refresh`)")
    unrecorded = sum(r["no_record"] for r in f["coverage"] if r["locale"] in f["active"])
    if unrecorded:
        notes.append(f"{unrecorded} translation(s) exist but are not recorded (`llm-localizator adopt`)")
    due = sum(r["missing"] + r["stale"] for r in f["coverage"] if r["locale"] in f["active"])
    if due:
        notes.append(f"{due} string(s) not yet translated or out of date in active locales")
    verdict = "no-go" if reasons else ("go-with-notes" if notes else "go")
    return verdict, reasons, notes


_COVERAGE_NOTE = ("*Not recorded*: the text exists but the engine has no record of who wrote it or "
                  "which English it matches (`llm-localizator adopt` records it).")
_COVERAGE_NOTE_HTML = ("<p class=meta><i>Not recorded</i>: the text exists but the engine has no record of "
                       "who wrote it or which English it matches (<code>llm-localizator adopt</code>).</p>")

_VERDICT_LABEL = {"go": "GO", "go-with-notes": "GO, with notes", "no-go": "NO-GO"}


def render_markdown(f: dict[str, Any]) -> str:
    out = [f"# Localization report: {f['project']}", "",
           f"{f['generated_at']} · source `{f['source_locale']}` · active: "
           f"{', '.join(f['active']) or '(none)'}"
           + (f" · frozen: {', '.join(f['frozen'])}" if f["frozen"] else ""), "",
           f"## Verdict: {_VERDICT_LABEL[f['verdict']]}", ""]
    out += [f"- **Blocking:** {r}" for r in f["reasons"]]
    out += [f"- {n}" for n in f["notes"]]
    if not f["reasons"] and not f["notes"]:
        out.append("Nothing to fix or review.")
    out += ["", "## Coverage", "", "| Locale | Has text | Missing | Out of date | Not recorded |",
            "|---|---|---|---|---|"]
    for r in f["coverage"]:
        tag = " (frozen)" if r["frozen"] else ""
        out.append(f"| {r['locale']}{tag} | {r['has_text']}/{r['total']} ({r['pct']}%) | "
                   f"{r['missing']} | {r['stale']} | {r['no_record']} |")
    if any(r["no_record"] for r in f["coverage"]):
        out += ["", _COVERAGE_NOTE]
    v = f["validate"]
    out += ["", "## Checks", "",
            f"- Validation (active locales): {v['errors']} error(s), {v['warnings']} warning(s)"
            + (f" — {', '.join(f'{c} ×{n}' for c, n in v['errors_by_check'].items())}" if v["errors_by_check"] else "")]
    out += [f"    - {e}" for e in v["examples"]]
    if f["keys"] is not None:
        out.append(f"- Keys used in code: {f['keys']['summary']}")
    c = f["hardcoded"]["counts"]
    out.append(f"- Hardcoded text (last scan{', stale' if f['hardcoded']['stale'] else ''}): "
               f"{c.get('high', 0)} high, {c.get('medium', 0)} medium, {c.get('low', 0)} low")
    if f["review"]:
        out += ["", "## Review first", ""]
        for loc, r in f["review"].items():
            out.append(f"- **{loc}**: {r['high']} high-risk of {r['total']} ranked")
            out += [f"    - `{t['key']}` (risk {t['risk']})" for t in r["top"]]
    if f["drafts"]:
        out += ["", "## Drafts waiting", ""] + [f"- {loc or '?'}: {n}" for loc, n in sorted(f["drafts"].items())]
    if f["spend"]:
        s = f["spend"]
        out += ["", "## Cloud spend this month", "",
                f"${s['month_usd']:.2f} of ${s['cap_usd']:.2f} (${s['remaining_usd']:.2f} left)"]
    if f["runs"]:
        out += ["", "## Recent runs", ""]
        for r in f["runs"]:
            counts = ", ".join(f"{k} {v}" for k, v in r["counts"].items())
            out.append(f"- {r['started_at']} `{r['command']}` {','.join(r['locales'])}"
                       + (f" ({counts})" if counts else "") + (f" · {r['model']}" if r["model"] else ""))
    out += ["", "---", "Generated by `llm-localizator report` (read-only). "
            "What to run next: `llm-localizator guide`.", ""]
    return "\n".join(out)


_CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e6;--go:#1a7f37;--warn:#9a6700;--stop:#cf222e;--card:#f6f6f7}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececee;--muted:#9a9aa0;--line:#2c2c30;--go:#3fb950;--warn:#d29922;--stop:#f85149;--card:#1c1c1f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px 48px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
.meta{color:var(--muted);font-size:13px}.verdict{border:1px solid var(--line);border-left:6px solid var(--c);background:var(--card);border-radius:8px;padding:12px 16px;margin-top:16px}
.verdict strong{color:var(--c);font-size:18px}ul{padding-left:20px;margin:6px 0}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;min-width:80px}.bar i{display:block;height:100%;background:var(--go)}
code{font:13px ui-monospace,Consolas,monospace}.wrap{overflow-x:auto}footer{margin-top:32px;color:var(--muted);font-size:13px}
"""


def render_html(f: dict[str, Any]) -> str:
    e = html.escape
    color = {"go": "var(--go)", "go-with-notes": "var(--warn)", "no-go": "var(--stop)"}[f["verdict"]]
    items = [f"<li><b>Blocking:</b> {e(r)}</li>" for r in f["reasons"]] + [f"<li>{e(n)}</li>" for n in f["notes"]]
    rows = "".join(
        f"<tr><td>{e(r['locale'])}{' <span class=meta>(frozen)</span>' if r['frozen'] else ''}</td>"
        f"<td><div class=bar><i style='width:{min(100.0, r['pct'])}%'></i></div></td>"
        f"<td>{r['has_text']}/{r['total']} ({r['pct']}%)</td><td>{r['missing']}</td>"
        f"<td>{r['stale']}</td><td>{r['no_record']}</td></tr>"
        for r in f["coverage"])
    v, c = f["validate"], f["hardcoded"]["counts"]
    checks = [f"Validation (active locales): {v['errors']} error(s), {v['warnings']} warning(s)"]
    if f["keys"] is not None:
        checks.append(f"Keys used in code: {f['keys']['summary']}")
    checks.append(f"Hardcoded text (last scan{', stale' if f['hardcoded']['stale'] else ''}): "
                  f"{c.get('high', 0)} high, {c.get('medium', 0)} medium, {c.get('low', 0)} low")
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>Localization report</title><style>{_CSS}</style></head><body><main>",
        f"<h1>Localization report: {e(f['project'])}</h1>",
        f"<div class=meta>{e(f['generated_at'])} · source <code>{e(f['source_locale'])}</code> · active: "
        f"{e(', '.join(f['active']) or '(none)')}"
        + (f" · frozen: {e(', '.join(f['frozen']))}" if f["frozen"] else "") + "</div>",
        f"<div class=verdict style='--c:{color}'><strong>{e(_VERDICT_LABEL[f['verdict']])}</strong>"
        f"<ul>{''.join(items) or '<li>Nothing to fix or review.</li>'}</ul></div>",
        "<h2>Coverage</h2><div class=wrap><table><tr><th>Locale</th><th></th><th>Has text</th>"
        f"<th>Missing</th><th>Out of date</th><th>Not recorded</th></tr>{rows}</table></div>"
        + _COVERAGE_NOTE_HTML,
        "<h2>Checks</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in checks)
        + "".join(f"<li class=meta><code>{e(x)}</code></li>" for x in v["examples"]) + "</ul>",
    ]
    if f["review"]:
        parts.append("<h2>Review first</h2><ul>" + "".join(
            f"<li><b>{e(loc)}</b>: {r['high']} high-risk of {r['total']} ranked<ul>"
            + "".join(f"<li><code>{e(str(t['key']))}</code> (risk {e(str(t['risk']))})</li>" for t in r["top"])
            + "</ul></li>" for loc, r in f["review"].items()) + "</ul>")
    if f["drafts"]:
        parts.append("<h2>Drafts waiting</h2><ul>" + "".join(
            f"<li>{e(loc or '?')}: {n}</li>" for loc, n in sorted(f["drafts"].items())) + "</ul>")
    if f["spend"]:
        s = f["spend"]
        parts.append(f"<h2>Cloud spend this month</h2><p>${s['month_usd']:.2f} of ${s['cap_usd']:.2f} "
                     f"(${s['remaining_usd']:.2f} left)</p>")
    if f["runs"]:
        parts.append("<h2>Recent runs</h2><ul>" + "".join(
            f"<li>{e(str(r['started_at']))} <code>{e(str(r['command']))}</code> {e(','.join(r['locales']))}</li>"
            for r in f["runs"]) + "</ul>")
    parts.append("<footer>Generated by <code>llm-localizator report</code> (read-only). "
                 "What to run next: <code>llm-localizator guide</code>.</footer></main></body></html>")
    return "\n".join(parts) + "\n"


def op_report(
    cfg: ProjectConfig, *, fmt: str = "md", locales: list[str] | None = None,
    out: str | None = None, review_limit: int = 5,
) -> OpResult:
    command = "report"
    if fmt not in REPORT_FORMATS:
        return OpResult(ok=False, exit_code=64, command=command,
                        summary=f"unknown format {fmt!r} ({'|'.join(REPORT_FORMATS)})")
    facts = gather(cfg, locales=locales, review_limit=review_limit)
    if fmt == "json":
        text = json.dumps(facts, ensure_ascii=False, indent=2, default=str) + "\n"
    elif fmt == "html":
        text = render_html(facts)
    else:
        text = render_markdown(facts)
    summary = f"{_VERDICT_LABEL[facts['verdict']]}: " + (
        "; ".join(facts["reasons"] or facts["notes"][:2]) or "nothing to fix or review")
    data = {"verdict": facts["verdict"], "reasons": facts["reasons"], "notes": facts["notes"],
            "facts": facts}
    if out:
        from pathlib import Path

        from ..catalog.io import atomic_write_text

        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, text)
        data["path"] = str(path)
        lines = [f"wrote {path}"]
    else:
        data["text"] = text
        lines = [text]
    # The verdict is information, not a command failure: exit 1 only for no-go so CI can gate on it.
    exit_code = 1 if facts["verdict"] == "no-go" else 0
    return OpResult(ok=True, exit_code=exit_code, command=command, summary=summary,
                    lines=lines, data=data)
