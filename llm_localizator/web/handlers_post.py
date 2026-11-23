"""POST route handlers for the local review server (one per _POST_ROUTES entry)."""
from __future__ import annotations

import base64
from ..catalog import (
    make_entry,
)
from ..catalog.export_formats import format_export_report, render_export
from ..catalog.import_formats import import_documents
from ..catalog.io import atomic_write_text
from ..catalog.mutation_lock import project_mutation_lock
from ..projects.collections import (
    safe_collection_path,
)
from ..projects import load_config
from ..projects.paths import is_under_root
from ..ops import dispatch_op
from .config_write import write_config_atomically
from .server_logic import (
    _WRITE_LOCK,
    _SAFE_COMPONENT,
    _SAFE_NAMESPACE,
    ScopeError,
    _validate_scope,
    _session_author,
    rotate_web_token,
    _SCREEN_ID,
    _PNG_MAGIC,
    _JPEG_MAGIC,
    build_state,
    store_state,
    invalidate_caches,
    refresh_sidecars_from_disk,
    _coverage_bucket,
    patch_caches_after_save,
    save,
    revert_key,
    validate_key,
    set_locked,
    verify_key,
    mark_example,
    save_context,
    set_translate_enabled,
    add_locale,
    _export_keys,
    posted_translation,
)


def _task_scope(st, actor, body) -> str:
    """Tasks-only contributing (C-029): a Translator writes only keys a task assigns."""
    from ..ops.permissions import task_scope_denied

    return task_scope_denied(
        st.cfg, actor.role, getattr(actor.user, "username", None),
        str(body.get("locale") or ""), [f"{body.get('namespace')}.{body.get('key')}"],
    )


