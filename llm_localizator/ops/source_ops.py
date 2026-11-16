"""Read-only term proposals, source-change impact, and a throwaway pseudo locale."""

from __future__ import annotations

import math
import re
from collections import defaultdict

from ..catalog import StateStore, catalog_for
from ..core.hash import src_hash
from ..core.source_quality import pseudo_text
from ..core.standards import get_standard
from ..projects import ProjectConfig
from ..projects.context import ContextNotes
from .types import OpResult, PseudoRequest

__all__ = ["op_glossary_propose", "op_impact", "op_pseudo"]

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOP = frozenset(
    "a an the of to and or in on for with from by at as is are was were be "
    "been being this that these those it its not no".split()
)
_LOCALE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def _tm_suggestions(
    cfg: ProjectConfig, locale: str, min_occurrences: int, out: str | None,
) -> OpResult:
    """Terms the TM keeps translating the same way but the glossary does not cover."""
    import csv
    import io
    from pathlib import Path

    from ..catalog.glossary_exchange import COLUMNS
    from ..catalog.tm import TranslationMemory
    from ..pipeline.glossary_suggest import suggest_terms
    from ..projects.context import load_glossary

    if locale not in cfg.targets:
        return OpResult(
            ok=False, exit_code=1, command="glossary-propose",
            summary=f"{locale!r} is not a target locale ({', '.join(cfg.targets) or 'none'})",
        )
    tm = cfg.open_tm()
    pairs = [
        (entry.source, entry.text)
        for entry, superseded in tm.rows(locale)
        if not superseded and entry.text != entry.source
    ]
    glossary = load_glossary(cfg.glossary_path)
    known = set((glossary.get("terms") or {})) | set(glossary.get("doNotTranslate") or [])
    found = suggest_terms(pairs, known=known, min_occurrences=max(2, min_occurrences))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for item in found:
        note = f"suggested from TM: {item.count} entries"
        writer.writerow([item.term, locale, item.translation, "", note])
    text = buffer.getvalue()
    lines = text.splitlines()
    if out:
        Path(out).write_text(text, encoding="utf-8", newline="")
        lines = [f"wrote {len(found)} suggestion(s) to {out}"]
    return OpResult(
        ok=True, exit_code=0, command="glossary-propose",
        summary=f"{len(found)} suggested term(s) for {locale} from {len(pairs)} TM entries",
        lines=lines, data={"suggestions": len(found), "locale": locale, "out": out},
    )


def op_glossary_propose(
    cfg: ProjectConfig,
    *,
    locale: str | None = None,
    min_occurrences: int = 5,
    out: str | None = None,
) -> OpResult:
    """Print candidates. Does not write the glossary.

    With ``locale``, mine that locale's translation memory instead and print (or write to
    ``out``) a CSV that ``glossary-import`` accepts.
    """
    if locale:
        return _tm_suggestions(cfg, locale, min_occurrences, out)
    catalog = catalog_for(cfg)
    notes = ContextNotes(cfg.context_dir)
    namespaces = cfg.namespaces_for(catalog)
    freq: dict[str, int] = defaultdict(int)
    keys: dict[str, set[tuple[str, str]]] = defaultdict(set)
    sources: list[tuple[str, str, str]] = []
    for namespace in namespaces:
        for key, text in catalog.load(cfg.source_locale, namespace).items():
            if cfg.is_skipped(namespace, key) or not isinstance(text, str) or not text.strip():
                continue
            sources.append((namespace, key, text))
            words = [word.casefold() for word in _WORD.findall(text)]
            for size in (2, 3):
                for index in range(len(words) - size + 1):
                    gram = words[index:index + size]
                    if gram[0] in _STOP or gram[-1] in _STOP:
                        continue
                    phrase = " ".join(gram)
                    freq[phrase] += 1
                    keys[phrase].add((namespace, key))
    ranked = []
    for phrase, count in freq.items():
        if count < 3:
            continue
        distinct = len(keys[phrase])
        score = count * math.log(distinct) if distinct > 1 else 0.0
        ranked.append((score, phrase, count, distinct))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    lines = [
        f"{phrase}\tfreq={count}\tkeys={distinct}\tscore={score:.4f}"
        for score, phrase, count, distinct in ranked
    ]
    lines.extend(_ambiguity(cfg, catalog, notes, sources))
    summary = f"{len(ranked)} candidate terms"
    return OpResult(
        ok=True, exit_code=0, command="glossary-propose", summary=summary,
        lines=lines, data={"candidates": len(ranked)},
    )


