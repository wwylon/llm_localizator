"""Documents operation: preview, enqueue, or execute Markdown/HTML translation."""

from __future__ import annotations

import json
from pathlib import Path

from ..catalog.io import atomic_write_text, read_json
from ..pipeline.documents import translate_document
from ..projects import ProjectConfig
from ..projects.taskqueue import TaskqueueNotFound, submit
from ..providers import project_provider
from .cloud_gate import cloud_gate, release_cloud_hold
from .types import DocumentsRequest, OpResult

__all__ = [
    "DOC_EXTENSIONS",
    "markdown_ids",
    "document_ids",
    "doc_id_from_rel",
    "resolve_document_path",
    "op_documents",
    "execute_documents",
    "document_source_texts",
    "documents_dir",
    "documents_state_path",
]

# File-collection articles: Markdown or HTML (arena bots use HTML help pages).
DOC_EXTENSIONS = (".md", ".html", ".htm")


def documents_dir(cfg: ProjectConfig, override: str | None = None) -> Path:
    if override:
        return Path(override)
    if cfg.documents_dir:
        return cfg.documents_dir
    return cfg.root / "content" / "legal"


def documents_state_path(cfg: ProjectConfig, doc_dir: Path, locale: str) -> Path:
    return cfg.documents_state_root(doc_dir) / f"{locale}.json"


# Private aliases kept for in-module call sites.
_documents_dir = documents_dir
_state_path = documents_state_path


def doc_id_from_rel(rel: str) -> str:
    """Strip a known document extension from a relative path."""
    lower = rel.lower()
    for ext in DOC_EXTENSIONS:
        if lower.endswith(ext):
            return rel[: -len(ext)]
    return rel


def _strip_doc_ext(rel: str) -> str:
    return doc_id_from_rel(rel)


def document_ids(source_dir: Path) -> list[str]:
    """Relative ids for ``*.md`` / ``*.html`` / ``*.htm``, including nested help.

    ``terms.md`` stays ``terms``. ``help/blackjack.html`` stays ``help/blackjack``.
    Prefer ``.md`` when the same stem exists in more than one extension.
    """
    if not source_dir.is_dir():
        return []
    by_id: dict[str, str] = {}
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in DOC_EXTENSIONS:
            continue
        rel = path.relative_to(source_dir).as_posix()
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        doc_id = _strip_doc_ext(rel)
        prev = by_id.get(doc_id)
        if prev is None or path.suffix.lower() == ".md":
            by_id[doc_id] = path.suffix.lower()
    return sorted(by_id)


def markdown_ids(source_dir: Path) -> list[str]:
    """Alias for :func:`document_ids` (historical name)."""
    return document_ids(source_dir)


def resolve_document_path(locale_dir: Path, doc_id: str) -> Path | None:
    """Find ``doc_id`` under *locale_dir* as ``.md``, ``.html``, or ``.htm``."""
    for ext in DOC_EXTENSIONS:
        path = locale_dir / f"{doc_id}{ext}"
        if path.is_file():
            return path
    return None


def document_source_texts(
    cfg: ProjectConfig, doc_dir: Path, docs: list[str],
) -> list[str]:
    """Source document bodies for cloud quotes (not catalogue keys)."""
    source_dir = doc_dir / cfg.source_locale
    out: list[str] = []
    for doc in docs:
        path = resolve_document_path(source_dir, doc)
        if path is None:
            continue
        try:
            out.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return out


