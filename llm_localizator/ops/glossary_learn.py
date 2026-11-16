"""``glossary-learn``: glossary proposals from human and agent fixes (A6, ADR-135).

History keeps ``prev`` and ``next`` for every write. A ``set`` (or an imported review
decision, or a web edit with ``edited_by``) that replaces one word with another is a
correction. When the same correction (same word stems) is made in two or more different
keys, and the English sources of those keys share a word, that word probably needs a
glossary entry: the corrected word is the approved rendering and the replaced word is a
forbidden variant (``seed``: nasienie → ziarno).

Read-only unless ``write``; ``write`` saves a proposal file in the data home for a person
to confirm. The glossary itself is never edited here (agents propose, people confirm).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..catalog import catalog_for
from ..catalog.history import HistoryStore
from ..catalog.io import atomic_write_text
from ..projects import ProjectConfig, load_glossary
from .types import OpResult

__all__ = ["op_glossary_learn", "learn_corrections"]

_MANUAL_TRIGGERS = frozenset({"set", "import", "review", "import-review", "web", "edit"})
_WORD = re.compile(r"[^\W\d_]{3,}")
_EN_STOP = frozenset("""the and for with from this that your you are was were have has not all any
can will into out over per each one two its our their them then than when what which who how""".split())
_STEM = 4
MIN_KEYS = 2


def _words(text: str | None) -> list[str]:
    return [w.casefold() for w in _WORD.findall(text or "")]


def _stem(word: str) -> str:
    return word[:_STEM]


def _swap(prev: str | None, new: str | None) -> tuple[str, str] | None:
    """The one word ``prev`` lost and the one word ``new`` gained, by stem; else None."""
    before, after = _words(prev), _words(new)
    lost = {_stem(w): w for w in before if _stem(w) not in {_stem(a) for a in after}}
    gained = {_stem(w): w for w in after if _stem(w) not in {_stem(b) for b in before}}
    if len(lost) != 1 or len(gained) != 1:
        return None
    return next(iter(lost.values())), next(iter(gained.values()))


def _manual(event) -> bool:
    return event.trigger in _MANUAL_TRIGGERS or bool(event.edited_by) or event.status == "human"


def learn_corrections(events: list[tuple[str, str | None, str, str]],
                      known_terms: frozenset[str] = frozenset()) -> list[dict]:
    """Proposals from ``(key, prev, next, source)`` corrections. Pure."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for key, prev, new, source in events:
        swap = _swap(prev, new)
        if swap is None:
            continue
        old, fixed = swap
        groups[(_stem(old), _stem(fixed))].append(
            {"key": key, "old": old, "fixed": fixed, "source": source})
    out = []
    for rows in groups.values():
        keys = sorted({r["key"] for r in rows})
        if len(keys) < MIN_KEYS:
            continue
        common = None
        for r in rows:
            words = {w for w in _words(r["source"]) if w not in _EN_STOP}
            common = words if common is None else common & words
        if not common:
            continue
        # A word the glossary already knows wins; else the shortest shared word (the noun
        # in "Bots thinking…" is "bots", not "thinking"). The rest are listed for the person.
        ranked = sorted(common, key=lambda w: (w not in known_terms, len(w), w))
        term = ranked[0]
        fixed_forms = sorted({r["fixed"] for r in rows})
        old_forms = sorted({r["old"] for r in rows})
        out.append({"term": term, "approved": min(fixed_forms, key=len), "forms": fixed_forms,
                    "forbidden": old_forms, "keys": keys,
                    "other_source_words": ranked[1:6],
                    "examples": [{"key": r["key"], "source": r["source"]} for r in rows[:3]]})
    out.sort(key=lambda p: (-len(p["keys"]), p["term"]))
    return out


def _known(glossary: dict, proposal: dict, locale: str) -> bool:
    entry = (glossary.get("terms") or {}).get(proposal["term"])
    if not isinstance(entry, dict):
        return False
    forbidden = {str(f).casefold() for f in entry.get(f"{locale}_forbidden") or []}
    return all(f in forbidden for f in proposal["forbidden"])


def op_glossary_learn(cfg: ProjectConfig, *, locale: str, write: bool = False) -> OpResult:
    command = "glossary-learn"
    catalog = catalog_for(cfg)
    sources: dict[str, str] = {}
    for ns in cfg.namespaces_for(catalog):
        for key, text in catalog.load(cfg.source_locale, ns).items():
            if isinstance(text, str):
                sources[f"{ns}.{key}" if ns else key] = text
    history = HistoryStore(cfg.history_root())
    events = []
    for sk, event, _raw in history.iter_events(locale):
        if not _manual(event) or not event.prev or event.prev == event.next:
            continue
        events.append((sk, event.prev, event.next, sources.get(sk, event.next_src or "")))
    glossary = load_glossary(cfg.glossary_path)
    known = frozenset(str(t).casefold() for t in (glossary.get("terms") or {}))
    proposals = [p for p in learn_corrections(events, known) if not _known(glossary, p, locale)]
    lines = [f"{p['term']}: {locale} {p['approved']!r}; forbid {', '.join(p['forbidden'])} "
             f"({len(p['keys'])} keys: {', '.join(p['keys'][:4])})" for p in proposals]
    data = {"locale": locale, "corrections": len(events), "proposals": proposals}
    if write and proposals:
        out = Path(cfg.data_root()) / "glossary" / f"proposals-{locale}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        atomic_write_text(out, json.dumps({"generated_at": stamp, **data}, ensure_ascii=False,
                                          indent=2) + "\n")
        lines.append(f"proposals written to {out}: confirm each in the glossary by hand")
        data["path"] = str(out)
    return OpResult(ok=True, exit_code=0, command=command,
                    summary=f"{len(proposals)} glossary proposal(s) from {len(events)} manual "
                            f"{locale} correction(s)", lines=lines, data=data)