class PostRoutesMixin:
    def _post_setup(self, url, body, st, actor, project):
        from ..projects.config import load_config
        import tomlkit

        path = st.cfg.config_path
        if path is None:
            return self._send({"ok": False, "error": "config path is not set"}, 400)
        project_name = (project or "").strip() or self.default_project
        with project_mutation_lock(st.cfg):
            doc = tomlkit.parse(path.read_text(encoding="utf-8"))
            if body.get("source_locale"):
                project_tbl = doc.get("project")
                if not isinstance(project_tbl, dict):
                    project_tbl = tomlkit.table()
                    doc["project"] = project_tbl
                project_tbl["source_locale"] = str(body["source_locale"])
            if "targets" in body:
                locales = doc.get("locales")
                if not isinstance(locales, dict):
                    locales = tomlkit.table()
                    doc["locales"] = locales
                arr = tomlkit.array()
                for item in body.get("targets") or []:
                    arr.append(str(item))
                locales["targets"] = arr
            if body.get("model"):
                locales = doc.get("locales")
                if not isinstance(locales, dict):
                    locales = tomlkit.table()
                    doc["locales"] = locales
                models = locales.get("models")
                if not isinstance(models, dict):
                    models = tomlkit.table()
                    locales["models"] = models
                models["default"] = str(body["model"])
            if body.get("domain"):
                prompt_tbl = doc.get("prompt")
                if not isinstance(prompt_tbl, dict):
                    prompt_tbl = tomlkit.table()
                    doc["prompt"] = prompt_tbl
                prompt_tbl["domain"] = str(body["domain"])
            if body.get("catalog_format") or body.get("catalog_path"):
                catalog = doc.get("catalog")
                if not isinstance(catalog, dict):
                    catalog = tomlkit.table()
                    doc["catalog"] = catalog
                if body.get("catalog_format"):
                    catalog["format"] = str(body["catalog_format"])
                if body.get("catalog_path"):
                    catalog["path"] = str(body["catalog_path"])
            new_text = tomlkit.dumps(doc)
            err = write_config_atomically(path, new_text)
            if err:
                return self._send({"ok": False, "error": err}, 400)
            try:
                store_state(self.states, project_name, build_state(load_config(path)), self.default_project)
            except Exception as exc:
                return self._send({"ok": False, "error": str(exc)}, 400)
            return self._send({"ok": True})

    def _post_push_strings(self, url, body, st, actor, project):
        from .auth import require_op
        from ..ops.push_strings import PushStringsRequest, op_push_strings

        denied = require_op(actor, "push-strings", cfg=st.cfg)
        if denied is not None:
            return self._send(denied, 403)
        strings = body.get("strings")
        if not isinstance(strings, dict):
            return self._send(
                {"ok": False, "error": "strings must be an object"}, 400,
            )
        result = op_push_strings(st.cfg, PushStringsRequest(
            namespace=str(body.get("namespace") or ""),
            strings={
                str(k): ("" if v is None else str(v))
                for k, v in strings.items()
            },
            dry_run=bool(body.get("dry_run")),
        ))
        if result.ok and result.data.get("written"):
            st.catalog.invalidate()
            invalidate_caches(st)
        payload = {
            "ok": result.ok,
            "added": result.data.get("added", 0),
            "updated": result.data.get("updated", 0),
            "skipped": result.data.get("skipped", 0),
            "stale_marked": result.data.get("stale_marked", 0),
            "summary": result.summary,
        }
        if not result.ok:
            payload["error"] = result.summary
        return self._send(payload, 200 if result.ok else 400)

    def _post_export(self, url, body, st, actor, project):
        collection = body.get("collection") or "messages"
        if collection != "messages":
            from ..ops.export_import import op_export
            from ..ops.types import ExportRequest
            import io
            import zipfile

            result = op_export(st.cfg, ExportRequest(
                locales=self._allowed_locales(list(body.get("locales") or st.cfg.targets)),
                collection=collection,
            ))
            if not result.ok:
                return self._send({
                    "ok": False, "error": result.summary,
                }, 400)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in result.data.get("files", []):
                    zf.writestr(
                        f"{item['locale']}/{item['path']}",
                        item.get("text") or "",
                    )
            payload = buf.getvalue()
            filename = f"{st.cfg.name}-{collection}.zip"
            return self._send({
                "ok": True,
                "filename": filename,
                "content_type": "application/zip",
                "file_base64": base64.b64encode(payload).decode("ascii"),
                "lines": result.lines,
                "summary": result.summary,
            })
        fmt = str(body.get("format") or "csv").lower()
        screenshots = bool(body.get("screenshots"))
        locs = body.get("locales") or self._allowed_locales(list(st.cfg.targets))
        namespaces = body.get("namespaces")
        if not namespaces and body.get("namespace"):
            namespaces = [body["namespace"]]
        try:
            payload, ctype, filename, report = render_export(
                st.cfg, st.catalog,
                locales=list(locs),
                namespaces=list(namespaces) if namespaces else None,
                fmt=fmt,
                layout=str(body.get("layout") or "single"),
                only=str(body.get("only") or "all"),
                screenshots=screenshots,
                file_count=body.get("file_count", 1),
                approved_only=bool(body.get("approved_only")),
                keys=_export_keys(body.get("keys")),
            )
        except ValueError as exc:
            return self._send({"ok": False, "error": str(exc)}, 400)
        lines = format_export_report(report)
        return self._send({
            "ok": True,
            "filename": filename,
            "content_type": ctype,
            "file_base64": base64.b64encode(payload).decode("ascii"),
            "report": report,
            "lines": lines,
            "summary": lines[0] if lines else "exported",
        })

    def _post_save(self, url, body, st, actor, project):
        from .auth import editor_identity

        _validate_scope(st, body["locale"], body["namespace"], write=True)
        denied = _task_scope(st, actor, body)
        if denied:
            return self._send({"ok": False, "error": denied}, 403)
        value = posted_translation(st, body["namespace"], body["key"], body)
        edited_by, edited_by_name = editor_identity(actor)
        result = save(st, body["locale"], body["namespace"],
                      body["key"], value,
                      full_value=body.get("fullValue"),
                      full_key=body.get("fullKey"),
                      provider=body.get("provider"),
                      model=body.get("model"),
                      verified_by=body.get("verified_by") or body.get("verifiedBy"),
                      edited_by=edited_by,
                      edited_by_name=edited_by_name)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_preview(self, url, body, st, actor, project):
        from ..render import preview_payload

        text = body.get("text") or ""
        fmt = body.get("format") or "icu"
        locale = body.get("locale") or st.cfg.source_locale
        values = body.get("values") if isinstance(body.get("values"), dict) else None
        mode = body.get("mode")
        try:
            if fmt == "html" and getattr(self, "paranoid_preview", False):
                from ..render.html_preview import preview_html

                html = preview_html(text, locale)
                payload = {
                    "ok": True, "html": html, "source": text,
                    "placeholders": [], "format": fmt,
                }
            else:
                payload = preview_payload(
                    text, locale, fmt, values=values, mode=mode,
                )
                payload["ok"] = True
        except ValueError as exc:
            return self._send({"ok": False, "error": str(exc)}, 400)
        return self._send(payload)

    def _post_collection_file(self, url, body, st, actor, project):
        from .auth import editor_identity
        from .document_editor import save_collection_section

        name = body.get("collection") or ""
        locale = body.get("locale") or st.cfg.source_locale
        rel = body.get("path") or ""
        text = body.get("text")
        if text is None:
            return self._send({"ok": False, "error": "text is required"}, 400)
        section = body.get("section")
        if section is not None:
            try:
                index = int(section)
            except (TypeError, ValueError):
                return self._send({"ok": False, "error": "section must be an integer"}, 400)
            edited_by, edited_by_name = editor_identity(actor)
            result = save_collection_section(
                st, name, locale, rel, index, text,
                provider=body.get("provider"),
                edited_by=edited_by,
                edited_by_name=edited_by_name,
            )
            return self._send(result, 200 if result.get("ok") else 400)
        try:
            path = safe_collection_path(st.cfg, name, locale, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            with project_mutation_lock(st.cfg):
                atomic_write_text(
                    path, text if text.endswith("\n") else text + "\n",
                )
        except ValueError as exc:
            return self._send({"ok": False, "error": str(exc)}, 400)
        return self._send({"ok": True, "path": rel})

    def _post_mark_example(self, url, body, st, actor, project):
        _validate_scope(st, body["locale"], body["namespace"], write=True)
        result = mark_example(
            st, body["locale"], body["namespace"], body["key"],
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_validate_key(self, url, body, st, actor, project):
        _validate_scope(st, body["locale"], body["namespace"], write=True)
        value = posted_translation(st, body["namespace"], body["key"], body)
        result = validate_key(
            st, body["locale"], body["namespace"], body["key"], value,
            full_value=body.get("fullValue"),
        )
        return self._send(result)

    def _post_context(self, url, body, st, actor, project):
        ns = body.get("namespace", "")
        if ns == "__all__":
            return self._send(
                {"ok": False, "error": "select a single namespace, not all namespaces"},
                400,
            )
        if ns and not _SAFE_NAMESPACE.fullmatch(ns):
            return self._send({"ok": False, "error": "invalid namespace"}, 400)
        result = save_context(
            st, ns, body["key"],
            note=body.get("note"),
            llm_note=body.get("llmNote"),
            max_chars=body.get("maxChars"),
            screen=body.get("screen"),
            image=body.get("image"),
            tags=body.get("tags"),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_screenshot_upload(self, url, body, st, actor, project):
        ns = body.get("namespace", "")
        if ns == "__all__":
            return self._send(
                {"ok": False, "error": "select a single namespace"}, 400,
            )
        if ns and not _SAFE_NAMESPACE.fullmatch(ns):
            return self._send({"ok": False, "error": "invalid namespace"}, 400)
        key = body.get("key", "")
        screen_id = (body.get("screen") or "").strip() or (
            st.notes.screen(ns, key) if key else ""
        )
        if not screen_id or not _SCREEN_ID.fullmatch(screen_id) or ".." in screen_id:
            return self._send(
                {"ok": False, "error": "screen id must match [A-Za-z0-9._-]{1,80}"},
                400,
            )
        if not st.cfg.context_dir:
            return self._send({"ok": False, "error": "no context directory configured"}, 400)
        raw_b64 = body.get("data", "")
        try:
            raw = base64.b64decode(raw_b64, validate=True)
        except (ValueError, TypeError):
            return self._send({"ok": False, "error": "invalid image data"}, 400)
        if not raw or len(raw) > 5_000_000:
            return self._send({"ok": False, "error": "image too large"}, 400)
        if not (raw.startswith(_PNG_MAGIC) or raw.startswith(_JPEG_MAGIC)):
            return self._send({"ok": False, "error": "image must be PNG or JPEG"}, 400)
        ext = ".jpg" if raw.startswith(_JPEG_MAGIC) else ".png"
        rel = f"screenshots/{screen_id}{ext}"
        dest = (st.cfg.context_dir / rel).resolve()
        if not is_under_root(dest, st.cfg.context_dir):
            return self._send({"ok": False, "error": "forbidden"}, 403)
        with project_mutation_lock(st.cfg):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            if key:
                ctx = save_context(st, ns, key, image=rel)
                if not ctx.get("ok"):
                    return self._send(ctx, 400)
        return self._send({"ok": True, "image": rel, "screenshot": rel})

    def _post_translate_enabled(self, url, body, st, actor, project):
        with project_mutation_lock(st.cfg):
            result = set_translate_enabled(st, bool(body.get("enabled", True)))
            if result.get("ok"):
                new_cfg = load_config(st.cfg.config_path)
                store_state(self.states, project, build_state(new_cfg), self.default_project)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_lock(self, url, body, st, actor, project):
        items = body.get("items")
        if isinstance(items, list) and items:
            return self._post_batch_keys(url, body, st, actor, project, action="lock")
        result = set_locked(
            st, body.get("locale", ""), body.get("namespace", ""), body.get("key", ""),
            locked=bool(body.get("locked")),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_glossary(self, url, body, st, actor, project):
        from ..projects.context import load_glossary
        from ..projects.glossary_edit import mutate_glossary

        try:
            with project_mutation_lock(st.cfg):
                result = mutate_glossary(
                    st.cfg.glossary_path,
                    domain=str(body.get("domain") or "global"),
                    action=str(body.get("action") or ""),
                    term=str(body.get("term") or ""),
                    kind=str(body.get("kind") or "term"),
                    translations=body.get("translations") if isinstance(body.get("translations"), dict) else None,
                    forbidden=body.get("forbidden") if isinstance(body.get("forbidden"), dict) else None,
                    notes=body.get("notes") if isinstance(body.get("notes"), dict) else None,
                    note=None if "note" not in body else body.get("note"),
                )
        except ValueError as exc:
            return self._send({"ok": False, "error": str(exc)}, 400)
        st.glossary = load_glossary(st.cfg.glossary_path)
        return self._send(result)

    def _post_verify(self, url, body, st, actor, project):
        from .auth import editor_identity

        items = body.get("items")
        if isinstance(items, list) and items:
            return self._post_batch_keys(url, body, st, actor, project, action="verify")
        _validate_scope(st, body["locale"], body["namespace"], write=True)
        denied = _task_scope(st, actor, body)
        if denied:
            return self._send({"ok": False, "error": denied}, 403)
        edited_by, edited_by_name = editor_identity(actor)
        result = verify_key(
            st, body["locale"], body["namespace"], body["key"],
            verify=bool(body.get("verify", True)),
            verified_by=body.get("verified_by") or body.get("verifiedBy"),
            edited_by=edited_by,
            edited_by_name=edited_by_name,
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_batch_keys(self, url, body, st, actor, project, *, action: str):
        """Batch verify/lock for the editor (Wave C)."""
        from .auth import editor_identity

        items = body.get("items")
        if not isinstance(items, list) or not items:
            return self._send({"ok": False, "error": "items[] required"}, 400)
        if len(items) > 200:
            return self._send({"ok": False, "error": "at most 200 items"}, 400)
        edited_by, edited_by_name = editor_identity(actor)
        results = []
        ok_n = 0
        for raw in items:
            if not isinstance(raw, dict):
                results.append({"ok": False, "error": "bad item"})
                continue
            locale = str(raw.get("locale") or body.get("locale") or "")
            namespace = str(raw.get("namespace") or "")
            key = str(raw.get("key") or "")
            try:
                _validate_scope(st, locale, namespace, write=True)
            except ScopeError as exc:
                results.append({"ok": False, "error": str(exc), "namespace": namespace, "key": key})
                continue
            denied = _task_scope(st, actor, {"locale": locale, "namespace": namespace, "key": key})
            if denied:
                results.append({"ok": False, "error": denied, "namespace": namespace, "key": key})
                continue
            if action == "verify":
                result = verify_key(
                    st, locale, namespace, key,
                    verify=bool(body.get("verify", True)),
                    verified_by=body.get("verified_by") or body.get("verifiedBy"),
                    edited_by=edited_by,
                    edited_by_name=edited_by_name,
                )
            else:
                result = set_locked(
                    st, locale, namespace, key,
                    locked=bool(body.get("locked", True)),
                )
            if result.get("ok"):
                ok_n += 1
            results.append({**result, "namespace": namespace, "key": key, "locale": locale})
        return self._send({"ok": ok_n == len(results), "done": ok_n, "total": len(results), "results": results})

    def _post_revert(self, url, body, st, actor, project):
        from .auth import editor_identity

        _validate_scope(st, body["locale"], body["namespace"], write=True)
        denied = _task_scope(st, actor, body)
        if denied:
            return self._send({"ok": False, "error": denied}, 403)
        edited_by, edited_by_name = editor_identity(actor)
        result = revert_key(
            st, body["locale"], body["namespace"], body["key"],
            to_text=body.get("value") or body.get("prev") or "",
            edited_by=edited_by,
            edited_by_name=edited_by_name,
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_import(self, url, body, st, actor, project):
        fmt = (body.get("format") or "csv").lower()
        locs = body.get("locales")
        if not locs and not actor.is_admin:
            locs = self._allowed_locales(list(st.cfg.targets))
        dry = bool(body.get("dry_run"))
        text = body.get("csv") or body.get("xliff") or body.get("json") or body.get("data") or ""
        suffix = {"xliff": ".xliff", "json": ".json"}.get(fmt, ".csv")
        docs = [(f"upload{suffix}", text)] if text else []
        if body.get("xlsx_base64"):
            import base64

            from ..catalog.import_formats import explode_import_file

            try:
                raw = base64.b64decode(body["xlsx_base64"], validate=True)
            except (ValueError, TypeError):
                return self._send({"ok": False, "error": "could not read the .xlsx bytes"}, 400)
            if len(raw) > 8 * 1024 * 1024:
                return self._send({"ok": False, "error": "file exceeds 8 MiB"}, 400)
            docs, error = explode_import_file(str(body.get("filename") or "upload.xlsx"), raw=raw)
            if error:
                return self._send({"ok": False, "structural": error, "error": error}, 400)
        result = import_documents(
            st.cfg, st.catalog, docs,
            locales=locs, dry_run=dry,
            model=str(body.get("model") or "import"),
            fmt=fmt if fmt in {"csv", "xliff", "json"} else None,
        )
        if not dry and result.get("accepted"):
            refresh_sidecars_from_disk(st, bust_catalog=True)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_settings(self, url, body, st, actor, project):
        from ..projects.config import load_config

        from .settings import save_settings

        frozen = body.get("frozen") if "frozen" in body else None
        asap = body.get("asap") if "asap" in body else None
        overlay = body.get("overlay_edit") if "overlay_edit" in body else None
        matrix = body.get("permission_matrix") if "permission_matrix" in body else None
        fallbacks = body.get("fallbacks") if "fallbacks" in body else None
        quality = body.get("quality") if "quality" in body else None
        providers = body.get("providers") if "providers" in body else None
        assignments = (
            body.get("locale_assignments")
            if "locale_assignments" in body else None
        )
        # Pages also send ``project`` as the selected project's *name* (a string, like every other POST); only a
        # table is a [project] settings patch. The name made every Settings save fail with "project must be an object".
        project_patch = body.get("project") if isinstance(body.get("project"), dict) else None
        with project_mutation_lock(st.cfg):
            result = save_settings(
                st.cfg,
                frozen=frozen,
                asap=asap,
                overlay_edit=overlay,
                permission_matrix=matrix,
                reset_permissions=bool(body.get("reset_permissions")),
                fallbacks=fallbacks,
                quality=quality,
                providers=providers,
                locale_assignments=assignments,
                project=project_patch,
                allow_model_writes=bool(body.get("allow_model_writes")),
            )
        if result.get("ok") and st.cfg.config_path is not None:
            try:
                written = st.cfg.config_path.resolve()
                new_cfg = load_config(st.cfg.config_path)
                for name, state in list(self.states.items()):
                    cfg_path = getattr(state.cfg, "config_path", None)
                    if name != project and cfg_path is not None and cfg_path.resolve() == written:
                        store_state(self.states, name, build_state(load_config(cfg_path)), self.default_project)
                store_state(self.states, project, build_state(new_cfg), self.default_project)
            except Exception as exc:
                return self._send({"ok": False, "error": str(exc)}, 400)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_project_config(self, url, body, st, actor, project):
        from ..projects.config import load_config

        from .project_config import save_project_config

        with project_mutation_lock(st.cfg):
            result = save_project_config(
                st.cfg,
                family=body.get("family") if "family" in body else None,
                locale_families=(
                    body.get("locale_families")
                    if "locale_families" in body else None
                ),
                glossary=body.get("glossary") if "glossary" in body else None,
                glossary_domains=(
                    body.get("glossary_domains")
                    if "glossary_domains" in body else None
                ),
                glossary_shared=(
                    body.get("glossary_shared")
                    if "glossary_shared" in body else None
                ),
                tm_shared=body.get("tm_shared") if "tm_shared" in body else None,
                tm_write=body.get("tm_write") if "tm_write" in body else None,
                **{
                    key: body[key] for key in (
                        "display_name", "description", "audience", "tone", "domain",
                        "localize", "glossary_conflict", "locale_notes",
                        "models", "bridge", "pivots", "source_locale", "scan",
                    ) if key in body
                },
            )
        return self._reload_after_save(st, project, result)

    def _reload_after_save(self, st, project, result):
        """After a config save: reload the project's state from disk, then answer with the save result.

        A reload failure (a stale server missing newly allowed fields, a TOML the loader rejects) is reported as 400.
        """
        from ..projects.config import load_config

        if result.get("ok") and st.cfg.config_path is not None:
            try:
                store_state(self.states, project, build_state(load_config(st.cfg.config_path)), self.default_project)
            except Exception as exc:
                return self._send({"ok": False, "error": str(exc)}, 400)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_workflow(self, url, body, st, actor, project):
        from ..projects.config import load_config
        from .workflow_config import save_workflows

        workflows = body.get("workflows")
        if not isinstance(workflows, dict):
            return self._send({"ok": False, "error": "workflows object required"}, 400)
        with project_mutation_lock(st.cfg):
            result = save_workflows(
                st.cfg, workflows=workflows,
                notify_webhook=str(body.get("notifyWebhook") or ""),
            )
        return self._reload_after_save(st, project, result)

    def _post_workflow_copy(self, url, body, st, actor, project):
        from ..ops.workflow import get_workflow
        from .server_logic import ProjectAccessError
        from .workflow_config import _spec_json, add_workflow

        name = str(body.get("name") or "").strip()
        target = str(body.get("toProject") or "").strip()
        spec = get_workflow(st.cfg, name)
        if spec is None:
            return self._send({"ok": False, "error": f"unknown workflow {name!r}"}, 404)
        if not target:
            return self._send({"ok": False, "error": "toProject required"}, 400)
        try:
            dst = self._state(target)
        except ProjectAccessError as exc:
            return self._send({"ok": False, "error": str(exc)}, 403)
        except Exception:  # noqa: BLE001 - unknown project
            return self._send({"ok": False, "error": f"unknown project {target!r}"}, 404)
        full = _spec_json(spec)
        row = {k: full[k] for k in ("script", "maxImproveLoops", "notify", "locales")}
        with project_mutation_lock(dst.cfg):
            result = add_workflow(
                dst.cfg, name=str(body.get("newName") or name), row=row,
                overwrite=bool(body.get("overwrite")),
            )
        if result.get("ok") and dst.cfg.config_path is not None:
            store_state(self.states, target, build_state(load_config(dst.cfg.config_path)), self.default_project)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_workflow_resume(self, url, body, st, actor, project):
        from ..ops.workflow import WorkflowSpec, get_workflow
        from ..ops.workflow_run import describe_run, load_run, resume_run

        rec = load_run(st.cfg, str(body.get("id") or ""))
        if rec is None:
            return self._send({"ok": False, "error": "unknown workflow run"}, 404)
        spec = get_workflow(st.cfg, str(rec.get("workflow"))) or WorkflowSpec(
            name=str(rec.get("workflow")),
        )
        got = resume_run(st.cfg, spec, rec["id"])
        rec = load_run(st.cfg, rec["id"]) or rec
        return self._send({"ok": True, "run": describe_run(rec), "summary": got.summary if got else ""})

    def _post_workflow_cancel(self, url, body, st, actor, project):
        from ..ops.workflow_run import cancel_run

        run = cancel_run(st.cfg, str(body.get("id") or ""))
        if run is None:
            return self._send({"ok": False, "error": "unknown workflow run"}, 404)
        return self._send({"ok": True, "run": run})

    def _bust_branches_cache(self, st) -> None:
        with st.cache_lock:
            st._branches_cache = None

    def _post_branches_track(self, url, body, st, actor, project):
        from ..projects.branches import track_branch

        with project_mutation_lock(st.cfg):
            result = track_branch(
                st.cfg,
                str(body.get("name") or ""),
                base=str(body.get("base") or "") or None,
                auto_translate=bool(body.get("auto_translate", True)),
            )
        if result.get("ok"):
            self._bust_branches_cache(st)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_branches_active(self, url, body, st, actor, project):
        from ..projects.branches import set_active_branch

        name = body.get("name")
        with project_mutation_lock(st.cfg):
            result = set_active_branch(
                st.cfg, None if name in (None, "", "main") else str(name),
            )
        if result.get("ok"):
            self._bust_branches_cache(st)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_branches_merge(self, url, body, st, actor, project):
        from ..projects.branches import merge_resolve

        choices = body.get("choices") or []
        if not isinstance(choices, list):
            return self._send({"ok": False, "error": "choices must be a list"}, 400)
        with project_mutation_lock(st.cfg):
            result = merge_resolve(st.cfg, str(body.get("branch") or ""), choices=choices)
        if result.get("ok"):
            self._bust_branches_cache(st)
            invalidate_caches(st)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_branches_archive(self, url, body, st, actor, project):
        from ..projects.branches import archive_branch

        with project_mutation_lock(st.cfg):
            result = archive_branch(st.cfg, str(body.get("name") or ""), True)
        if result.get("ok"):
            self._bust_branches_cache(st)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_branches_unarchive(self, url, body, st, actor, project):
        from ..projects.branches import archive_branch

        with project_mutation_lock(st.cfg):
            result = archive_branch(st.cfg, str(body.get("name") or ""), False)
        if result.get("ok"):
            self._bust_branches_cache(st)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_branches_delete(self, url, body, st, actor, project):
        from ..projects.branches import delete_branch

        with project_mutation_lock(st.cfg):
            result = delete_branch(
                st.cfg, str(body.get("name") or ""), confirm=body.get("confirm") is True,
            )
        if result.get("ok"):
            self._bust_branches_cache(st)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_branches_fetch(self, url, body, st, actor, project):
        from ..projects.branches import fetch_remote

        result = fetch_remote(st.cfg)
        if result.get("ok"):
            self._bust_branches_cache(st)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_model_eval_run(self, url, body, st, actor, project):
        from .model_eval import run_bakeoff, run_eval

        locale = str(body.get("locale") or "").strip()
        if not locale:
            targets = list(getattr(st.cfg, "targets", None) or [])
            if not targets:
                return self._send(
                    {"ok": False, "error": "locale required (no active targets)"},
                    400,
                )
            locale = targets[0]
        model = str(body.get("model") or "").strip()
        if model or body.get("dry_run"):
            result = run_eval(
                st.cfg, locale=locale, model=model, limit=body.get("limit"),
                corpus=str(body.get("corpus") or ""), dry_run=bool(body.get("dry_run")),
            )
        else:
            result = run_bakeoff(locale=locale)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_model_eval_apply(self, url, body, st, actor, project):
        from .model_eval import apply_recommendation

        result = apply_recommendation(
            st.cfg, report=str(body.get("report") or ""),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_web_token(self, url, body, st, actor, project):
        token = rotate_web_token(type(self), st.cfg)
        return self._send({"token": token})

    def _post_review_tickets(self, url, body, st, actor, project):
        from .review import create_review_ticket

        result = create_review_ticket(
            st.cfg,
            locale=str(body.get("locale") or ""),
            namespace=str(body.get("namespace") or ""),
            key=str(body.get("key") or ""),
            reason=str(body.get("reason") or ""),
            assignee=body.get("assignee"),
            description=body.get("description"),
            author=_session_author(actor, body.get("author")),
            title=body.get("title"),
            scores=st.scores_store(),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_add_locale(self, url, body, st, actor, project):
        if not isinstance(body.get("locale"), str) or not _SAFE_COMPONENT.fullmatch(body["locale"]):
            return self._send({"ok": False, "error": "invalid locale"}, 400)
        result = add_locale(st, body["locale"], body.get("model"))
        if result.get("ok"):
            try:
                new_cfg = load_config(st.cfg.config_path)
                store_state(self.states, project, build_state(new_cfg), self.default_project)
            except Exception as exc:
                # TOML was already patched; surface parse/reload failures
                # (e.g. stale web process missing newly allowed fields).
                return self._send({
                    "ok": False,
                    "error": (
                        f"{type(exc).__name__}: {exc}. "
                        "Locale may already be in the TOML — restart "
                        "`llm-localizator web` and reload."
                    ),
                }, 500)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_remove_locale(self, url, body, st, actor, project):
        from ..ops.remove_locale import remove_locale as drop_locale
        from ..projects.config import load_config as _load_cfg

        if not isinstance(body.get("locale"), str) or not _SAFE_COMPONENT.fullmatch(body["locale"]):
            return self._send({"ok": False, "error": "invalid locale"}, 400)
        result = drop_locale(st.cfg, body["locale"])
        if result.get("ok") and st.cfg.config_path is not None:
            try:
                new_cfg = _load_cfg(st.cfg.config_path)
                store_state(self.states, project, build_state(new_cfg), self.default_project)
            except Exception as exc:
                return self._send({"ok": False, "error": str(exc)}, 500)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_tm_import(self, url, body, st, actor, project):
        import base64

        from ..ops.tm import op_tm_import
        from ..ops.types import TmImportRequest

        raw = body.get("tmx_base64") or body.get("tmx") or ""
        xml = raw
        if body.get("tmx_base64"):
            try:
                xml = base64.b64decode(raw).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                return self._send({"ok": False, "error": f"invalid TMX: {exc}"}, 400)
        req = TmImportRequest(
            locale=str(body.get("locale") or ""),
            tmx=xml or None,
            conflict=str(body.get("conflict") or "skip"),
            dry_run=bool(body.get("dry_run")),
        )
        if req.dry_run:
            result = op_tm_import(st.cfg, req)
        else:
            with project_mutation_lock(st.cfg):
                result = op_tm_import(st.cfg, req)
        return self._send(result.to_dict(), 200 if result.ok else 400)

    def _post_retranslate(self, url, body, st, actor, project):
        project_name = body.get("project", self.default_project)
        st = self._state(project_name)
        locales = body.get("locales")
        if not locales and body.get("locale"):
            locales = [body["locale"]]
        if locales:
            for locale in locales:
                _validate_scope(st, locale, "", write=True, allow_empty_namespace=True)
        result = dispatch_op(st.cfg, "translate", {
            "locales": locales,
            "force": bool(body.get("force")),
            "dry_run": bool(body.get("dry_run")),
            "submit": bool(body.get("submit")),
            "confirm": True,
        }, actor_role=actor.role)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_mark_intentional(self, url, body, st, actor, project):
        locale = body["locale"]
        namespace = body["namespace"]
        key = body["key"]
        _validate_scope(st, locale, namespace, write=True)
        unmark = bool(body.get("unmark", False))
        source = st.catalog.load(st.cfg.source_locale, namespace)
        if key not in source:
            return self._send({"ok": False, "error": f"{key} not in source"}, 400)
        # Write only this key (the source value when the target lacks it);
        # merge_for_write would fill every other missing key with source text.
        with _WRITE_LOCK:
            with project_mutation_lock(st.cfg):
                old_bucket = _coverage_bucket(st, locale, namespace, key)
                existing = st.catalog.load(locale, namespace)
                if key not in existing:
                    merged = dict(existing)
                    merged[key] = source[key]
                    st.catalog.save(locale, namespace, merged)
                if st.store is not None:
                    new_status = "untranslated" if unmark else "intentional"
                    prev = st.store.entry(locale, namespace, key)
                    if prev:
                        entry = dict(prev)
                        entry["status"] = new_status
                    else:
                        entry = make_entry(source[key], "", status=new_status)
                    st.store.record(locale, namespace, key, entry)
                    st.store.save(locale)
                patch_caches_after_save(st, locale, namespace, key, old_bucket=old_bucket)
        return self._send({"ok": True})

    def _post_reload(self, url, body, st, actor, project):
        reloaded = []
        errors = []
        for name, app_st in list(self.states.items()):
            try:
                new_cfg = load_config(app_st.cfg.config_path)
                store_state(self.states, name, build_state(new_cfg), self.default_project)
                reloaded.append(name)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        return self._send({
            "ok": not errors,
            "reloaded": reloaded,
            "errors": errors,
        })

    def _post_save_ui_locale(self, url, body, st, actor, project):
        from .translator import save_web_ui_string

        result = save_web_ui_string(
            body.get("locale", ""),
            body.get("key", ""),
            body.get("value", ""),
            state_root=st.cfg.state_root(),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_resolve(self, url, body, st, actor, project):
        from .translator import resolve_text

        bundle_mode = body.get("mode", "project")
        locale = body.get("locale", "en")
        st = None if bundle_mode == "web-ui" else self._state(project)
        return self._send(resolve_text(
            st, locale, body.get("text", ""),
            hint_ns=body.get("namespace", ""),
            hint_key=body.get("key", ""),
        ))

    def _post_flag(self, url, body, st, actor, project):
        from .translator import flag_key

        _validate_scope(st, body["locale"], body["namespace"], write=True)
        result = flag_key(
            st, body["locale"], body["namespace"], body["key"],
            reason=body.get("reason", "flagged from translator overlay"),
        )
        return self._send(result, 200 if result.get("ok") else 400)
