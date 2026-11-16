"""Per-key edit operations behind the web editor (save, revert, verify, lock, context).

Split out of ``server_logic``; that module still re-exports every name here.
"""

from __future__ import annotations

import re
import subprocess

from ..catalog.io import atomic_write_text
from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.state import now_iso
from ..core.standards import get_standard
from ..core.validate import validate_translation_detailed
from ..pipeline.recording import record_candidate
from ..core.quality import score_translation
from ..projects.context import write_context_entry
from .server_logic import (
    AppState,
    _SAFE_NAMESPACE,
    _WRITE_LOCK,
    _coverage_bucket,
    _validate_scope,
    invalidate_caches,
    patch_caches_after_save,
)

__all__ = [
    "save",
    "revert_key",
    "validate_key",
    "set_locked",
    "history_for_key",
    "verify_key",
    "mark_example",
    "save_context",
    "set_translate_enabled",
    "add_locale",
]


def save(st: AppState, locale: str, namespace: str, key: str, value: str,
         *, full_value: str | None = None, full_key: str | None = None,
         trigger: str = "web-edit",
         provider: str | None = None,
         model: str | None = None,
         verified_by: str | None = None,
         edited_by: str | None = None,
         edited_by_name: str | None = None) -> dict:
    """Write one translation; refuses anything the validator rejects."""
    try:
        _validate_scope(st, locale, namespace, write=True)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    source = st.catalog.load(st.cfg.source_locale, namespace)
    if key not in source:
        return {"ok": False, "error": f"{key} is not in the source locale"}

    from ..catalog.provenance import PROVIDERS

    raw_provider = None if provider is None else str(provider).strip().lower()
    if raw_provider is None or raw_provider == "":
        channel = "human"
    elif raw_provider in PROVIDERS:
        channel = raw_provider
    elif raw_provider in {"null", "local"}:
        channel = "ollama"
    else:
        return {"ok": False, "error": f"unknown provider {provider!r}"}

    editor_id = (str(edited_by).strip() or None) if edited_by else None
    editor_name = (str(edited_by_name).strip() or None) if edited_by_name else None

    if channel == "agent":
        stamp_model = (model or "cursor-agent").strip() or "cursor-agent"
        stamp_status = "agent"
        edit_trigger = "agent-edit" if trigger == "web-edit" else trigger
        who = (verified_by or "cursor-agent").strip() or "cursor-agent"
    elif channel == "human":
        stamp_model = "human"
        stamp_status = "human"
        edit_trigger = trigger
        who = None
    elif channel == "import":
        stamp_model = (model or "import").strip() or "import"
        stamp_status = "imported"
        edit_trigger = trigger
        who = None
    else:
        # Allow scripts to re-attribute a save to a machine channel (rare).
        stamp_model = (model or channel).strip() or channel
        stamp_status = "machine"
        edit_trigger = trigger
        who = None

    fk = full_key or st.notes.full_key(namespace, key)
    if full_value is not None and (not fk or fk not in source):
        return {
            "ok": False,
            "error": "fullValue was sent but this key has no fullKey in the source catalogue",
        }
    fk_val = None
    if fk and fk in source:
        fk_val = st.catalog.load(locale, namespace).get(fk)
    ok, failures = validate_translation_detailed(
        source[key], value, locale, st.glossary,
        max_chars=st.notes.max_chars(namespace, key),
        fullkey_sibling=full_value if full_value is not None else fk_val,
        check_html=True if st.notes.html(namespace, key) else None,
        standard=get_standard(getattr(st.cfg, "catalog_standard", None)),
    )
    if ok:
        # C-049 (ADR-72): a warning the project graded ``error`` blocks the save.
        # Demotion (off/warning) never reaches the hard gate above.
        graded = [f for f in failures if st.cfg.severity_overrides.get(f.id) == "error"]
        if graded:
            return {
                "ok": False,
                "error": graded[0].message,
                "errors": [{"id": f.id, "message": f.message, "field": f.field} for f in graded],
            }
    else:
        return {
            "ok": False,
            "error": failures[0].message if failures else "validation failed",
            "errors": [{"id": f.id, "message": f.message, "field": f.field} for f in failures],
        }

    with _WRITE_LOCK:
      with project_mutation_lock(st.cfg):
        old_bucket = _coverage_bucket(st, locale, namespace, key)
        existing = st.catalog.load(locale, namespace)
        updates = {key: value}
        if full_value is not None and fk and fk in source:
            updates[fk] = full_value
        merged = st.catalog.merge_for_write(source, existing, updates)
        st.catalog.save(locale, namespace, merged)

        propagated: list[tuple[str, str]] = []
        if st.store is not None:
            quality = score_translation(source[key], value, locale, st.glossary)
            scores = st.scores_store()
            hist = st.history_store()
            pending_history: list = []
            entry = record_candidate(
                state=st.store,
                scores=scores,
                history=hist,
                locale=locale, namespace=namespace, key=key,
                source=source[key], previous=existing.get(key), text=value,
                model=stamp_model, quality_score=quality.score,
                quality_signals=quality.signals, trigger=edit_trigger,
                dimensions=quality.dimensions, scorer=quality.scorer,
                status=stamp_status, provider=channel,
                pending_history=pending_history,
                edited_by=editor_id,
                edited_by_name=editor_name,
            )
            if who:
                entry["verified_at"] = now_iso()
                entry["verified_by"] = who
                st.store.record(locale, namespace, key, entry)
            if full_value is not None and fk and fk in source:
                fk_entry = record_candidate(
                    state=st.store,
                    scores=scores,
                    history=hist,
                    locale=locale, namespace=namespace, key=fk,
                    source=source[fk], previous=existing.get(fk), text=full_value,
                    model=stamp_model, quality_score=1.0,
                    quality_signals=[], trigger=f"{edit_trigger}-full",
                    status=stamp_status, provider=channel,
                    pending_history=pending_history,
                    edited_by=editor_id,
                    edited_by_name=editor_name,
                )
                if who:
                    fk_entry["verified_at"] = now_iso()
                    fk_entry["verified_by"] = who
                    st.store.record(locale, namespace, fk, fk_entry)
            if edit_trigger != "web-revert" and value != source[key]:
                from ..pipeline.propagate import propagate_identical

                propagated = propagate_identical(
                    st.cfg, st.catalog, st.store, st.notes, st.glossary,
                    locale=locale, namespace=namespace, key=key,
                    source_text=source[key], text=value,
                    model=stamp_model, status=stamp_status, provider=channel,
                    pending_history=pending_history,
                    edited_by=editor_id,
                    edited_by_name=editor_name,
                )
            st.store.save(locale)
            scores.save(locale)
            for hist_locale, event in pending_history:
                hist.append(hist_locale, event)
            for hist_locale in {loc for loc, _event in pending_history}:
                hist.compact(hist_locale)
            if editor_id:
                from ..catalog.translator_activity import append_activity

                for hist_locale, event in pending_history:
                    append_activity(
                        st.cfg.state_root(),
                        user_id=editor_id,
                        username=editor_name or editor_id,
                        locale=hist_locale,
                        namespace=event.namespace,
                        key=event.key,
                        trigger=event.trigger,
                        provider=event.provider,
                    )
            if channel == "human" and edit_trigger == "web-edit":
                from ..pipeline.feedback import learn_from_edit

                try:
                    learn_from_edit(
                        st.cfg, locale=locale, source=source[key],
                        previous=existing.get(key), text=value, score=quality.score,
                    )
                except OSError:
                    pass  # the examples file is a convenience; never fail a save over it
            if who:
                from ..catalog.tm import TranslationMemory

                ctx = st.notes.note(namespace, key)
                st.cfg.open_tm().approve(
                    locale=locale,
                    source=source[key],
                    text=value,
                    context=ctx,
                    model=stamp_model,
                    provider=channel,
                )
        if propagated:
            invalidate_caches(st)
        else:
            patch_caches_after_save(
                st, locale, namespace, key, old_bucket=old_bucket,
            )
    return {"ok": True, "value": value, "status": stamp_status,
            "provider": channel, "model": stamp_model,
            "warnings": [{"id": f.id, "message": f.message} for f in failures]}