def execute_documents(
    cfg: ProjectConfig,
    *,
    locales: list[str],
    docs: list[str],
    doc_dir: Path,
    model: str | None = None,
    dry_run: bool = False,
    report=None,
) -> OpResult:
    """Translate named documents for each locale. Shared by CLI and ops."""
    provider = project_provider(cfg)
    source_dir = doc_dir / cfg.source_locale
    resolved_model = model or cfg.documents_model
    lines: list[str] = []
    failures = 0
    translated = 0

    def _line(msg: str) -> None:
        lines.append(msg)
        if report is not None:
            report(msg)

    for locale in locales:
        state_path = _state_path(cfg, doc_dir, locale)
        state = read_json(state_path) if state_path.exists() else {}
        if not isinstance(state, dict):
            state = {}
        for doc in docs:
            source = resolve_document_path(source_dir, doc)
            if source is None:
                _line(f"  skip {locale}/{doc}: no source under {source_dir}")
                continue
            target = doc_dir / locale / f"{doc}{source.suffix.lower()}"
            doc_state = state.setdefault(doc, {})
            if not isinstance(doc_state, dict):
                doc_state = {}
                state[doc] = doc_state
            result = translate_document(
                source, target, locale, provider,
                model=resolved_model or cfg.model_for(locale),
                domain=cfg.domain,
                state=doc_state,
                timeout_s=cfg.provider.timeout_batch_s,
                dry_run=dry_run,
                project=cfg,
            )
            status = "ok" if result.ok else f"FAILED ({result.failed})"
            _line(
                f"  {locale}/{doc}: {result.translated} translated, "
                f"{result.reused} reused — {status}"
            )
            translated += int(result.translated or 0)
            if not result.ok:
                failures += 1
        if not dry_run:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                state_path,
                json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            )

    if dry_run:
        _line("(100%) Dry run — nothing written.")
    summary = (
        f"{len(docs)} document(s) × {len(locales)} locale(s): "
        f"{translated} section(s) translated"
        + (f", {failures} failed" if failures else "")
        + (" (dry-run)" if dry_run else "")
    )
    return OpResult(
        ok=failures == 0,
        exit_code=1 if failures else 0,
        command="documents",
        summary=summary,
        lines=lines,
        data={
            "documents": docs,
            "locales": locales,
            "docDir": str(doc_dir),
            "translated": translated,
            "failed": failures,
            "dryRun": dry_run,
        },
    )


def op_documents(cfg: ProjectConfig, req: DocumentsRequest, *, report=None) -> OpResult:
    doc_dir = _documents_dir(cfg, req.doc_dir)
    if not doc_dir.is_dir():
        return OpResult(
            ok=False,
            exit_code=64,
            command="documents",
            summary=f"no document directory at {doc_dir}",
            lines=["Set [documents] dir or pass doc_dir."],
        )

    source_dir = doc_dir / cfg.source_locale
    docs = [req.doc] if req.doc else document_ids(source_dir)
    if not docs:
        return OpResult(
            ok=False,
            exit_code=64,
            command="documents",
            summary=f"no .md/.html documents under {source_dir}",
            lines=[],
        )

    locales = list(req.locales) if req.locales else list(cfg.active_targets())
    texts = document_source_texts(cfg, doc_dir, docs)
    texts_by_locale = {loc: list(texts) for loc in locales}
    hold_id: str | None = None
    enqueue = bool(req.submit) and not bool(getattr(req, "inline", False))
    if not req.dry_run:
        blocked, hold_id = cloud_gate(
            cfg, "documents", locales=locales,
            keys=list(docs),
            texts_by_locale=texts_by_locale,
            take_hold=not enqueue,
        )
        if blocked is not None:
            return blocked

    lines = [
        f"documents in {doc_dir}",
        f"  {len(docs)} document(s): {', '.join(docs)}",
        f"  target locale(s): {', '.join(locales)}",
    ]

    if enqueue:
        overrides: dict[str, str] = {}
        if locales:
            overrides["--locales"] = ",".join(locales)
        if req.model:
            overrides["--model"] = req.model
        if req.dry_run:
            overrides["--dry-run"] = "true"
        if req.doc_dir:
            # A named collection (`translate --collection rules`) is not the [documents]
            # default: the queued run must read the same tree this preview read.
            overrides["--doc-dir"] = doc_dir.as_posix()  # backslashes break the YAML quoting
        try:
            outcome = submit(cfg, "documents", overrides)
            return OpResult(
                ok=outcome.ok,
                exit_code=outcome.exit_code,
                command="documents",
                summary=outcome.message,
                lines=lines + ([outcome.message] if outcome.message else []),
                data={"documents": docs, "locales": locales, "submitted": outcome.ok},
            )
        except TaskqueueNotFound as exc:
            return OpResult(
                ok=False, exit_code=1, command="documents",
                summary=str(exc), lines=lines,
            )
        finally:
            release_cloud_hold(cfg, hold_id)

    # Preview listing only when dry-run and not executing inline.
    if req.dry_run and not bool(getattr(req, "inline", False)):
        lines.append("(dry-run preview — use Submit to taskqueue or inline to translate)")
        return OpResult(
            ok=True,
            exit_code=0,
            command="documents",
            summary=f"{len(docs)} document(s) for {len(locales)} locale(s)",
            lines=lines,
            data={"documents": docs, "locales": locales, "docDir": str(doc_dir)},
        )

    try:
        return execute_documents(
            cfg,
            locales=locales,
            docs=docs,
            doc_dir=doc_dir,
            model=req.model,
            dry_run=req.dry_run,
            report=report,
        )
    finally:
        release_cloud_hold(cfg, hold_id)