def op_impact(cfg: ProjectConfig) -> OpResult:
    """Locales whose stored source hash no longer matches. Does not write."""
    catalog = catalog_for(cfg)
    state = StateStore(cfg.state_root())
    by_text: dict[str, list[tuple[str, str]]] = defaultdict(list)
    rows: list[tuple[str, str, str]] = []
    for namespace in cfg.namespaces_for(catalog):
        for key, text in catalog.load(cfg.source_locale, namespace).items():
            if not isinstance(text, str):
                continue
            rows.append((namespace, key, text))
            by_text[text].append((namespace, key))
    lines: list[str] = []
    changes: list[dict] = []
    for namespace, key, text in rows:
        stale = []
        current = src_hash(text)
        for locale in cfg.targets:
            entry = state.entry(locale, namespace, key)
            recorded = entry.get("src_sha") if entry else None
            if isinstance(recorded, str) and recorded and recorded != current:
                stale.append(locale)
        if not stale:
            continue
        others = len(by_text[text]) - 1
        label = f"{namespace}.{key}" if namespace else key
        lines.append(f"{label} stale: {', '.join(stale)}")
        lines.append(f"  {others} keys share this source")
        changes.append({"namespace": namespace, "key": key, "stale": stale, "shared": others})
    summary = f"{len(changes)} changed source keys"
    return OpResult(
        ok=True, exit_code=0, command="impact", summary=summary,
        lines=lines, data={"changes": changes},
    )


def op_pseudo(cfg: ProjectConfig, req: PseudoRequest) -> OpResult:
    """Write one throwaway locale. Refuses a locale the project already uses."""
    locale = (req.locale or "en-XA").strip()
    if not _LOCALE.fullmatch(locale):
        return _fail("pseudo", f"invalid locale {locale!r}")
    configured = {cfg.source_locale, *cfg.targets, *cfg.frozen}
    if locale in configured:
        return _fail("pseudo", f"{locale} is a configured locale")
    factor = float(req.length_factor if req.length_factor else 1.4)
    style = (req.style or "").strip().lower()
    if not style:
        style = "xxxx" if locale.upper().endswith("-XX") else "accents"
    if style not in ("accents", "xxxx", "x", "marker"):
        return _fail("pseudo", f"unknown pseudo style {style!r} (accents|xxxx)")
    catalog = catalog_for(cfg)
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    before = _source_bytes(catalog, cfg)
    written = 0
    for namespace in cfg.namespaces_for(catalog):
        source = catalog.load(cfg.source_locale, namespace)
        messages = {
            key: pseudo_text(
                value, standard.tokens(value),
                length_factor=factor, style=style,
            )
            for key, value in source.items()
            if isinstance(value, str)
        }
        catalog.save(locale, namespace, messages)
        written += len(messages)
    after = _source_bytes(catalog, cfg)
    if after != before:
        return _fail("pseudo", "source catalogue bytes changed")
    summary = f"wrote {written} pseudo strings to {locale} (style={style})"
    return OpResult(
        ok=True, exit_code=0, command="pseudo", summary=summary,
        lines=[summary], data={"locale": locale, "keys": written, "style": style},
    )


def _ambiguity(cfg, catalog, notes: ContextNotes, sources: list[tuple[str, str, str]]) -> list[str]:
    lines: list[str] = []
    by_text: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for namespace, key, text in sources:
        label = f"{namespace}.{key}" if namespace else key
        words = _WORD.findall(text)
        if 0 < len(words) <= 2:
            lines.append(f"ambiguity: {label} short source")
        if not notes.has_entry(namespace, key):
            lines.append(f"ambiguity: {label} missing note")
        by_text[text].append((namespace, key))
    for text, group in by_text.items():
        if len(group) < 2:
            continue
        for locale in cfg.targets:
            rendered = []
            for namespace, key in group:
                value = catalog.load(locale, namespace).get(key)
                if isinstance(value, str) and value.strip():
                    rendered.append(value)
            if len(set(rendered)) > 1:
                named = " ".join(
                    f"{namespace}.{key}" if namespace else key for namespace, key in sorted(group)
                )
                lines.append(f"ambiguity: {named} same source, different translations")
                break
    lines.sort()
    return lines


def _source_bytes(catalog, cfg) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for namespace in cfg.namespaces_for(catalog):
        path = catalog.path_for(cfg.source_locale, namespace)
        out[str(path)] = path.read_bytes() if path.exists() else b""
    return out


def _fail(command: str, summary: str) -> OpResult:
    return OpResult(ok=False, exit_code=1, command=command, summary=summary, lines=[summary])