def revert_key(st: AppState, locale: str, namespace: str, key: str,
               *, to_text: str,
               edited_by: str | None = None,
               edited_by_name: str | None = None) -> dict:
    """Restore a previous translation from history (clears verification)."""
    return save(
        st, locale, namespace, key, to_text, trigger="web-revert",
        edited_by=edited_by, edited_by_name=edited_by_name,
    )


def validate_key(st: AppState, locale: str, namespace: str, key: str, value: str,
                 *, full_value: str | None = None) -> dict:
    try:
        _validate_scope(st, locale, namespace, write=True)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    source = st.catalog.load(st.cfg.source_locale, namespace)
    if key not in source:
        return {"ok": False, "error": f"{key} is not in the source locale"}
    fk = st.notes.full_key(namespace, key)
    fk_val = full_value
    if fk_val is None and fk:
        fk_val = st.catalog.load(locale, namespace).get(fk)
    ok, failures = validate_translation_detailed(
        source[key], value, locale, st.glossary,
        max_chars=st.notes.max_chars(namespace, key),
        fullkey_sibling=fk_val,
        check_html=True if st.notes.html(namespace, key) else None,
        standard=get_standard(getattr(st.cfg, "catalog_standard", None)),
    )
    return {
        "ok": ok,
        "errors": [{"id": f.id, "message": f.message, "severity": f.severity} for f in failures],
        "docsUrl": getattr(st.cfg, "docs_url", "") or "",
    }


