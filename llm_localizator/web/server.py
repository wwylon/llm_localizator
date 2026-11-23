from __future__ import annotations


import base64
import functools
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections import OrderedDict
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from ..catalog import (
    Catalog, HistoryStore, ScoreStore, StateStore, build_catalog,
    make_entry, needs_translation,
)
from ..catalog.history import make_history_event
from ..catalog.export_formats import format_export_report, render_export
from ..catalog.import_formats import import_documents
from ..catalog.io import atomic_write_text
from ..catalog.mutation_lock import project_mutation_lock
from ..projects.collections import (
    get_collection,
    list_collection_files,
    read_collection_file,
    safe_collection_path,
    visible_collections,
)
from ..render import preview
from ..catalog.state import is_verified, now_iso
from ..core.standards import get_standard
from ..core.validate import validate_translation, validate_translation_detailed
from ..pipeline.validate import run_validation
from ..pipeline.recording import record_candidate
from ..core.quality import score_translation
from ..projects import ContextNotes, ProjectConfig, load_config, load_glossary, load_registry
from ..projects.context import write_context_entry
from ..projects.paths import is_under_root
from ..projects.screenshots import resolve_screenshot_path
from ..ops import build_commands_manifest, dispatch_op, is_streamable
from ..cli.main import build_parser
from .. import __version__
from ..doctor import package_info, ui_digest
from .config_write import write_config_atomically
from .assets import WEB_FEATURES, static_cache_control, ui_source
from .responses import ResponseMixin
from .shell import render_shell, route_for_path, token_snippet
from .index import (
    FULL_FINDINGS_THRESHOLD,
    MAX_PAGE_LIMIT,
    PAGE_SIZE_ALL_THRESHOLD,
    MessageIndex,
    clamp_limit,
    hydrate_rows,
    index_cache_key,
)

__all__ = [
    "serve", "build_state", "messages", "message_row", "findings", "overview",
    "overview_lite", "overview_stats", "save",
    "mark_example", "history_for_key", "verify_key", "validate_key",
    "save_context", "set_translate_enabled", "revert_key", "invalidate_caches",
    "refresh_sidecars_from_disk",
    "invalidate_caches_after_save", "patch_caches_after_save",
]

from .handlers_get import GetRoutesMixin
from .handlers_auth import AuthRoutesMixin
from .handlers_post import PostRoutesMixin
from .server_logic import (
    _MODELS_CACHE,
    ProjectAccessError,
    ProjectLoadError,
    DEFAULT_PORT,
    DEFAULT_MARKETING_PORT,
    _MARKETING_STATIC,
    _WRITE_LOCK,
    _STATES_LOCK,
    _SAFE_COMPONENT,
    _SAFE_NAMESPACE,
    ScopeError,
    _validate_scope,
    _session_author,
    _host_allowed,
    _safe_filename,
    SECURITY_HEADERS,
    max_body_bytes,
    _origin_allowed,
    _same_origin,
    _install_session_token,
    rotate_web_token,
    _SCREEN_ID,
    _PNG_MAGIC,
    _JPEG_MAGIC,
    _cors_origin,
    _OVERLAY_DIR,
    _SHELL_STATIC_DIR,
    _SHELL_STATIC,
    AppState,
    build_state,
    invalidate_caches,
    refresh_sidecars_from_disk,
    _OPS_REFRESH_SIDECARS,
    _OPS_BUST_CATALOG,
    _coverage_bucket,
    patch_caches_after_save,
    invalidate_caches_after_save,
    _commands_manifest,
    _INDEX_CACHE_CAP,
    _FINDINGS_CACHE_CAP,
    _message_index,
    _source_total,
    _load_primary_state,
    _registered_project_names,
    _tq_on_path,
    overview_lite,
    _overview_from_index,
    _warm_full_index,
    _dashboard_extras,
    overview_stats,
    overview,
    findings,
    _findings_payload,
    _parse_finding_keys,
    messages,
    message_row,
    save,
    revert_key,
    validate_key,
    set_locked,
    history_for_key,
    verify_key,
    mark_example,
    save_context,
    set_translate_enabled,
    add_locale,
    _CLIENT_GONE,
    _export_keys,
    posted_translation,
)


#: Pages a visitor without a session may open: signing in and registering.
_ACCOUNT_PAGES = frozenset({"login", "register", "pending", "setup"})


def default_op_targets(cmd: str, cfg) -> list[str]:
    """Locales an op runs on when the request names none.

    An LLM op (translate, improve, review, …) uses the default sweep, which leaves frozen locales out, as the CLI
    does; read-only ops (validate, status) still cover every target. A frozen locale named explicitly still runs.
    """
    from ..ops.command_descriptor import by_name

    desc = by_name().get(cmd.replace("_", "-"))
    return cfg.active_targets() if desc is not None and desc.llm else list(cfg.targets)


