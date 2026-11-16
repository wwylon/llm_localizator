"""File-collection editor: section rows under a path (ADR-109).

Identity for history and review tickets is ``doc:<collection>/<path>`` +
section index. Preview stays a view; stored Markdown is never replaced by HTML.
"""

from __future__ import annotations

import json
import re

from ..catalog.history import make_history_event
from ..catalog.io import atomic_write_text, read_json
from ..core.hash import src_hash
from ..ops.documents import documents_state_path
from ..pipeline.documents import is_frontmatter, join_sections, split_sections
from ..projects.collections import (
    get_collection,
    read_collection_file,
    safe_collection_path,
)
from ..render import preview

__all__ = [
    "doc_namespace",
    "section_heading",
    "pack_collection_file",
    "save_collection_section",
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def doc_namespace(collection: str, path: str) -> str:
    """Synthetic namespace that cannot collide with catalogue namespaces."""
    rel = str(path or "").replace("\\", "/").lstrip("/")
    return f"doc:{collection}/{rel}"


def section_heading(section: str, index: int) -> str:
    if is_frontmatter(section):
        return "Frontmatter"
    match = _HEADING_RE.search(section or "")
    if match:
        return match.group(2).strip() or f"Section {index}"
    stripped = (section or "").strip()
    if not stripped:
        return f"Section {index}"
    first = stripped.splitlines()[0].strip()
    return (first[:72] + "…") if len(first) > 72 else first


def _doc_id_from_path(rel: str) -> str:
    """Match ``document_ids`` / documents state keys (stem without extension)."""
    from ..ops.documents import doc_id_from_rel

    posix = str(rel or "").replace("\\", "/").lstrip("/")
    return doc_id_from_rel(posix)


def _preview_format(coll_format: str) -> str:
    fmt = "markdown" if coll_format in {"markdown", "md"} else coll_format
    if fmt not in {"markdown", "html", "icu"}:
        return "markdown"
    return fmt


def pack_collection_file(cfg, collection: str, locale: str, rel: str) -> dict:
    """Source + target + per-section rows for the hybrid editor."""
    coll = get_collection(cfg, collection)
    fmt = _preview_format(coll.format)
    source_locale = cfg.source_locale
    try:
        source_text = read_collection_file(cfg, collection, source_locale, rel) or ""
    except ValueError:
        source_text = ""
    try:
        target_text = read_collection_file(cfg, collection, locale, rel) or ""
    except ValueError:
        target_text = ""
    # When editing the source locale, one body is enough.
    if locale == source_locale and not target_text:
        target_text = source_text

    src_sections = split_sections(source_text) if source_text else []
    tgt_sections = split_sections(target_text) if target_text else []
    # Align lengths so a missing target section is an empty string.
    n = max(len(src_sections), len(tgt_sections), 1 if (source_text or target_text) else 0)
    if not src_sections and source_text:
        src_sections = [source_text]
    if not tgt_sections and target_text:
        tgt_sections = [target_text]
    while len(src_sections) < n:
        src_sections.append("")
    while len(tgt_sections) < n:
        tgt_sections.append("")

    sections = []
    for index in range(n):
        src = src_sections[index] if index < len(src_sections) else ""
        tgt = tgt_sections[index] if index < len(tgt_sections) else ""
        body = tgt or src
        sections.append({
            "index": index,
            "heading": section_heading(src or tgt, index),
            "source": src,
            "target": tgt,
            "isFrontmatter": is_frontmatter(src or tgt),
            "preview": preview(body, locale, fmt) if body else "",
            "namespace": doc_namespace(collection, rel),
            "key": str(index),
        })

    display = target_text if locale != source_locale else source_text
    return {
        "collection": collection,
        "locale": locale,
        "sourceLocale": source_locale,
        "path": rel,
        "format": fmt,
        "source": display,
        "sourceText": source_text,
        "targetText": target_text,
        "preview": preview(display, locale, fmt) if display else "",
        "sections": sections,
        "namespace": doc_namespace(collection, rel),
    }


def save_collection_section(
    st,
    collection: str,
    locale: str,
    rel: str,
    index: int,
    text: str,
    *,
    provider: str | None = None,
    edited_by: str | None = None,
    edited_by_name: str | None = None,
) -> dict:
    """Replace one section, rewrite the file, stamp documents state + history."""
    from ..catalog.mutation_lock import project_mutation_lock
    from ..catalog.provenance import PROVIDERS

    if index < 0:
        return {"ok": False, "error": "section index out of range"}

    raw_provider = None if provider is None else str(provider).strip().lower()
    if raw_provider is None or raw_provider == "":
        channel = "human"
        stamp_model = "human"
        stamp_status = "human"
        trigger = "web-edit"
    elif raw_provider == "agent":
        channel = "agent"
        stamp_model = "cursor-agent"
        stamp_status = "agent"
        trigger = "agent-edit"
    elif raw_provider in PROVIDERS:
        channel = raw_provider
        stamp_model = channel
        stamp_status = "machine"
        trigger = "web-edit"
    else:
        return {"ok": False, "error": f"unknown provider {provider!r}"}

    cfg = st.cfg
    try:
        path = safe_collection_path(cfg, collection, locale, rel)
        source_locale = cfg.source_locale
        try:
            source_text = read_collection_file(cfg, collection, source_locale, rel) or ""
        except ValueError:
            source_text = ""
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    src_sections = split_sections(source_text) if source_text else []
    tgt_sections = split_sections(existing) if existing else list(src_sections)
    # Pad target to source length so a new locale can fill section 0 of N.
    while len(tgt_sections) < max(len(src_sections), index + 1):
        pad_i = len(tgt_sections)
        tgt_sections.append(src_sections[pad_i] if pad_i < len(src_sections) else "")
    if index >= len(tgt_sections):
        return {"ok": False, "error": "section index out of range"}

    prev = tgt_sections[index]
    next_text = text if text.endswith("\n") or text == "" else text + "\n\n"
    tgt_sections[index] = next_text
    joined = join_sections(tgt_sections)
    if joined and not joined.endswith("\n"):
        joined += "\n"

    ns = doc_namespace(collection, rel)
    key = str(index)
    src_section = src_sections[index] if index < len(src_sections) else ""
    digest = src_hash(src_section) if src_section else src_hash(next_text)
    doc_id = _doc_id_from_path(rel)

    with project_mutation_lock(cfg):
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, joined)

        # Documents pipeline state (per-locale JSON keyed by doc id → section).
        coll = get_collection(cfg, collection)
        if coll.root is not None:
            state_path = documents_state_path(cfg, coll.root, locale)
            state = read_json(state_path) if state_path.exists() else {}
            if not isinstance(state, dict):
                state = {}
            doc_state = state.get(doc_id)
            if not isinstance(doc_state, dict):
                doc_state = {}
            doc_state[str(index)] = {
                "src_sha": digest,
                "model": stamp_model,
                "text": next_text,
                "src": src_section,
                "status": stamp_status,
                "provider": channel if channel != "human" else "human",
            }
            state[doc_id] = doc_state
            state_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                state_path,
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            )

        history = getattr(st, "history", None)
        if history is None and hasattr(st, "history_store"):
            history = st.history_store
        if history is not None:
            history.append(locale, make_history_event(
                namespace=ns,
                key=key,
                prev=prev,
                next_text=next_text,
                model=stamp_model,
                status=stamp_status,
                src_sha=digest,
                trigger=trigger,
                provider="human" if channel == "human" else channel,
                edited_by=edited_by,
                edited_by_name=edited_by_name,
            ))

    return {
        "ok": True,
        "path": rel,
        "section": index,
        "namespace": ns,
        "key": key,
        "collection": collection,
        "locale": locale,
    }
