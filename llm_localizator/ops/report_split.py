"""Split a hits list into agent-sized report parts (ADR-105).

Packing is deterministic: hits are ordered by (file, line), grouped by path
hierarchy (directory, then file, then line range) and adjacent small groups are
merged while they fit the token budget and the per-part hit cap.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.io import atomic_write_json

__all__ = ["Part", "est_tokens", "hit_line", "pack_hits", "render_part", "write_parts"]


def est_tokens(text: str) -> int:
    return len(text) // 4 + 1


def hit_line(row: dict) -> str:
    path, existing = row["file"], row.get("existing_key")
    if existing:
        return (
            f"- {path}:{row['line']}  {row['text']!r}  "
            f"→ already at `{existing}` (reuse this key, do not create a new one)"
        )
    line = f"- {path}:{row['line']}  {row['text']!r}  ({row['source']}) {row['reason']}"
    hints = [f"{n}={row[k]}" for k, n in (("key_hint", "key"), ("note", "note"),
                                         ("namespace_hint", "namespace")) if row.get(k)]
    if row.get("dnt"):
        hints.append("do-not-translate")
    return line + (f"  [{', '.join(hints)}]" if hints else "")


@dataclass
class Part:
    scope: str
    hits: list[dict] = field(default_factory=list)
    tokens: int = 0

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.scope}\0{self.hits[0]['file']}".encode()).hexdigest()[:8]


def _cost(hit: dict) -> int:
    return est_tokens(hit_line(hit)) + 1


def _make(scope: str, hits: list[dict]) -> Part:
    return Part(scope, hits, sum(_cost(h) for h in hits))


def _chunk(hits: list[dict], scope: str, budget: int, cap: int) -> list[Part]:
    """Split one file's hits by line range; never splits inside a hit."""
    parts: list[Part] = []
    cur: list[dict] = []
    tok = 0
    for h in hits:
        c = _cost(h)
        if cur and (tok + c > budget or len(cur) >= cap):
            parts.append(_make(scope, cur))
            cur, tok = [], 0
        cur.append(h)
        tok += c
    if cur:
        parts.append(_make(scope, cur))
    return parts


def _is_file_level(rows: list[dict], depth: int) -> bool:
    return all(r["file"].count("/") == depth for r in rows)


def _pack(hits: list[dict], prefix: str, budget: int, cap: int) -> list[Part]:
    total = sum(_cost(h) for h in hits)
    if total <= budget and len(hits) <= cap:
        return [_make(prefix or ".", hits)]
    depth = len(prefix.split("/")) if prefix else 0
    groups: dict[str, list[dict]] = {}
    for h in hits:
        bits = h["file"].split("/")
        groups.setdefault(bits[depth], []).append(h)
    if len(groups) == 1:
        (name, rows), = groups.items()
        if _is_file_level(rows, depth):
            return _chunk(rows, rows[0]["file"], budget, cap)
        return _pack(rows, posixpath.join(prefix, name) if prefix else name, budget, cap)
    out: list[Part] = []
    for name in sorted(groups):
        rows = groups[name]
        if _is_file_level(rows, depth):
            out.extend(_chunk(rows, rows[0]["file"], budget, cap))
        else:
            out.extend(_pack(rows, posixpath.join(prefix, name) if prefix else name, budget, cap))
    merged: list[Part] = []
    for p in out:
        last = merged[-1] if merged else None
        if last and last.tokens + p.tokens <= budget and len(last.hits) + len(p.hits) <= cap:
            merged[-1] = Part(prefix or ".", last.hits + p.hits, last.tokens + p.tokens)
        else:
            merged.append(p)
    return merged


def pack_hits(
    hits: list[dict], budget_tokens: int = 15000, max_hits: int = 150, header_tokens: int = 600,
) -> list[Part]:
    """Parts ordered by urgency (most high-confidence hits first)."""
    ordered = sorted(hits, key=lambda h: (h["file"], h["line"], h["text"]))
    if not ordered:
        return []
    parts = _pack(ordered, "", max(budget_tokens - header_tokens, 200), max(max_hits, 1))
    parts.sort(key=lambda p: (
        -sum(1 for h in p.hits if h.get("confidence") == "high"), p.scope, p.id,
    ))
    return parts


def render_part(project: str, part: Part, number: int, total: int, note: str, skips: str) -> str:
    lines = [
        f"# Hardcoded strings — {project} — part {number}/{total} (`{part.id}`, {part.scope})",
        "",
        "The engine did not edit these files and will not invent keys.",
        "Add English source strings only, routing each literal through the "
        "project translation function.",
        "",
        f"How to route: {note or 'use the project translation function.'}",
        f"Skipped while scanning: {skips}.",
        "Record a decision per hit: `llm-localizator scan-decide accept|ignore --ids <id,...>`",
        "",
    ]
    by_file: dict[str, list[dict]] = {}
    for h in part.hits:
        by_file.setdefault(h["file"], []).append(h)
    for path, rows in by_file.items():
        lines += [f"## {path}", ""]
        for r in rows:
            lines.append(hit_line(r) + (f"  [id {r['id']}]" if r.get("id") else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_parts(
    out_dir: Path,
    project: str,
    parts: list[Part],
    note: str,
    skips: str,
    *,
    write_json: bool = True,
) -> dict:
    """Write one md (and json) file per part plus index.md / index.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    entries = []
    for n, part in enumerate(parts, 1):
        name = f"part-{part.id}.md"
        text = render_part(project, part, n, len(parts), note, skips)
        (out_dir / name).write_text(text, encoding="utf-8")
        keep.add(name)
        json_name = f"part-{part.id}.json"
        if write_json:
            payload = {
                "project": project,
                "part": n,
                "totalParts": len(parts),
                "id": part.id,
                "scope": part.scope,
                "routingNote": note,
                "hits": part.hits,
            }
            (out_dir / json_name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            keep.add(json_name)
        conf: dict[str, int] = {}
        for h in part.hits:
            c = h.get("confidence", "medium")
            conf[c] = conf.get(c, 0) + 1
        entries.append({
            "id": part.id, "file": name, "jsonFile": json_name if write_json else None,
            "scope": part.scope, "hits": len(part.hits),
            "byConfidence": conf, "estTokens": est_tokens(text), "order": n,
        })
    for old in list(out_dir.glob("part-*.md")) + list(out_dir.glob("part-*.json")):
        if old.name not in keep:
            old.unlink()
    index = {"project": project, "parts": entries, "totalHits": sum(e["hits"] for e in entries)}
    atomic_write_json(out_dir / "index.json", index, ensure_ascii=True, newline=False)
    md = [
        f"# Report index — {project}", "",
        "| # | part | scope | hits | high/med/low | ~tokens |", "|---|---|---|---|---|---|",
    ]
    for e in entries:
        c = e["byConfidence"]
        md.append(
            f"| {e['order']} | [{e['id']}]({e['file']}) | {e['scope']} | {e['hits']} | "
            f"{c.get('high', 0)}/{c.get('medium', 0)}/{c.get('low', 0)} | {e['estTokens']} |"
        )
    (out_dir / "index.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return index
