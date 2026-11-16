"""Patch mode: generate a structured changeset without writing to the project.

The patch output describes:
- Hardcoded strings that should be routed through the translation function,
  with a suggested key name and the catalogue entry to add.
- Catalogue gaps (keys present in source but absent in one or more target
  locales) that should be translated.

Nothing in this module writes to the consumer project.  The changeset can be
saved to an output directory as JSON and applied later by ``ops/apply.py`` or
by a developer / AI agent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..catalog.scan_decisions import ACCEPTED, APPLIED, IGNORED, KIND_HIT, ScanDecisions, hit_id
from ..projects import ProjectConfig
from ..scan import scanner_from_config
from .agent_hardcoded import _scan_files, catalogue_gap_audit
from .types import OpResult, PatchRequest
from ..projects.paths import project_path

__all__ = ["op_patch", "select_patches", "suggest_key"]


# ---------------------------------------------------------------------------
# Key suggestion
# ---------------------------------------------------------------------------

_NON_ALPHA = re.compile(r"[^a-zA-Z0-9 ]+")
_SPACES = re.compile(r"\s+")
_MAX_WORDS = 5


def suggest_key(text: str) -> str:
    """Derive a camelCase translation key from a plain-text string.

    Examples::

        "Sign in"          -> "signIn"
        "Create account"   -> "createAccount"
        "Hello, World!"    -> "helloWorld"
    """
    cleaned = _NON_ALPHA.sub(" ", text).strip()
    words = _SPACES.split(cleaned)[:_MAX_WORDS]
    if not words or not words[0]:
        return "untitled"
    first = words[0].lower()
    rest = [w.capitalize() for w in words[1:] if w]
    return first + "".join(rest)


def _namespace_from_path(rel: str) -> str:
    """Guess a namespace from a relative source-file path.

    ``src/auth/login.tsx`` -> ``auth``
    ``components/nav/Header.tsx`` -> ``nav``
    ``pages/index.tsx`` -> ``pages``
    """
    parts = Path(rel).parts
    # Strip common top-level dirs that are not namespaces
    skip = {"src", "app", "pages", "components", "lib", "utils", "features"}
    meaningful = [p for p in parts[:-1] if p.lower() not in skip]
    return meaningful[0] if meaningful else (parts[0] if len(parts) > 1 else "app")


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------

def _hardcoded_patches(hits: list[dict], routing_note: str) -> list[dict]:
    """Convert scan hits into structured patch entries."""
    patches = []
    for hit in hits:
        ns = hit.get("namespace_hint") or _namespace_from_path(hit["file"])
        key = hit.get("key_hint") or suggest_key(hit["text"])
        patches.append({
            "file": hit["file"],
            "line": hit["line"],
            "text": hit["text"],
            "suggested_namespace": ns,
            "suggested_key": key,
            "suggested_catalogue_key": f"{ns}.{key}",
            "routing_note": routing_note,
            "source": hit.get("source", "regex"),
            **{k: hit[k] for k in ("note", "max_length", "dnt") if hit.get(k)},
        })
    return patches


def select_patches(cfg: ProjectConfig, hits: list[dict], routing_note: str) -> list[dict]:
    """Patch entries for the hits the user decided on (ADR-55).

    With no decisions recorded every hit is listed, as before. Once the user has
    accepted or ignored anything, only accepted (and already applied) hits remain,
    each with the key the decision fixed.
    """
    patches = _hardcoded_patches(hits, routing_note)
    decided = ScanDecisions.for_project(cfg).items()
    has_hit_decisions = any(e.get("kind", KIND_HIT) == KIND_HIT for e in decided.values())
    out: list[dict] = []
    for patch in patches:
        patch["id"] = hit_id(patch["file"], patch["text"])
        if not has_hit_decisions:
            out.append(patch)
            continue
        entry = decided.get(patch["id"])
        if not entry or entry.get("status") not in (ACCEPTED, APPLIED):
            continue
        key = entry.get("key")
        if key:
            ns = entry.get("namespace") or ""
            patch["suggested_key"] = key
            patch["suggested_namespace"] = ns
            patch["suggested_catalogue_key"] = f"{ns}.{key}" if ns else key
        patch["decision"] = entry["status"]
        out.append(patch)
    return out


def _render_markdown(
    cfg: ProjectConfig,
    routing_note: str,
    hardcoded_patches: list[dict],
    gap_records: list[dict],
) -> str:
    lines = [
        f"# Patch report — {cfg.name}",
        "",
        "This is a **read-only** changeset.  Apply it with `llm-localizator apply`",
        "or act on it manually / via an AI agent.",
        "",
    ]

    if hardcoded_patches:
        lines += [
            f"## Hardcoded strings ({len(hardcoded_patches)})",
            "",
            f"Routing: {routing_note or 'use the project translation function.'}",
            "",
        ]
        by_file: dict[str, list[dict]] = {}
        for p in hardcoded_patches:
            by_file.setdefault(p["file"], []).append(p)
        for path, patches in by_file.items():
            lines.append(f"### {path}")
            lines.append("")
            for p in patches:
                lines.append(
                    f"- **line {p['line']}** `{p['text']!r}` → "
                    f"`{p['suggested_catalogue_key']}` "
                    f"(add to `{p['suggested_namespace']}.json`)"
                )
            lines.append("")

    if gap_records:
        by_ns_locale: dict[tuple, list[dict]] = {}
        for g in gap_records:
            by_ns_locale.setdefault((g["namespace"], g["locale"]), []).append(g)
        lines += [f"## Catalogue gaps ({len(gap_records)})", ""]
        for (ns, locale), recs in by_ns_locale.items():
            lines.append(f"### {ns or '(default)'} / {locale}  ({len(recs)} keys)")
            lines.append("")
            for r in recs[:20]:
                lines.append(f"  - `{r['key']}`: {r['source_text'][:80]!r}")
            if len(recs) > 20:
                lines.append(f"  … and {len(recs) - 20} more")
            lines.append("")

    if not hardcoded_patches and not gap_records:
        lines.append("No changes needed.")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# op_patch
# ---------------------------------------------------------------------------

_HASH_EXT = {".py", ".rb", ".sh", ".yaml", ".yml", ".toml"}
_HTML_EXT = {".html", ".htm", ".vue", ".svelte", ".xml"}


def directive_suggestions(cfg: ProjectConfig, hits: list[dict]) -> list[dict]:
    """Inline `l10n-ignore-next-line` comments for hits the user ignored (decisions_in = "code")."""
    decided = ScanDecisions.for_project(cfg).items()
    out: list[dict] = []
    for hit in hits:
        entry = decided.get(hit_id(hit["file"], hit["text"]))
        if not entry or entry.get("status") != IGNORED:
            continue
        ext = Path(hit["file"]).suffix.lower()
        body = "l10n-ignore-next-line"
        comment = (f"# {body}" if ext in _HASH_EXT
                   else f"<!-- {body} -->" if ext in _HTML_EXT else f"// {body}")
        out.append({"file": hit["file"], "line": hit["line"], "insert_above": comment})
    return out


def op_patch(cfg: ProjectConfig, req: PatchRequest) -> OpResult:
    """Scan for hardcoded strings and catalogue gaps; emit a changeset JSON.

    Writes nothing to the consumer project.  If ``req.out_dir`` is set, saves
    the changeset as ``patch.json`` and a human-readable ``patch.md`` there.
    """
    if cfg.source_edits == "never":
        return OpResult(
            ok=False, exit_code=1, command="patch",
            summary="source edits are disabled by [source_policy]",
            lines=['[source_policy] source_edits = "never": reports only, no patch.',
                   'Set it to "patch" or "agent-branch" to allow patch output.'],
        )
    adapter = req.adapter or cfg.scan_adapter
    if not adapter:
        return OpResult(
            ok=False, exit_code=64, command="patch",
            summary="no scan adapter configured",
            lines=["Set [scan] adapter in .llm-localize.toml or pass --adapter."],
        )
    if not cfg.scan_src_dirs:
        return OpResult(
            ok=False, exit_code=64, command="patch",
            summary="no [scan] src_dirs configured",
            lines=[],
        )

    try:
        scanner = scanner_from_config(cfg, adapter)
    except ValueError as exc:
        return OpResult(ok=False, exit_code=64, command="patch", summary=str(exc))

    result, _ = _scan_files(scanner, req.limit)
    hits = [
        {"text": h.text, "file": h.file, "line": h.line,
         "reason": h.reason, "source": "regex",
         "key_hint": h.key_hint, "namespace_hint": h.namespace_hint,
         "note": h.note, "max_length": h.max_length, "dnt": h.dnt}
        for h in result.hardcoded
    ]

    hc_patches = select_patches(cfg, hits, scanner.routing_note)
    gap_records, _ = catalogue_gap_audit(cfg)

    changeset = {
        "project": cfg.name,
        "hardcoded_strings": hc_patches,
        "catalogue_gaps": gap_records,
        "routing_note": scanner.routing_note,
        "stats": {
            "files_scanned": result.files_scanned,
            "hardcoded": len(hc_patches),
            "catalogue_gaps": len(gap_records),
        },
    }

    if cfg.decisions_in == "code":
        changeset["directive_suggestions"] = directive_suggestions(cfg, hits)

    if cfg.source_edits == "agent-branch":
        changeset["agent_task"] = {
            "branch": f"l10n/extract-{cfg.name}",
            "files": sorted({p["file"] for p in hc_patches if "file" in p}),
            "verify": "llm-localizator scan --strict --lint-directives && llm-localizator check",
            "target_branch_for_translations": cfg.target_branch,
            "note": "The engine edits no source; an agent applies the patch on this branch.",
        }
    md = _render_markdown(cfg, scanner.routing_note, hc_patches, gap_records)

    out_dir = project_path(cfg.root, req.out_dir)
    written: list[str] = []
    if out_dir:
        from ..catalog.io import atomic_write_text

        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "patch.json"
        md_path = out_dir / "patch.md"
        atomic_write_text(json_path, json.dumps(changeset, ensure_ascii=False, indent=2) + "\n")
        atomic_write_text(md_path, md)
        written = [str(json_path), str(md_path)]

    summary = (
        f"{len(hc_patches)} hardcoded string(s), "
        f"{len(gap_records)} catalogue gap(s)"
    )
    lines = md.splitlines()
    if written:
        lines = [f"Wrote {p}" for p in written] + [""] + lines

    return OpResult(
        ok=True, exit_code=0, command="patch", summary=summary,
        lines=lines,
        data=changeset,
    )