def set_locked(st: AppState, locale: str, namespace: str, key: str, *, locked: bool) -> dict:
    """Flip the optional lock. Does not rewrite the catalogue value."""
    try:
        _validate_scope(st, locale, namespace, write=True)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if st.store is None:
        return {"ok": False, "error": "no state directory"}
    source = st.catalog.load(st.cfg.source_locale, namespace)
    if key not in source:
        return {"ok": False, "error": f"{key} is not in the source locale"}
    from ..catalog.state import state_key

    sk = state_key(namespace, key)
    with _WRITE_LOCK:
        with project_mutation_lock(st.cfg):
            old_bucket = _coverage_bucket(st, locale, namespace, key)
            bucket = st.store.load(locale)
            entry = bucket.get(sk)
            if not isinstance(entry, dict):
                entry = {}
                bucket[sk] = entry
            if locked:
                entry["locked"] = True
            else:
                entry.pop("locked", None)
            st.store.save(locale)
            patch_caches_after_save(st, locale, namespace, key, old_bucket=old_bucket)
    return {"ok": True, "locked": locked, "stateKey": sk}


def history_for_key(st: AppState, locale: str, namespace: str, key: str) -> dict:
    _validate_scope(st, locale, namespace)
    from ..catalog.history import DEFAULT_RETENTION
    events = st.history_store().events_for(
        locale, namespace, key, limit=DEFAULT_RETENTION,
    )
    from ..catalog.source_history import SourceHistory

    return {
        "retention": DEFAULT_RETENTION,
        "sourceChange": SourceHistory(st.cfg.state_root()).latest(namespace, key),
        "events": [
            {
                "ts": e.ts, "prev": e.prev, "next": e.next,
                "model": e.model, "provider": e.provider,
                "status": e.status, "trigger": e.trigger,
                "quality_score": e.quality_score,
                "candidates": e.candidates,
                "propagatedFrom": e.propagated_from,
                "editedBy": e.edited_by,
                "editedByName": e.edited_by_name,
                "prevSource": e.prev_src,
                "nextSource": e.next_src,
            }
            for e in reversed(events)
        ],
    }


def verify_key(
    st: AppState,
    locale: str,
    namespace: str,
    key: str,
    *,
    verify: bool = True,
    verified_by: str | None = None,
    edited_by: str | None = None,
    edited_by_name: str | None = None,
) -> dict:
    from ..ops.verify import verify_translation

    who = (verified_by or "web").strip() or "web"
    result = verify_translation(
        st.cfg,
        locale=locale,
        namespace=namespace,
        key=key,
        verified_by=who,
        verify=verify,
        edited_by=edited_by,
        edited_by_name=edited_by_name,
    )
    if result.get("ok"):
        patch_caches_after_save(st, locale, namespace, key)
        if edited_by and not result.get("dry_run"):
            from ..catalog.translator_activity import append_activity

            trigger = "web-verify" if verify else "web-unverify"
            if who == "workflow" and verify:
                trigger = "workflow-verify"
            append_activity(
                st.cfg.state_root(),
                user_id=edited_by,
                username=edited_by_name or edited_by,
                locale=locale,
                namespace=namespace,
                key=key,
                trigger=trigger,
            )
    return result