_LOG = logging.getLogger("llm_localizator.web")


class _Handler(ResponseMixin, GetRoutesMixin, AuthRoutesMixin, PostRoutesMixin, BaseHTTPRequestHandler):
    states: dict[str, AppState]   # injected by serve()
    default_project: str
    timeout = 60  # idle sockets must not pin a handler thread forever

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        pass

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_GONE):
            return
        super().handle_error(request, client_address)

    def _stream_op(
        self, cfg, cmd: str, body: dict, *, actor_role: str | None = None,
        catalog=None, status_rows=None, st=None, actor_name: str | None = None,
    ) -> None:
        """SSE progress for long-running ops (rescore, review, translate, …)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.flush()
        except OSError:
            return

        emit_lock = threading.Lock()
        stop_heartbeat = threading.Event()

        def emit(event: dict) -> bool:
            """Write one SSE event. Return False if the client is gone."""
            payload = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
            with emit_lock:
                try:
                    self.wfile.write(payload)
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    return False

        def report(line: str) -> None:
            if not emit({"type": "log", "line": line}):
                raise BrokenPipeError("ops stream client disconnected")

        def _heartbeat() -> None:
            # Comment frames keep proxies from idle-dropping long translates.
            while not stop_heartbeat.wait(15.0):
                with emit_lock:
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except OSError:
                        stop_heartbeat.set()
                        return

        beat = threading.Thread(target=_heartbeat, name=f"sse-hb-{cmd}", daemon=True)
        beat.start()
        try:
            if not emit({"type": "log", "line": f"starting {cmd}…"}):
                return
            result = dispatch_op(
                cfg, cmd, body, report=report, actor_role=actor_role, actor_name=actor_name,
                catalog=catalog, status_rows=status_rows,
            )
            if st is not None:
                # Same cache refresh as a plain request: a streamed translate or improve changes the catalogue too.
                self._after_op(st, cmd, body, result)
            emit({"type": "result", **result})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:
            emit({
                "type": "result",
                "ok": False,
                "exit_code": 1,
                "command": cmd,
                "summary": f"{type(exc).__name__}: {exc}",
                "lines": [],
                "data": {},
                "error": str(exc),
            })
        finally:
            stop_heartbeat.set()

    def _state(self, project: str, *, check_access: bool = True) -> AppState:
        # Auth pages and early paint often send project="" — treat as default.
        name = (project or "").strip() or self.default_project
        if check_access and name != self.default_project:
            from .auth import project_allowed

            if not project_allowed(self._actor(), name, self.default_project):
                raise ProjectAccessError(
                    f"project {name!r} is not allowed for this user"
                )
        with _STATES_LOCK:
            if name in self.states:
                if isinstance(self.states, dict) and hasattr(self.states, "move_to_end"):
                    self.states.move_to_end(name)  # type: ignore[attr-defined]
                return self.states[name]
            entry = load_registry().get(name)
            if entry is None:
                raise ValueError(f"unknown project {name!r}")
            try:
                cfg = load_config(entry.config_path)
                self.states[name] = build_state(cfg)
                if isinstance(self.states, dict) and hasattr(self.states, "move_to_end"):
                    from .server_logic import _prune_states, _STATES_CAP

                    self.states.move_to_end(name)  # type: ignore[attr-defined]
                    if len(self.states) > _STATES_CAP:
                        _prune_states(self.states, keep=self.default_project)  # type: ignore[arg-type]
            except Exception as exc:
                raise ProjectLoadError(name, exc, entry.config_path) from exc
            return self.states[name]

    def _locale_guard(self, locales, *, allow_anonymous: bool = False) -> bool:
        """Send 403/401 and return True when the caller may not read these locales.

        Sensitive catalogue GETs require a session or startup token. Overlay
        bundle routes pass ``allow_anonymous=True`` (consumer CTRL-inspect).
        """
        from .auth import locale_allowed

        actor = self._actor()
        if actor.kind == "anonymous":
            if allow_anonymous:
                return False
            self._send(
                {"ok": False, "error": "authentication required"},
                401,
            )
            return True
        for loc in locales:
            if loc and not locale_allowed(actor, str(loc)):
                self._send(
                    {"ok": False, "error": f"locale {loc} is not allowed for this user"},
                    403,
                )
                return True
        return False

    def _allowed_locales(self, locales) -> list[str]:
        from .auth import resolve_locales

        actor = self._actor()
        if actor.kind == "anonymous":
            return []
        resolved, _err = resolve_locales(actor, list(locales) if locales else None, list(locales) if locales else [])
        # When *locales* is the full target list (caller default), empty request
        # semantics apply: intersect with what the actor may see.
        if not locales:
            return resolved
        # Caller passed an explicit list (often cfg.targets): keep only allowed.
        from .auth import locale_allowed
        return [l for l in locales if locale_allowed(actor, l)]

    def _filter_locale_payload(self, payload: dict, targets) -> dict:
        """Project aggregate GET payloads onto locales the actor may see."""
        if not isinstance(payload, dict):
            return payload
        allowed = set(self._allowed_locales(list(targets or [])))
        out = dict(payload)

        def _keep_row(row) -> bool:
            if isinstance(row, dict):
                loc = row.get("locale")
                return loc is None or str(loc) in allowed
            return str(row) in allowed

        for key in ("locales", "localeRows", "eta", "series"):
            rows = out.get(key)
            if isinstance(rows, list) and rows and (
                isinstance(rows[0], dict) and "locale" in rows[0]
                or not isinstance(rows[0], dict)
            ):
                if key == "series" and rows and isinstance(rows[0], dict) and "locale" not in rows[0]:
                    continue
                out[key] = [r for r in rows if _keep_row(r)]
        for key in ("activeLocales", "frozenLocales"):
            rows = out.get(key)
            if isinstance(rows, list):
                out[key] = [loc for loc in rows if str(loc) in allowed]
        data = out.get("data")
        if isinstance(data, dict) and isinstance(data.get("locales"), list):
            data = dict(data)
            data["locales"] = [r for r in data["locales"] if _keep_row(r)]
            out["data"] = data
        return out

    def _project_names(self) -> list[str]:
        names = set(self.states)
        names.update(load_registry().keys())
        names.add(self.default_project)
        return sorted(names)

    # -------------------------------------------------------------------
    # GET route table — exact path matches only.
    # Prefix routes (/locales/*.json), redirects, static files, and
    # shell routes stay inline in do_GET below.
    # -------------------------------------------------------------------
    _GET_ROUTES: dict[str, str] = {
        "/api/projects":               "_get_projects",
        "/api/ui-locales":             "_get_ui_locales",
        "/api/dashboard":              "_get_dashboard",
        "/api/overview":               "_get_overview",
        "/api/overview-lite":          "_get_overview_lite",
        "/api/overview-stats":         "_get_overview_stats",
        "/api/collections":            "_get_collections",
        "/api/collection-files":       "_get_collection_files",
        "/api/collection-file":        "_get_collection_file",
        "/api/models":                 "_get_models",
        "/api/locales":                "_get_locales",
        "/api/setup-state":            "_get_setup_state",
        "/api/messages":               "_get_messages",
        "/api/messages/row":           "_get_messages_row",
        "/api/findings":               "_get_findings",
        "/api/export":                 "_get_export",
        "/api/screenshot":             "_get_screenshot",
        "/api/commands":               "_get_commands",
        "/api/version":                "_get_version",
        "/api/bootstrap-token":        "_get_bootstrap_token",
        "/api/history":                "_get_history",
        "/overlay.js":                 "_get_overlay_js",
        "/overlay.css":                "_get_overlay_css",
        "/api/tm/concordance":         "_get_tm_concordance",
        "/api/tm/leverage":            "_get_tm_leverage",
        "/api/tm/browse":              "_get_tm_browse",
        "/api/tm/export":              "_get_tm_export",
        "/api/report-parts":           "_get_report_parts",
        "/api/report-part":            "_get_report_part",
        "/api/glossary":               "_get_glossary",
        "/api/bundle":                 "_get_bundle",
        "/api/auth/me":                "_get_auth_me",
        "/api/settings":               "_get_settings",
        "/api/provider-status":        "_get_provider_status",
        "/api/project-config":         "_get_project_config",
        "/api/model-eval":             "_get_model_eval",
        "/api/workflow":               "_get_workflow",
        "/api/workflow/run":           "_get_workflow_run",
        "/api/workflow/summary":       "_get_workflow_summary",
        "/api/branches":               "_get_branches",
        "/api/branches/sync":          "_get_branches_sync",
        "/api/branches/merge-preview": "_get_branches_merge_preview",
        "/api/branches/diff":          "_get_branches_diff",
        "/api/usage":                  "_get_usage",
        "/api/usage/export":           "_get_usage_export",
        "/api/progress":               "_get_progress",
        "/api/translator-activity":    "_get_translator_activity",
        "/api/metrics":                "_get_metrics",
        "/api/status":                 "_get_status",
        "/api/scan/status":            "_get_scan_status",
        "/api/queue":                  "_get_queue",
        "/api/scan/hits":              "_get_scan_hits",
        "/api/analysis":               "_get_analysis",
        "/api/analysis/report":        "_get_analysis_report",
        "/api/review/tickets":         "_get_review_tickets",
        "/api/review/counts":          "_get_review_counts",
        "/api/translator-lookup":      "_get_translator_lookup",
        "/api/translator-bundle":      "_get_translator_bundle",
        "/api/translator-config":      "_get_translator_config",
    }

    def do_GET(self) -> None:  # noqa: N802
        from . import timing as web_timing

        if not _host_allowed(self.headers.get("Host")):
            return self._send({"error": "host not allowed"}, 403)
        url = urlparse(self.path)
        q = parse_qs(url.query)
        one = lambda name, default="": (q.get(name) or [default])[0]
        cfg = None
        try:
            cfg = self._state(self.default_project, check_access=False).cfg
        except Exception:
            _LOG.debug("default project config unavailable for %s", self.path, exc_info=True)
            cfg = None
        web_timing.reset(
            enabled=web_timing.enabled_for_request(
                query_profile=one("profile"), cfg=cfg,
            ),
        )

        try:
            mkt_port = int(getattr(self, "marketing_port", 0) or 0)
            if mkt_port:
                from .marketing import MARKETING_REDIRECTS

                if url.path in MARKETING_REDIRECTS:
                    dest = MARKETING_REDIRECTS[url.path]
                    self.send_response(302)
                    self.send_header(
                        "Location", f"http://127.0.0.1:{mkt_port}{dest}",
                    )
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

            from .ui_locale_path import (
                UI_LOCALE_COOKIE,
                needs_locale_redirect,
                prefixed_path,
                split_ui_locale_path,
                ui_locales,
            )

            # Prefer the cfg already loaded above (populates states). Falling
            # back to states.get alone missed qa_locales when _state failed
            # earlier in the same request and left the cache empty.
            qa = ()
            if cfg is not None:
                qa = tuple(getattr(cfg, "qa_locales", ()) or ())
            else:
                st0 = self.states.get(getattr(self, "default_project", "") or "")
                if st0 is not None:
                    qa = tuple(getattr(st0.cfg, "qa_locales", ()) or ())
            allowed = ui_locales(qa)

            if url.path in ("/", "/index.html"):
                preferred = self._cookie(UI_LOCALE_COOKIE) or "en"
                if preferred not in allowed:
                    preferred = "en"
                self.send_response(302)
                self.send_header(
                    "Location", prefixed_path(preferred, "/app", allowed=allowed),
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            ui_locale, app_path = split_ui_locale_path(url.path)
            # QA marker in the URL but not enabled → strip to bare path + redirect.
            if ui_locale is not None and ui_locale not in allowed:
                preferred = self._cookie(UI_LOCALE_COOKIE) or "en"
                if preferred not in allowed:
                    preferred = "en"
                loc = prefixed_path(preferred, app_path, allowed=allowed)
                if url.query:
                    loc = f"{loc}?{url.query}"
                self.send_response(302)
                self.send_header("Location", loc)
                self.send_header(
                    "Set-Cookie",
                    f"{UI_LOCALE_COOKIE}={preferred}; Path=/; SameSite=Lax",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if ui_locale is None and needs_locale_redirect(url.path):
                preferred = self._cookie(UI_LOCALE_COOKIE) or "en"
                if preferred not in allowed:
                    preferred = "en"
                loc = prefixed_path(preferred, url.path, allowed=allowed)
                if url.query:
                    loc = f"{loc}?{url.query}"
                self.send_response(302)
                self.send_header("Location", loc)
                self.send_header(
                    "Set-Cookie",
                    f"{UI_LOCALE_COOKIE}={preferred}; Path=/; SameSite=Lax",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if url.path.startswith("/locales/") and url.path.endswith(".json"):
                locales_root = (Path(__file__).parent / "locales").resolve()
                rel = url.path[len("/locales/"):].lstrip("/")
                locale_file = (locales_root / rel).resolve()
                try:
                    locale_file.relative_to(locales_root)
                except ValueError:
                    return self._send({"error": "not found"}, 404)
                if locale_file.is_file():
                    body = locale_file.read_bytes()
                    return self._send(body, content_type="application/json; charset=utf-8")
                return self._send({"error": "not found"}, 404)

            handler_name = self._GET_ROUTES.get(url.path)
            if handler_name is not None:
                from .get_policy import policy_for_get

                get_pol = policy_for_get(url.path)
                # Unlisted API GETs default to auth (fail closed). Overlay
                # routes must opt into anonymous in get_policy.GET_POLICY.
                if get_pol is None or get_pol == "auth":
                    actor = self._actor()
                    if actor.kind == "anonymous":
                        return self._send(
                            {"ok": False, "error": "authentication required"},
                            401,
                        )
                elif get_pol == "admin":
                    actor = self._actor()
                    if not actor.is_admin:
                        return self._send(
                            {"ok": False, "error": "Admin required"},
                            403,
                        )
                return getattr(self, handler_name)(url, q, one)

            static = _SHELL_STATIC.get(url.path)
            if static is not None:
                name, ctype = static
                body = (_SHELL_STATIC_DIR / name).read_bytes()
                return self._send(
                    body,
                    content_type=ctype,
                    cache_control=static_cache_control(url.path, url.query),
                    etag=True,
                )

            shell_route = route_for_path(app_path if ui_locale else url.path)
            if shell_route is not None:
                if shell_route.id not in _ACCOUNT_PAGES and self._needs_login():
                    # Accounts exist and this browser has no session: the shell token grants no role (M0), so the
                    # app pages would only show "sign in required" errors. Send people to the login page instead.
                    login = f"/{ui_locale}/login" if ui_locale else "/login"
                    self.send_response(302)
                    self.send_header("Location", login)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                token = getattr(self, "session_token", "") or ""
                html = render_shell(
                    shell_route.id, token, ui_locale=ui_locale or "en",
                    qa_locales=list(qa),
                )
                cookies = []
                if ui_locale:
                    cookies.append(
                        f"{UI_LOCALE_COOKIE}={ui_locale}; Path=/; SameSite=Lax",
                    )
                return self._send(
                    html.encode("utf-8"),
                    content_type="text/html; charset=utf-8",
                    no_cache=True,
                    set_cookies=cookies or None,
                )

            self._send({"error": "not found"}, 404)
        except ProjectAccessError as exc:
            self._send({"ok": False, "error": str(exc)}, 403)
        except ProjectLoadError as exc:
            self._send({"ok": False, "error": str(exc), "hint": exc.hint,
                        "project": exc.project}, 409)
        except Exception as exc:
            _LOG.exception("GET %s failed", self.path)
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)

    # -------------------------------------------------------------------
    # GET handlers — one per route in _GET_ROUTES
    # -------------------------------------------------------------------
















































    # -------------------------------------------------------------------
    # POST route table — exact path matches only.
    # Preamble, auth routes, actor/mutation/admin checks, regex routes
    # (/api/review/tickets/*/comment|status), and /api/ops/ prefix all
    # stay inline in do_POST below.
    # -------------------------------------------------------------------
    _AUTH_ROUTES: dict[str, str] = {
        "/api/auth/register": "_post_auth_register",
        "/api/auth/login": "_post_auth_login",
        "/api/auth/logout": "_post_auth_logout",
        "/api/auth/users": "_post_auth_users",
        "/api/auth/users/approve": "_post_auth_approve",
        "/api/auth/users/deny": "_post_auth_deny",
        "/api/auth/users/remove": "_post_auth_remove",
        "/api/setup/smoke-test": "_post_auth_smoke_test",
        "/api/setup": "_post_auth_setup",
    }

    _POST_PATTERN_ROUTES: tuple[tuple[str, str], ...] = (
        (r"/api/review/tickets/([^/]+)/comment", "_post_ticket_comment"),
        (r"/api/review/tickets/([^/]+)/status", "_post_ticket_status"),
    )

    _POST_ROUTES: dict[str, str] = {
        "/api/push-strings":      "_post_push_strings",
        "/api/export":            "_post_export",
        "/api/save":              "_post_save",
        "/api/preview":           "_post_preview",
        "/api/collection-file":   "_post_collection_file",
        "/api/mark-example":      "_post_mark_example",
        "/api/validate-key":      "_post_validate_key",
        "/api/context":           "_post_context",
        "/api/screenshot-upload": "_post_screenshot_upload",
        "/api/translate-enabled": "_post_translate_enabled",
        "/api/lock":              "_post_lock",
        "/api/glossary":          "_post_glossary",
        "/api/verify":            "_post_verify",
        "/api/revert":            "_post_revert",
        "/api/import":            "_post_import",
        "/api/settings":          "_post_settings",
        "/api/project-config":    "_post_project_config",
        "/api/workflow":          "_post_workflow",
        "/api/workflow/cancel":   "_post_workflow_cancel",
        "/api/workflow/resume":   "_post_workflow_resume",
        "/api/workflow/copy":     "_post_workflow_copy",
        "/api/branches/track":    "_post_branches_track",
        "/api/branches/active":   "_post_branches_active",
        "/api/branches/merge":    "_post_branches_merge",
        "/api/branches/archive":  "_post_branches_archive",
        "/api/branches/unarchive": "_post_branches_unarchive",
        "/api/branches/delete":   "_post_branches_delete",
        "/api/branches/fetch":    "_post_branches_fetch",
        "/api/model-eval/run":    "_post_model_eval_run",
        "/api/model-eval/apply":  "_post_model_eval_apply",
        "/api/web-token":         "_post_web_token",
        "/api/review/tickets":    "_post_review_tickets",
        "/api/add-locale":        "_post_add_locale",
        "/api/remove-locale":     "_post_remove_locale",
        "/api/tm/import":         "_post_tm_import",
        "/api/retranslate":       "_post_retranslate",
        "/api/mark-intentional":  "_post_mark_intentional",
        "/api/reload":            "_post_reload",
        "/api/save-ui-locale":    "_post_save_ui_locale",
        "/api/resolve":           "_post_resolve",
        "/api/flag":              "_post_flag",
    }

    def do_POST(self) -> None:  # noqa: N802
        from . import timing as web_timing

        if not _host_allowed(self.headers.get("Host")):
            return self._send({"error": "host not allowed"}, 403)
        url = urlparse(self.path)
        try:
            expected = getattr(self, "session_token", "") or ""
            if expected:
                # Either the printed startup token (curl, agents) or the shell token our own page fetched.
                got = (self.headers.get("X-LLM-Token") or "").encode("utf-8")
                shell = (getattr(self, "shell_token", "") or "").encode("utf-8")
                if not (secrets.compare_digest(got, expected.encode("utf-8"))
                        or (shell and secrets.compare_digest(got, shell))):
                    return self._send({"error": "missing token"}, 403)
            origin = self.headers.get("Origin")
            if not _origin_allowed(origin):
                return self._send({"error": "origin not allowed"}, 403)
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return self._send({"error": "bad Content-Length"}, 400)
            if length < 0 or length > max_body_bytes(url.path):
                return self._send({"error": "request too large"}, 413)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send({"ok": False, "error": "body must be valid JSON"}, 400)
            if not isinstance(body, dict):
                return self._send({"ok": False, "error": "body must be a JSON object"}, 400)
            project = body.get("project", self.default_project)
            st = self._state(project)
            web_timing.reset(
                enabled=web_timing.enabled_for_request(body=body, cfg=st.cfg),
            )
            auth_path = url.path.startswith("/api/auth/")
            # Login/register may be cross-origin on loopback; every other auth
            # route (users list, approve, …) needs same-origin like catalogue POSTs.
            auth_open = url.path in ("/api/auth/login", "/api/auth/register")
            if not (auth_path and auth_open) and not _same_origin(
                origin, self.headers.get("Host"),
            ):
                if not getattr(st.cfg, "overlay_edit", False):
                    return self._send(
                        {"error": "cross-origin edit is off; set [web] overlay_edit = true"},
                        403,
                    )

            handler_name = self._AUTH_ROUTES.get(url.path)
            if handler_name is not None:
                return getattr(self, handler_name)(url, body, st, None, project)

            actor = self._actor(st.cfg)
            from .auth import locale_allowed, require_mutation
            from .post_policy import POST_OPS, body_locales, policy_for

            policy = policy_for(url.path)
            if policy in ("admin", "edit", "read"):
                denied = require_mutation(actor)
                if denied is not None:
                    return self._send(denied, 403)
                if policy == "admin" and not actor.is_admin:
                    return self._send(
                        {"ok": False, "error": "Admin required"}, 403,
                    )
                for loc in body_locales(body):
                    if not locale_allowed(actor, loc):
                        return self._send(
                            {"ok": False, "error": f"locale {loc} is not allowed for this user"},
                            403,
                        )
                op_name = POST_OPS.get(url.path)
                if op_name is not None and not actor.is_admin:
                    from .auth import require_op

                    denied = require_op(actor, op_name, cfg=st.cfg)
                    if denied is not None:
                        return self._send(denied, 403)

            # Pattern routes: path parameters, so not in the exact-match table.
            for pattern, method in self._POST_PATTERN_ROUTES:
                match = re.fullmatch(pattern, url.path)
                if match:
                    return getattr(self, method)(match, body, st, actor)
            if url.path.startswith("/api/ops/"):
                return self._post_ops(url, body, st, actor)

            handler_name = self._POST_ROUTES.get(url.path)
            if handler_name is not None:
                return getattr(self, handler_name)(url, body, st, actor, project)

            self._send({"error": "not found"}, 404)
        except ProjectAccessError as exc:
            self._send({"ok": False, "error": str(exc)}, 403)
        except ScopeError as exc:
            self._send({"ok": False, "error": str(exc)}, 400)
        except ProjectLoadError as exc:
            self._send({"ok": False, "error": str(exc), "hint": exc.hint,
                        "project": exc.project}, 409)
        except Exception as exc:
            _LOG.exception("POST %s failed", self.path)
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _post_ticket_comment(self, match, body, st, actor):
        from .review import comment_on_ticket

        result = comment_on_ticket(
            st.cfg,
            locale=str(body.get("locale") or ""),
            ticket_id=match.group(1),
            author=_session_author(actor, body.get("author")),
            body=str(body.get("body") or ""),
            resolve=bool(body.get("resolve")),
            scores=st.scores_store(),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_ticket_status(self, match, body, st, actor):
        from .review import set_ticket_status

        locale = str(body.get("locale") or "")
        if not _SAFE_COMPONENT.fullmatch(locale):
            return self._send({"ok": False, "error": "invalid locale"}, 400)
        path = st.cfg.review_root() / f"{locale}.jsonl"
        before = path.read_bytes() if path.exists() else b""
        result = set_ticket_status(
            st.cfg,
            locale=locale,
            ticket_id=match.group(1),
            status=str(body.get("status") or ""),
            assignee=body.get("assignee"),
            actor=_session_author(actor, body.get("author")) or None,
            scores=st.scores_store(),
        )
        if not result.get("ok"):
            after = path.read_bytes() if path.exists() else b""
            if after != before:
                return self._send({"ok": False, "error": "file changed on reject"}, 500)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_ops(self, url, body, st, actor):
        cmd = url.path.split("/api/ops/", 1)[1].strip("/")
        if not cmd or "/" in cmd:
            return self._send({"ok": False, "error": "invalid operation"}, 400)
        from .auth import require_op

        denied = require_op(actor, cmd, cfg=st.cfg)
        if denied is not None:
            return self._send(denied, 403)
        from .auth import resolve_locales

        raw_locales = body.get("locales")
        if isinstance(raw_locales, str):
            raw_locales = [p.strip() for p in raw_locales.split(",") if p.strip()]
        elif raw_locales is None and body.get("locale"):
            raw_locales = [body["locale"]]
        resolved, loc_err = resolve_locales(
            actor,
            list(raw_locales) if raw_locales else None,
            default_op_targets(cmd, st.cfg),
        )
        if loc_err:
            return self._send({"ok": False, "error": loc_err}, 403)
        body["locales"] = resolved or None
        if cmd in ("scan-decide", "scan_decide"):
            who = getattr(actor.user, "username", None) or actor.kind
            body["by"] = who
        cmd_key = cmd.replace("-", "_")
        if cmd_key == "validate":
            body.setdefault("detail", "summary")
            body.setdefault("findings_limit", 200)
        from .server_logic import cached_metrics, cached_places, cached_status_rows

        status_rows = None
        if cmd_key in ("guide", "status", "validate", "metrics"):
            try:
                status_rows = cached_status_rows(st)
            except Exception:
                status_rows = None
        # Default list paths: reuse AppState caches (Settings Places, Ops metrics).
        if cmd_key == "places" and str(body.get("action") or "list") == "list":
            return self._send(cached_places(st))
        if (
            cmd_key == "metrics"
            and not body.get("by")
            and not body.get("since")
            and not body.get("locale")
            and not body.get("locales")
            and not body.get("why_low")
        ):
            return self._send(cached_metrics(st))
        if bool(body.get("stream")) and is_streamable(cmd):
            return self._stream_op(
                st.cfg, cmd, body, actor_role=actor.role, catalog=st.catalog,
                status_rows=status_rows, st=st, actor_name=getattr(actor.user, "username", None),
            )
        result = dispatch_op(
            st.cfg, cmd, body, actor_role=actor.role,
            actor_name=getattr(actor.user, "username", None),
            catalog=st.catalog,
            status_rows=status_rows,
        )
        status = self._after_op(st, cmd, body, result)
        return self._send(result, status)

    def _after_op(self, st, cmd: str, body: dict, result: dict) -> int:
        """Refresh cached state after an op (both plain and streamed requests); return the HTTP status."""
        status = 200 if result.get("ok", True) and "error" not in result else 400
        if result.get("exit_code", 0) not in (0, 2):
            status = 400
        wrote = int((result.get("data") or {}).get("accepted") or 0)
        refresh_cmd = cmd.replace("-", "_") in {
            c.replace("-", "_") for c in _OPS_REFRESH_SIDECARS
        }
        # Sidecar-writing ops use their own StateStore; refresh AppState.
        # Import refreshes even when ok is false, as long as rows were written.
        if (
            not body.get("dry_run")
            and refresh_cmd
            and (
                (status == 200 and result.get("ok", True))
                or (cmd.replace("-", "_") == "import" and wrote > 0)
            )
        ):
            refresh_sidecars_from_disk(
                st,
                bust_catalog=cmd.replace("-", "_") in _OPS_BUST_CATALOG,
            )
        name = cmd.replace("-", "_")
        if result.get("ok") and not body.get("dry_run"):
            if name == "glossary_import":
                from ..projects.context import load_glossary
                st.glossary = load_glossary(st.cfg.glossary_path)
            if name == "pseudo":
                st.catalog.invalidate()
            if name == "places" and str(body.get("action") or "") in ("set", "unset"):
                with st.cache_lock:
                    st._places_cache = None
            if (name == "approach" and (body.get("set_to") or body.get("set"))) or (
                name == "engine" and str(body.get("action") or "") == "apply"
            ):
                # These ops rewrite .llm-localize.toml (W6): reload so the guide and pages see the new config.
                self._reload_config(st)
        return status

    def _reload_config(self, st) -> None:
        from ..projects.config import load_config
        from .server_logic import store_state

        path = getattr(st.cfg, "config_path", None)
        if not path:
            return
        for key, value in list(self.states.items()):
            if value is st:
                try:
                    store_state(self.states, key, build_state(load_config(path)), self.default_project)
                except Exception:  # noqa: BLE001 -- the write succeeded; a bad reload must not fail the op
                    pass
                return

    # -------------------------------------------------------------------
    # POST handlers — one per route in _POST_ROUTES
    # Signature: (self, url, body, st, actor, project)
    # -------------------------------------------------------------------





































class _LoopbackServer(ThreadingHTTPServer):
    """``SO_REUSEADDR`` on Windows lets a second server bind a port that is already in use, so two servers would
    share 8770 and answer with each other's tokens. Off there; kept elsewhere for quick restarts (TIME_WAIT)."""

    allow_reuse_address = os.name != "nt"


