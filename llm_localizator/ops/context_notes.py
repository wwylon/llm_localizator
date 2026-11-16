"""``context-propose`` and ``context-note``: per-key translator notes (A3, ADR-131).

Short placeholder frames ("{rank} of {suit}", "{n} nodes") are where models
translate word by word. A per-key note in ``[prompt] context_dir`` (ContextAssembler,
ADR-25) fixes that, but nothing wrote them.

* ``context-propose`` lists frames (fewer than 3 words outside placeholders) with
  a suggested note. It is read-only unless ``write``. A person reads the proposal
  first.
* ``context-note`` writes one note. It creates the context file, and sets
  ``[prompt] context_dir`` if missing, under the catalogue's directory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..catalog import catalog_for
from ..catalog.io import atomic_write_text
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["op_context_propose", "op_context_note", "frame_note"]

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_FUNCTION_WORDS = {"of", "in", "on", "to", "by", "for", "at", "from", "with", "per", "and", "or"}


def frame_note(source: str) -> str | None:
    """A note for a short frame, or None when the source is not one."""
    if "{" not in source or re.search(r"\{\s*\w+\s*,\s*(?:plural|select)", source):
        return None
    words = re.findall(r"[^\W\d_]+", _PLACEHOLDER.sub(" ", source))
    if not words or len(words) >= 3:
        return None
    fn = [w for w in words if w.casefold() in _FUNCTION_WORDS]
    if fn:
        return (f"Placeholder frame: translate the whole phrase as it reads with real values; "
                f"do not translate '{fn[0]}' word for word, the target language may need a "
                f"different word order or no preposition at all.")
    return None  # no function word: the frame translates as a phrase on its own


def _context_dir(cfg: ProjectConfig) -> Path:
    if cfg.context_dir:
        return Path(cfg.context_dir)
    path = Path(str(cfg.catalog_path).replace("{locale}", "x")).parent
    return Path(cfg.root) / path / "context"


def _file_for(cfg: ProjectConfig, namespace: str) -> Path:
    return _context_dir(cfg) / (f"{namespace}.json" if namespace else "_root.json")


def op_context_propose(cfg: ProjectConfig, *, write: bool = False) -> OpResult:
    catalog = catalog_for(cfg)
    rows = []
    for ns in cfg.namespaces_for(catalog):
        existing = _read(_file_for(cfg, ns))
        for key, src in catalog.load(cfg.source_locale, ns).items():
            if not isinstance(src, str) or key in existing:
                continue
            note = frame_note(src)
            if note:
                rows.append({"namespace": ns, "key": key, "source": src, "note": note})
    lines = [f"{(r['namespace'] + '.') if r['namespace'] else ''}{r['key']}: {r['source']!r}\n    {r['note']}"
             for r in rows]
    if write:
        for r in rows:
            op_context_note(cfg, key=f"{r['namespace']}.{r['key']}" if r["namespace"] else r["key"],
                            note=r["note"])
    return OpResult(ok=True, exit_code=0, command="context-propose",
                    summary=f"{len(rows)} frame(s) without a note" + (" — written" if write else ""),
                    lines=lines, data={"rows": rows, "written": write})


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def op_context_note(cfg: ProjectConfig, *, key: str, note: str | None = None,
                    approved: dict[str, str] | None = None) -> OpResult:
    """Write a note and/or a person-approved translation per locale (ADR-137)."""
    catalog = catalog_for(cfg)
    ns, bare = "", key
    for candidate in cfg.namespaces_for(catalog):
        if candidate and key.startswith(candidate + ".") and key[len(candidate) + 1:] in catalog.load(
                cfg.source_locale, candidate):
            ns, bare = candidate, key[len(candidate) + 1:]
            break
    if bare not in catalog.load(cfg.source_locale, ns):
        return OpResult(ok=False, exit_code=2, command="context-note",
                        summary=f"key {key!r} is not in the source catalogue")
    path = _file_for(cfg, ns)
    data = _read(path)
    entry = data.get(bare)
    if isinstance(entry, str):
        entry = {"note": entry}
    entry = dict(entry or {})
    if note:
        entry["note"] = note
    if approved:
        entry["approved"] = {**(entry.get("approved") or {}), **approved}
    data[bare] = entry["note"] if set(entry) == {"note"} else entry
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=2) + "\n")
    lines = [f"{path}: {bare} = {data[bare]!r}"]
    if not cfg.context_dir and getattr(cfg, "config_path", None):
        import tomlkit

        doc = tomlkit.parse(Path(cfg.config_path).read_text(encoding="utf-8"))
        doc.setdefault("prompt", tomlkit.table())["context_dir"] = path.parent.relative_to(
            Path(cfg.root)).as_posix()
        atomic_write_text(Path(cfg.config_path), tomlkit.dumps(doc))
        lines.append(f"[prompt] context_dir = {path.parent.relative_to(Path(cfg.root)).as_posix()!r}")
    return OpResult(ok=True, exit_code=0, command="context-note", summary=f"note written for {key}",
                    lines=lines)