def mark_example(st: AppState, locale: str, namespace: str, key: str) -> dict:
    """Append the current source→target pair to ``[prompt] examples_file``."""
    from ..projects import append_example

    try:
        _validate_scope(st, locale, namespace, write=True)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not st.cfg.examples_file:
        return {"ok": False, "error": "no [prompt] examples_file configured"}
    source = st.catalog.load(st.cfg.source_locale, namespace)
    if key not in source:
        return {"ok": False, "error": f"{key} is not in the source locale"}
    target = st.catalog.load(locale, namespace)
    if key not in target or not str(target[key]).strip():
        return {"ok": False, "error": f"{key} has no translation in {locale}"}
    written = append_example(st.cfg.examples_file, locale, source[key], target[key])
    if not written:
        return {"ok": True, "added": False, "reason": "duplicate or at capacity"}
    return {"ok": True, "added": True}


def save_context(
    st: AppState, namespace: str, key: str, *,
    note: str | None = None,
    llm_note: str | None = None,
    max_chars: int | None = None,
    screen: str | None = None,
    image: str | None = None,
    tags: list[str] | str | None = None,
) -> dict:
    if not isinstance(namespace, str) or (namespace and not _SAFE_NAMESPACE.fullmatch(namespace)):
        return {"ok": False, "error": "invalid namespace"}
    if not st.cfg.context_dir:
        return {"ok": False, "error": "no context directory configured"}
    source = st.catalog.load(st.cfg.source_locale, namespace)
    if key not in source:
        return {"ok": False, "error": f"{key} is not in the source locale"}
    patch: dict = {}
    if note is not None:
        patch["note"] = note
    if llm_note is not None:
        patch["llmNote"] = llm_note
    if max_chars is not None:
        patch["maxChars"] = max_chars if max_chars > 0 else None
    if screen is not None:
        patch["screen"] = screen
    if image is not None:
        patch["image"] = image
    if tags is not None:
        from ..projects.context import normalize_tags

        patch["tags"] = normalize_tags(tags)
    with _WRITE_LOCK:
        with project_mutation_lock(st.cfg):
            write_context_entry(st.cfg.context_dir, namespace, key, patch)
            st.notes._cache.pop(namespace, None)
            invalidate_caches(st)
    return {"ok": True}


def set_translate_enabled(st: AppState, enabled: bool) -> dict:
    config_path = st.cfg.config_path
    if config_path is None:
        return {"ok": False, "error": "no config path"}
    # Full TOML read-modify-write under the project mutation lock (callers may
    # already hold it — ADR-24 locks are re-entrant in-process).
    with project_mutation_lock(st.cfg):
        text = config_path.read_text(encoding="utf-8")
        flag = "true" if enabled else "false"
        if re.search(r"^\s*enabled\s*=", text, re.MULTILINE):
            new_text = re.sub(
                r"(^\s*enabled\s*=\s*)(true|false)",
                rf"\g<1>{flag}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif "[translate]" in text:
            new_text = text.replace("[translate]", f"[translate]\nenabled = {flag}", 1)
        else:
            new_text = text.rstrip() + f"\n\n[translate]\nenabled = {flag}\n"
        atomic_write_text(config_path, new_text)
    if not enabled:
        try:
            from ..projects.taskqueue import TASK_IDS, _tq_command
            subprocess.run(
                [*_tq_command(), "stop", f"{st.cfg.name}/{TASK_IDS['translate']}"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            pass
    return {"ok": True, "translateEnabled": enabled}


def add_locale(st: AppState, locale: str, model: str | None = None) -> dict:
    """Add a locale to the project TOML and return. Caller reloads state."""
    from ..ops.add_locale import add_locale as write_locale

    return write_locale(st.cfg, locale, model)