def _port_busy(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


class _MarketingHandler(BaseHTTPRequestHandler):
    """Read-only marketing site (ADR-45). No catalogue APIs, no token."""

    app_port: int = DEFAULT_PORT

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        from .marketing import MARKETING_ROUTES, render_public

        url = urlparse(self.path)
        static = _MARKETING_STATIC.get(url.path)
        if static is not None:
            name, ctype = static
            body = (_SHELL_STATIC_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Cache-Control", static_cache_control(url.path, url.query),
            )
            self.end_headers()
            self.wfile.write(body)
            return

        route_id = MARKETING_ROUTES.get(url.path)
        if route_id is None:
            self.send_response(404)
            err = b'{"error":"not found"}'
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        html = render_public(
            route_id, app_port=int(getattr(self, "app_port", DEFAULT_PORT)),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html)

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 1_000_000))
        except (ValueError, OSError):
            pass
        body = b'{"error":"marketing server is read-only"}'
        self.send_response(405)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(
    cfg: ProjectConfig,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    *,
    paranoid: bool = False,
    marketing_port: int | None = DEFAULT_MARKETING_PORT,
) -> int:
    if paranoid:
        cfg.allow_cloud = False
        cfg.overlay_edit = False
    if _port_busy(port):
        print(
            f"error: port {port} is already in use — an old llm-localizator web "
            f"server is probably still running.",
            file=sys.stderr,
        )
        print(
            "  Run `llm-localizator doctor` to diagnose, then stop the old "
            "process (Ctrl-C in its terminal) and retry.",
            file=sys.stderr,
        )
        return 1

    mkt_port = 0 if marketing_port in (None, 0) else int(marketing_port)
    if mkt_port and mkt_port == port:
        print(
            "error: --marketing-port must differ from --port",
            file=sys.stderr,
        )
        return 1
    if mkt_port and _port_busy(mkt_port):
        print(
            f"error: marketing port {mkt_port} is already in use.",
            file=sys.stderr,
        )
        return 1

    token = _install_session_token(cfg)
    states = _load_primary_state(cfg)
    handler = type("Handler", (_Handler,), {
        "states": states,
        "default_project": cfg.name,
        "session_token": token,
        "shell_token": secrets.token_urlsafe(32),  # CSRF token for our own page; Admin only without accounts
        "paranoid_preview": paranoid,
        "bind_port": port,
        "marketing_port": mkt_port,
    })
    marketing_server: ThreadingHTTPServer | None = None
    try:
        server = _LoopbackServer(("127.0.0.1", port), handler)
    except OSError:
        print(
            f"error: port {port} is already in use — an old llm-localizator web "
            f"server is probably still running.",
            file=sys.stderr,
        )
        print(
            "  Run `llm-localizator doctor` to diagnose, then stop the old "
            "process (Ctrl-C in its terminal) and retry.",
            file=sys.stderr,
        )
        return 1

    if mkt_port:
        mkt_handler = type("MarketingHandler", (_MarketingHandler,), {
            "app_port": port,
        })
        try:
            marketing_server = _LoopbackServer(
                ("127.0.0.1", mkt_port), mkt_handler,
            )
        except OSError:
            server.server_close()
            print(
                f"error: marketing port {mkt_port} is already in use.",
                file=sys.stderr,
            )
            return 1
        threading.Thread(
            target=marketing_server.serve_forever, daemon=True,
        ).start()

    url = f"http://127.0.0.1:{port}"
    digest = ui_digest(ui_source())

    projects_list = ", ".join(_registered_project_names(cfg.name))
    print(f"llm-localizator web v{__version__} (ui {digest}) — {cfg.name}")
    print(f"  projects: {projects_list} (others load on first select)")
    print(f"  app: {url}")
    if mkt_port:
        print(f"  marketing: http://127.0.0.1:{mkt_port}")
    print(f"  token: {token}")
    print(f"  token file: {cfg.state_root() / 'web.token'}")
    print("  Ctrl-C to stop")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        if marketing_server is not None:
            marketing_server.shutdown()
            marketing_server.server_close()
        server.server_close()
    return 0
