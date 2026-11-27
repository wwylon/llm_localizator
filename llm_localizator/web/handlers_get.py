"""GET route handlers for the local review server (one per _GET_ROUTES entry)."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path
from ..catalog import canonical_formats
from ..catalog.export_formats import render_export
from ..projects.collections import list_collection_files
from ..projects.paths import is_under_root
from .. import __version__
from ..doctor import package_info, ui_digest
from .assets import WEB_FEATURES, ui_source
from .request_guard import _same_origin
from .server_logic import (
    DEFAULT_PORT,
    _origin_allowed,
    _OVERLAY_DIR,
    _commands_manifest,
    overview_lite,
    overview_stats,
    overview,
    findings,
    _parse_finding_keys,
    messages,
    message_row,
    history_for_key,
)


_ANALYSIS_TTL_S = 300.0
_ANALYSIS_CACHE: dict[tuple, tuple[float, dict]] = {}
# One computation per cache key at a time; a refresh within this window of the
# last one is served from cache (Re-analyze double-clicks, polling tabs).
_ANALYSIS_LOCKS: OrderedDict = OrderedDict()
_ANALYSIS_LOCKS_GUARD = threading.Lock()
_ANALYSIS_REFRESH_MIN_S = 10.0
_CACHE_CAP = 16
# Shared TTL helper (Wave 2) — generation bumps clear analysis siblings.
from .cache_ttl import TtlCache as _TtlCache  # noqa: E402

_HELPER_TTL = _TtlCache(ttl_s=30.0, cap=32)


def _cache_put(cache: dict, key, value) -> None:
    """Insert and evict the oldest entries so a long-lived server stays bounded."""
    from collections import OrderedDict as _OD

    if isinstance(cache, _OD):
        cache.pop(key, None)
        cache[key] = value
        while len(cache) > _CACHE_CAP:
            cache.popitem(last=False)
        return
    cache.pop(key, None)
    cache[key] = value
    while len(cache) > _CACHE_CAP:
        cache.pop(next(iter(cache)))


def _analysis_lock(cache_key: tuple) -> threading.Lock:
    from .cache_bounds import LOCK_MAP_CAP, bounded_lock

    return bounded_lock(
        _ANALYSIS_LOCKS, cache_key, guard=_ANALYSIS_LOCKS_GUARD, cap=LOCK_MAP_CAP,
    )

def _clamp_float(raw: str, default: float, low: float, high: float) -> float:
    try:
        value = float(raw) if raw not in ("", None) else default
    except ValueError:
        return default
    return min(high, max(low, value)) if value == value else default


class GetRoutesMixin:
    def _get_projects(self, url, q, one):
        from .auth import project_allowed

        actor = self._actor()
        return self._send({
            "projects": [
                {"name": n} for n in self._project_names()
                if project_allowed(actor, n, self.default_project)
            ],
            "default": self.default_project,
        })

    def _get_ui_locales(self, url, q, one):
        locales_dir = Path(__file__).parent / "locales"
        available = sorted(
            f.stem for f in locales_dir.glob("*.json") if f.stem != "en"
        )
        return self._send({"locales": ["en"] + available})

    def _get_dashboard(self, url, q, one):
        """One-shot dashboard aggregate (Wave 3) — lite + stats + review badge."""
        from .review import review_counts

        st = self._state(one("project", self.default_project))
        if self._locale_guard([]):
            return
        allowed = self._allowed_locales(st.cfg.targets)
        lite = self._filter_locale_payload(overview_lite(st), st.cfg.targets)
        stats = self._filter_locale_payload(overview_stats(st), st.cfg.targets)
        counts = review_counts(st.cfg, allowed)
        return self._send({
            "ok": True,
            "lite": lite,
            "stats": stats,
            "review": counts,
        })

    def _get_overview(self, url, q, one):
        st = self._state(one("project", self.default_project))
        if self._locale_guard([]):
            return
        return self._send(self._filter_locale_payload(overview(st), st.cfg.targets))

    def _get_overview_lite(self, url, q, one):
        st = self._state(one("project", self.default_project))
        if self._locale_guard([]):
            return
        return self._send(self._filter_locale_payload(overview_lite(st), st.cfg.targets))

    def _get_overview_stats(self, url, q, one):
        st = self._state(one("project", self.default_project))
        if self._locale_guard([]):
            return
        return self._send(self._filter_locale_payload(overview_stats(st), st.cfg.targets))

    def _get_collections(self, url, q, one):
        from .server_logic import cached_visible_collections

        st = self._state(one("project", self.default_project))
        return self._send({
            "collections": [
                {"name": c.name, "kind": c.kind, "format": c.format}
                for c in cached_visible_collections(st)
            ],
        })

    def _get_collection_files(self, url, q, one):
        from .timing import span

        st = self._state(one("project", self.default_project))
        name = one("collection", "messages")
        try:
            with span("collection_files"):
                files = list_collection_files(
                    st.cfg, name, [one("locale", st.cfg.source_locale)],
                )
        except ValueError as exc:
            return self._send({"error": str(exc)}, 400)
        return self._send({"collection": name, "files": files})

    def _get_collection_file(self, url, q, one):
        from .document_editor import pack_collection_file

        st = self._state(one("project", self.default_project))
        name = one("collection", "")
        locale = one("locale", st.cfg.source_locale)
        rel = one("path", "")
        try:
            payload = pack_collection_file(st.cfg, name, locale, rel)
        except ValueError as exc:
            return self._send({"error": str(exc)}, 400)
        return self._send(payload)

    def _get_models(self, url, q, one):
        from .settings import fetch_ollama_tags

        st = self._state(one("project", self.default_project))
        try:
            default_model = st.cfg.model_for("default")
        except Exception:
            default_model = getattr(st.cfg, "model", "llama3.2") or "llama3.2"
        base = (st.cfg.provider.url or "http://127.0.0.1:11434").rstrip("/")
        # Shared soft cache with provider-status (same Ollama /api/tags).
        models, err = fetch_ollama_tags(base)
        payload = {"models": models}
        if err is not None:
            payload["error"] = "Ollama not running"
        return self._send({**payload, "default": default_model})

    def _get_locales(self, url, q, one):
        from ..core.locales import all_profiles

        return self._send({"locales": [
            {"code": p.code, "name": p.name, "script": p.script, "direction": p.direction}
            for p in all_profiles() if p.selectable
        ]})

    def _get_setup_state(self, url, q, one):
        cfg = self._state(one("project", self.default_project)).cfg
        try:
            model = cfg.model_for((cfg.targets or [""])[0])
        except ValueError:
            model = ""
        from ..ops.approaches import APPROACHES

        return self._send({
            "sourceLocale": cfg.source_locale,
            "targets": list(cfg.targets),
            "model": model,
            "domain": cfg.domain,
            "catalogFormat": cfg.catalog_format,
            "catalogPath": cfg.catalog_path,
            "catalogFormats": canonical_formats(),
            "providerKind": cfg.provider.kind,
            "approach": getattr(cfg, "translate_approach", None) or "",
            "approaches": [
                {"id": a.id, "title": a.title, "words": a.words, "when": a.when}
                for a in APPROACHES
            ],
        })

    def _get_messages(self, url, q, one):
        project = one("project", self.default_project)
        st = self._state(project)
        from .auth import resolve_locales

        actor = self._actor(st.cfg)
        if actor.kind == "anonymous":
            return self._send({"ok": False, "error": "authentication required"}, 401)
        raw = one("locales", "")
        requested = [l.strip() for l in raw.split(",") if l.strip()] if raw else []
        locales, err = resolve_locales(actor, requested, list(st.cfg.targets))
        if err:
            return self._send({"ok": False, "error": err}, 403)
        offset_raw = one("offset", "0")
        limit_raw = one("limit", "")
        try:
            offset = max(0, int(offset_raw or 0))
        except ValueError:
            offset = 0
        limit: int | None
        if limit_raw == "" or limit_raw is None:
            limit = 100
        else:
            try:
                limit = int(limit_raw)
            except ValueError:
                limit = 100
        include = one("include", "")
        include_findings = "findings" in {
            p.strip() for p in include.split(",") if p.strip()
        }
        sort_col = one("sort", "")
        sort_direction = one("dir", "asc")
        if sort_direction not in ("asc", "desc"):
            sort_direction = "asc"
        row_detail = one("detail", "minimal") or "minimal"
        search_mode = one("mode", "exact") or "exact"
        if search_mode not in ("exact", "contains", "fuzzy", "regexp"):
            search_mode = "exact"
        if search_mode == "contains":
            search_mode = "exact"  # substring match is the default exact path
        return self._send(messages(
            st, locales, one("namespace"),
            one("q"), one("only", "all"),
            offset=offset, limit=limit,
            include_findings=include_findings,
            sort=sort_col,
            sort_dir=sort_direction,
            detail=row_detail,
            ns_prefix=one("nsPrefix", "") or one("ns_prefix", ""),
            mode=search_mode,
        ))

    def _get_messages_row(self, url, q, one):
        project = one("project", self.default_project)
        st = self._state(project)
        from .auth import resolve_locales

        actor = self._actor(st.cfg)
        if actor.kind == "anonymous":
            return self._send({"ok": False, "error": "authentication required"}, 401)
        raw = one("locales", "")
        requested = [l.strip() for l in raw.split(",") if l.strip()] if raw else []
        locales, err = resolve_locales(actor, requested, list(st.cfg.targets))
        if err:
            return self._send({"ok": False, "error": err}, 403)
        return self._send(message_row(
            st, locales, one("namespace"), one("key"),
        ))

    def _get_findings(self, url, q, one):
        project = one("project", self.default_project)
        st = self._state(project)
        if self._locale_guard([one("locale")]):
            return
        keys_raw = one("keys", "")
        parsed_keys = _parse_finding_keys(keys_raw)
        full_scan = one("full", "") in ("1", "true", "yes")
        return self._send(findings(
            st, one("locale"), one("namespace", "__all__"),
            keys=parsed_keys,
            full=full_scan,
        ))

    def _get_export(self, url, q, one):
        st = self._state(one("project", self.default_project))
        from .auth import resolve_locales

        actor = self._actor(st.cfg)
        if actor.kind == "anonymous":
            return self._send({"ok": False, "error": "authentication required"}, 401)
        raw = one("locales", "")
        requested = (
            [l.strip() for l in raw.split(",") if l.strip()]
            if raw else list(st.cfg.targets)
        )
        locs, err = resolve_locales(actor, requested, list(st.cfg.targets))
        if err:
            return self._send({"ok": False, "error": err}, 403)
        if not locs:
            return self._send({"ok": False, "error": "no locales allowed"}, 403)
        ns_multi = [n.strip() for n in one("namespaces", "").split(",") if n.strip()]
        ns = one("namespace", "").strip() or None
        namespaces = ns_multi or ([ns] if ns else None)
        fmt = one("format", "csv").lower()
        flag = lambda name: one(name, "") in ("1", "true", "yes")  # noqa: E731
        try:
            # Same options as `llm-localizator export` (CLI/web parity).
            body, ctype, filename, _report = render_export(
                st.cfg, st.catalog, locales=locs, namespaces=namespaces,
                fmt=fmt, layout=one("layout", "single") or "single",
                only=one("only", "all") or "all", screenshots=flag("screenshots"),
                file_count=one("files", "1") or "1",
                xliff_version=one("xliff_version", "1.2") or "1.2",
                bom=flag("bom"), approved_only=flag("approved_only"),
            )
        except ValueError as exc:
            return self._send({"error": str(exc)}, 400)
        return self._send(body, content_type=ctype, filename=filename)

    def _get_screenshot(self, url, q, one):
        st = self._state(one("project", self.default_project))
        rel = one("file") or one("screen")
        if not st.cfg.context_dir or not rel:
            return self._send({"error": "not found"}, 404)
        path = (st.cfg.context_dir / rel).resolve()
        if not is_under_root(path, st.cfg.context_dir):
            return self._send({"error": "forbidden"}, 403)
        if not path.is_file():
            return self._send({"error": "not found"}, 404)
        try:
            size = path.stat().st_size
        except OSError:
            return self._send({"error": "not found"}, 404)
        # Cap in-memory screenshot responses (consumer-controlled files).
        if size > 8 * 1024 * 1024:
            return self._send({"error": "screenshot too large"}, 413)
        data = path.read_bytes()
        ext = path.suffix.lower()
        ctype = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(ext, "application/octet-stream")
        return self._send(
            data,
            content_type=ctype,
            extra_headers={"X-Content-Type-Options": "nosniff"},
        )

    def _get_commands(self, url, q, one):
        return self._send(_commands_manifest())

    def _get_version(self, url, q, one):
        pinfo = package_info()
        return self._send({
            "version": __version__,
            "uiDigest": ui_digest(ui_source()),
            "packagePath": pinfo["packagePath"],
            "features": list(WEB_FEATURES),
        })

    def _get_history(self, url, q, one):
        st = self._state(one("project", self.default_project))
        locale, namespace, key = one("locale"), one("namespace"), one("key")
        if self._locale_guard([locale]):
            return
        if namespace == "__all__":
            return self._send(
                {"error": "select a single namespace, not all namespaces"}, 400,
            )
        try:
            return self._send(history_for_key(st, locale, namespace, key))
        except ValueError as exc:
            return self._send({"error": str(exc)}, 400)

    def _get_overlay_js(self, url, q, one):
        body = (_OVERLAY_DIR / "overlay.js").read_bytes()
        return self._send(body, content_type="application/javascript; charset=utf-8")

    def _get_overlay_css(self, url, q, one):
        body = (_OVERLAY_DIR / "overlay.css").read_bytes()
        return self._send(body, content_type="text/css; charset=utf-8")

    def _get_tm_concordance(self, url, q, one):
        from ..ops.tm import op_concordance
        from ..ops.types import ConcordanceRequest

        st = self._state(one("project", self.default_project))
        if self._locale_guard([one("locale", "")]):
            return
        limit = 20
        try:
            limit = int(one("limit", "20") or "20")
        except ValueError:
            limit = 20
        limit = min(max(limit, 1), 100)
        result = op_concordance(st.cfg, ConcordanceRequest(
            locale=one("locale", ""),
            query=one("query", ""),
            source=one("source", "1") not in {"0", "false", "no"},
            target=one("target", "1") not in {"0", "false", "no"},
            limit=limit,
            namespace=one("namespace", "") or None,
            key=one("key", "") or None,
            mode="fuzzy" if one("mode", "") == "fuzzy" else "substring",
            min_similarity=_clamp_float(one("min_similarity", ""), 0.55, 0.1, 1.0),
        ))
        return self._send(result.to_dict(), 200 if result.ok else 400)

    def _get_tm_leverage(self, url, q, one):
        from .server_logic import cached_leverage

        st = self._state(one("project", self.default_project))
        return self._send(cached_leverage(st))

    def _get_tm_browse(self, url, q, one):
        from ..ops.tm import browse_payload

        st = self._state(one("project", self.default_project))
        if self._locale_guard([one("locale", "") or (st.cfg.targets[0] if st.cfg.targets else "")]):
            return
        limit = 250
        try:
            limit = int(one("limit", "250") or "250")
        except ValueError:
            limit = 250
        return self._send(browse_payload(
            st.cfg,
            one("locale", st.cfg.targets[0] if st.cfg.targets else ""),
            provider=one("provider", ""),
            text=one("q", ""),
            limit=min(limit, 250),
        ))

    def _get_tm_export(self, url, q, one):
        from ..catalog.tm import TranslationMemory
        from ..catalog.tmx import export_tmx

        st = self._state(one("project", self.default_project))
        locale = one("locale", st.cfg.targets[0] if st.cfg.targets else "")
        if self._locale_guard([locale]):
            return
        xml = export_tmx(st.cfg.open_tm(), locale, st.cfg.source_locale)
        return self._send(
            xml.encode("utf-8"),
            content_type="application/xml; charset=utf-8",
            filename=f"{locale}.tmx",
        )

    def _report_dir(self, st, raw: str, kind: str = "hardcoded"):
        """A report directory under the project root or the engine data root, else None.

        Without ``dir`` it is where the op writes by default: ``<data root>/reports/<kind>`` (ADR-112).
        """
        data_root = Path(st.cfg.data_root())
        sub = "backlog" if kind in ("backlog", "agent-backlog") else "hardcoded"
        path = Path(raw) if raw else data_root / "reports" / sub
        if not path.is_absolute():
            path = st.cfg.root / path
        inside = is_under_root(path, st.cfg.root) or is_under_root(path, data_root)
        return path if inside and path.is_dir() else None

    def _get_report_parts(self, url, q, one):
        st = self._state(one("project", self.default_project))
        folder = self._report_dir(st, one("dir", ""), one("kind", "hardcoded"))
        if folder is None:
            return self._send({"error": "report directory not found"}, 404)
        parts = []
        for index in ("index.json", "backlog-index.json"):
            try:
                data = json.loads((folder / index).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for part in data.get("parts", []):
                name = part.get("file") or part.get("name")
                if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                    continue
                candidate = (folder / name).resolve()
                if not is_under_root(candidate, folder) or not candidate.is_file():
                    continue
                parts.append({"name": name, "size": candidate.stat().st_size})
        return self._send({"dir": str(folder), "parts": parts})

    def _get_report_part(self, url, q, one):
        import re

        st = self._state(one("project", self.default_project))
        folder = self._report_dir(st, one("dir", ""), one("kind", "hardcoded"))
        name = one("name", "")
        if folder is None or not re.fullmatch(r"[\w.-]+\.(md|json)", name) or not (folder / name).is_file():
            return self._send({"error": "report part not found"}, 404)
        path = folder / name
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                return self._send({"error": "report part too large"}, 413)
        except OSError:
            return self._send({"error": "report part not found"}, 404)
        return self._send(
            path.read_bytes(),
            content_type="text/plain; charset=utf-8",
            filename=name,
        )

    def _get_glossary(self, url, q, one):
        from ..projects.glossary_edit import glossary_payload

        st = self._state(one("project", self.default_project))
        payload = glossary_payload(st.cfg)
        return self._send(payload, 200 if payload.get("ok") else 400)

    def _get_bundle(self, url, q, one):
        from .bundle import bundle_payload, etag_matches

        origin = self.headers.get("Origin")
        if origin and not _origin_allowed(origin):
            return self._send({"error": "origin not allowed"}, 403)
        st = self._state(one("project", self.default_project))
        if self._locale_guard([one("locale", "")], allow_anonymous=True):
            return
        payload = bundle_payload(
            st.cfg,
            locale=one("locale", ""),
            namespace=one("namespace", "") or None,
        )
        if not payload.get("ok"):
            return self._send(payload, 400)
        etag = str(payload.get("etag") or "")
        inm = self.headers.get("If-None-Match")
        if etag_matches(inm, etag):
            return self._send(
                None, 304,
                extra_headers={"ETag": f'"{etag}"'},
            )
        return self._send(
            payload, 200,
            extra_headers={"ETag": f'"{etag}"'},
        )

    def _get_bootstrap_token(self, url, q, one):
        """Return the startup token for same-origin loopback shell boot only.

        The HTML shell no longer inlines ``window.__LLM_TOKEN`` (View Source /
        scraper hardening). Curl keeps using the printed token / ``web.token``.
        """
        host = (self.client_address[0] if self.client_address else "") or ""
        if host not in ("127.0.0.1", "::1", "localhost"):
            return self._send({"ok": False, "error": "loopback only"}, 403)
        origin = (self.headers.get("Origin") or "").strip()
        # Exact loopback origin on this server's own port: another local app must not read the token.
        if origin and not (_origin_allowed(origin) and _same_origin(origin, self.headers.get("Host"))):
            return self._send({"ok": False, "error": "loopback only"}, 403)
        # The shell token, not the printed startup token: it proves same-origin and grants no role while accounts
        # exist (web/auth.actor_from_request). Servers built without one (tests) fall back to the startup token.
        token = getattr(self, "shell_token", "") or getattr(self, "session_token", "") or ""
        return self._send({"ok": True, "token": token})

    def _get_auth_me(self, url, q, one):
        from .auth import public_me

        return self._send(public_me(self._actor()))

    def _get_settings(self, url, q, one):
        from .settings import settings_view

        st = self._state(one("project", self.default_project))
        port = int(getattr(self, "bind_port", DEFAULT_PORT))
        coverage: dict[str, float] = {}
        try:
            stats = overview_stats(st)
            for row in stats.get("locales") or []:
                loc = row.get("locale")
                if loc is not None:
                    coverage[str(loc)] = float(row.get("coverage") or 0)
        except Exception:
            coverage = {}
        payload = settings_view(st.cfg, port=port, coverage=coverage)
        from ..ops.permissions import OPERATIONS, ROLES, role_allowed

        matrix = {}
        for op in OPERATIONS:
            matrix[op] = [
                role_allowed(role, op, cfg=st.cfg) for role in ROLES
            ]
        payload["permissions"] = {
            "roles": list(ROLES),
            "operations": list(OPERATIONS),
            "matrix": matrix,
        }
        return self._send(payload)

    def _get_provider_status(self, url, q, one):
        from .settings import provider_status_payload

        st = self._state(one("project", self.default_project))
        return self._send(provider_status_payload(st.cfg))

    def _get_project_config(self, url, q, one):
        from .project_config import project_config_view

        st = self._state(one("project", self.default_project))
        return self._send(project_config_view(st.cfg))

    def _get_model_eval(self, url, q, one):
        from .model_eval import model_eval_view, report_text

        report = one("report", "")
        if report:
            result = report_text(report)
            return self._send(result, 200 if result.get("ok") else 400)
        st = self._state(one("project", self.default_project))
        return self._send(model_eval_view(st.cfg))

    def _get_workflow(self, url, q, one):
        from .workflow_config import get_named_workflow, workflow_view

        st = self._state(one("project", self.default_project))
        name = one("name", "")
        if name:
            return self._send(get_named_workflow(st.cfg, name))
        return self._send(workflow_view(st.cfg))

    def _get_workflow_summary(self, url, q, one):
        from .workflow_config import workflow_summary

        st = self._state(one("project", self.default_project))
        return self._send(workflow_summary(st.cfg))

    def _get_workflow_run(self, url, q, one):
        # Read-only: advancing a run is a side effect and lives behind POST
        # /api/workflow/resume so a cross-site GET cannot start work.
        from ..ops.workflow_run import describe_run, load_run

        st = self._state(one("project", self.default_project))
        rec = load_run(st.cfg, one("id", ""))
        if rec is None:
            return self._send({"ok": False, "error": "unknown workflow run"}, 404)
        return self._send({"ok": True, "run": describe_run(rec), "summary": ""})

    def _get_branches(self, url, q, one):
        from .server_logic import cached_branches
        from .timing import span

        st = self._state(one("project", self.default_project))
        with span("branches"):
            return self._send(cached_branches(st))

    def _get_branches_sync(self, url, q, one):
        from ..projects.branches import sync_from_git

        st = self._state(one("project", self.default_project))
        return self._send(sync_from_git(st.cfg))

    def _get_branches_merge_preview(self, url, q, one):
        from ..projects.branches import merge_preview

        st = self._state(one("project", self.default_project))
        return self._send(merge_preview(st.cfg, one("branch", "")))

    def _get_branches_diff(self, url, q, one):
        from ..projects.branches import diff_payload

        st = self._state(one("project", self.default_project))
        return self._send(diff_payload(st.cfg, one("branch", "")))

    def _get_usage(self, url, q, one):
        from ..ops.console import usage_payload
        from .server_logic import cached_status_rows
        from .timing import span

        st = self._state(one("project", self.default_project))
        if self._locale_guard([]):
            return
        if one("runs_only", "") in ("1", "true"):
            with span("usage_runs"):
                return self._send(usage_payload(st.cfg, runs_only=True))
        period = self._usage_period(one)
        with st.cache_lock:
            hit = (st._usage_cache or {}).get(period)
        if hit is not None:
            return self._send(self._filter_locale_payload(hit, st.cfg.targets))
        with span("usage"):
            payload = usage_payload(
                st.cfg, period, catalog=st.catalog, status_rows=cached_status_rows(st),
            )
        with st.cache_lock:
            st._usage_cache[period] = payload
        return self._send(self._filter_locale_payload(payload, st.cfg.targets))

    def _usage_period(self, one) -> str:
        from ..ops.console import USAGE_PERIODS

        period = one("period", "month")
        return period if period in USAGE_PERIODS else "month"

    def _get_usage_export(self, url, q, one):
        from ..ops.console import usage_export_csv

        st = self._state(one("project", self.default_project))
        period = self._usage_period(one)
        name = str(one("project", self.default_project) or "project")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return self._send(
            usage_export_csv(st.cfg, period).encode("utf-8"),
            content_type="text/csv; charset=utf-8",
            filename=f"usage-{safe}-{period}.csv",
        )

    def _get_progress(self, url, q, one):
        from ..ops.console import progress_payload
        from .server_logic import cached_status_rows
        from .timing import span

        st = self._state(one("project", self.default_project))
        if self._locale_guard([]):
            return
        with st.cache_lock:
            hit = st._progress_cache
        if hit is not None:
            return self._send(self._filter_locale_payload(hit, st.cfg.targets))
        with span("progress"):
            payload = progress_payload(
                st.cfg, catalog=st.catalog, status_rows=cached_status_rows(st),
            )
        with st.cache_lock:
            st._progress_cache = payload
        return self._send(self._filter_locale_payload(payload, st.cfg.targets))

    def _get_scan_status(self, url, q, one):
        from ..ops.agent_hardcoded import scan_cache_status
        from ..ops.permissions import role_allowed

        st = self._state(one("project", self.default_project))
        actor = self._actor(st.cfg)
        if actor.kind == "anonymous" or (
            actor.kind != "token_admin" and not role_allowed(actor.role, "agent-hardcoded", cfg=st.cfg)
        ):
            return self._send({"ok": False, "error": "Not allowed"}, 403)
        return self._send({"ok": True, **scan_cache_status(st.cfg, max_age=3.0)})   # dashboard poll (M4)

    def _get_scan_hits(self, url, q, one):
        """Hits of the stored hardcoded-string scan with decision ids (W5). Never scans."""
        from ..ops.agent_hardcoded import cached_hit_rows, scan_cache_status
        from ..ops.permissions import role_allowed

        st = self._state(one("project", self.default_project))
        actor = self._actor(st.cfg)
        if actor.kind == "anonymous" or (
            actor.kind != "token_admin" and not role_allowed(actor.role, "agent-hardcoded", cfg=st.cfg)
        ):
            return self._send({"ok": False, "error": "Not allowed"}, 403)
        status = scan_cache_status(st.cfg, max_age=3.0)
        try:
            offset = int(one("offset", "0") or 0)
        except ValueError:
            offset = 0
        conf = one("confidence", "") or None
        lim_raw = one("limit", "")
        kwargs = {"offset": offset, "confidence": conf}
        if lim_raw == "all":
            kwargs["limit"] = None
        elif lim_raw:
            try:
                kwargs["limit"] = int(lim_raw)
            except ValueError:
                pass  # keep default page size
        rows = cached_hit_rows(st.cfg, **kwargs)
        return self._send({"ok": True, **rows, "stale": status.get("stale", True),
                           "counts": status.get("counts", {})})

    def _get_queue(self, url, q, one):
        """Blueprint tasks and their taskqueue status (W3). Read-only: the DB opens with mode=ro."""
        from ..ops.permissions import ROLE_ADMIN, ROLE_DEVELOPER
        from ..ops.queue import queue_payload

        st = self._state(one("project", self.default_project))
        actor = self._actor(st.cfg)
        if actor.kind == "anonymous":
            return self._send({"ok": False, "error": "Not allowed"}, 403)
        if actor.kind != "token_admin" and actor.role not in (ROLE_ADMIN, ROLE_DEVELOPER):
            return self._send({"ok": False, "error": "Not allowed"}, 403)
        return self._send(queue_payload(st.cfg))

    def _get_status(self, url, q, one):
        from ..ops.status import leverage_line, op_status
        from ..ops.types import StatusRequest
        from .server_logic import cached_screen_status, cached_status_rows

        st = self._state(one("project", self.default_project))
        if one("group_by", "") == "screen":
            payload = cached_screen_status(st)
            return self._send(payload, 200 if payload.get("ok", True) else 400)
        if one("missing", "") in ("1", "true"):
            result = op_status(
                st.cfg, StatusRequest(missing=True), catalog=st.catalog,
            )
            return self._send(result.to_dict(), 200 if result.ok else 400)
        # Plain coverage: reuse the shared collect() snapshot (Wave 1).
        from dataclasses import asdict

        if self._locale_guard([]):
            return
        allowed = set(self._allowed_locales(st.cfg.targets))
        rows = [r for r in cached_status_rows(st) if r.locale in allowed]
        lines = []
        for r in rows:
            line = (
                f"{r.locale}{' (frozen)' if r.frozen else ''}: "
                f"{r.coverage:.1%} ({r.translated} done, {r.stale} stale, {r.missing} missing)"
            )
            if r.providers:
                prov = ", ".join(f"{k}={v}" for k, v in r.providers.items())
                line += f"  [{prov}]"
            lines.append(line)
            if r.models:
                models = ", ".join(f"{k}={v}" for k, v in r.models.items())
                lines.append(f"  models: {models}")
            lines.append(leverage_line(r))
        return self._send({
            "ok": True,
            "exit_code": 0,
            "command": "status",
            "summary": f"{len(rows)} locale(s)",
            "lines": lines,
            "data": {
                "project": st.cfg.name,
                "locales": [
                    {
                        **{
                            k: v for k, v in asdict(r).items()
                            if k not in ("stage_days", "source_days")
                        },
                        "coverage": r.coverage,
                    }
                    for r in rows
                ],
            },
        })

    def _get_metrics(self, url, q, one):
        from ..ops.metrics import op_metrics
        from ..ops.types import MetricsRequest
        from .server_logic import cached_metrics
        from .timing import span

        st = self._state(one("project", self.default_project))
        if self._actor(st.cfg).kind == "anonymous":
            return self._send({"ok": False, "error": "Sign in required"}, 403)
        by = one("by", "") or None
        if by:
            from ..ops.permissions import ROLE_ADMIN, ROLE_SUPERVISOR

            actor = self._actor(st.cfg)
            if not actor.is_admin and actor.role not in {ROLE_ADMIN, ROLE_SUPERVISOR}:
                return self._send({"ok": False, "error": "Not allowed"}, 403)
        since = one("since", "") or None
        locale = one("locale", "") or None
        if locale and self._locale_guard([locale]):
            return
        why_low = one("why_low", "") in ("1", "true")
        # Default dashboard metrics (no by/since/locale/why_low) share a cache.
        if not by and not since and not locale and not why_low:
            with span("metrics"):
                return self._send(self._filter_locale_payload(cached_metrics(st), st.cfg.targets))
        result = op_metrics(
            st.cfg,
            MetricsRequest(by=by, since=since, locale=locale, why_low=why_low),
            catalog=st.catalog,
        )
        if by and result.ok and one("format", "") == "csv":
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(one("project", self.default_project) or "project"))
            return self._send(
                result.data["csv"].encode("utf-8"),
                content_type="text/csv; charset=utf-8",
                filename=f"activity-{safe}-{by.replace('+', '-')}.csv",
            )
        return self._send(result.to_dict(), 200 if result.ok else 400)

    def _get_translator_activity(self, url, q, one):
        from ..ops.permissions import ROLE_ADMIN, ROLE_SUPERVISOR
        from ..catalog.translator_activity import summarize_activity

        st = self._state(one("project", self.default_project))
        actor = self._actor(st.cfg)
        if actor.kind == "anonymous" or (
            not actor.is_admin
            and actor.role not in {ROLE_ADMIN, ROLE_SUPERVISOR}
        ):
            return self._send(
                {"ok": False, "error": "Admin or Supervisor required"}, 403,
            )
        try:
            limit = int(one("limit", "100") or "100")
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 1000))
        user_id = one("user_id", "") or None
        payload = summarize_activity(
            st.cfg.state_root(),
            user_id=user_id,
            limit=limit,
        )
        return self._send(payload)

    def _get_analysis(self, url, q, one):
        from ..ops.console import analysis_payload

        st = self._state(one("project", self.default_project))
        locale = one("locale", "")
        if not locale and st.cfg.targets:
            locale = st.cfg.targets[0]
        if self._locale_guard([locale]):
            return
        payload = analysis_payload(st.cfg, locale)
        return self._send(payload, 200 if payload.get("ok") else 400)

    def _get_analysis_report(self, url, q, one):
        from ..ops.console import analysis_report
        from .timing import span

        from .server_logic import cached_analysis_due

        st = self._state(one("project", self.default_project))
        if self._locale_guard([]):
            return
        namespace = one("namespace", "") or None
        locales = self._allowed_locales(st.cfg.targets)
        # Phase-1 (bands=0): gaps/counts/estimates without TM.
        # Phase-2 / default: exact TM hits (near/fuzzy is opt-in via fuzzy=1 —
        # full near over large due sets routinely exceeds 10s).
        want_bands = one("bands", "1") not in ("0", "false", "no")
        want_fuzzy = one("fuzzy", "") in ("1", "true", "yes")
        cache_key = (
            str(st.cfg.root), namespace, tuple(locales), want_bands, want_fuzzy,
        )
        refresh = bool(one("refresh", ""))
        lock = _analysis_lock(cache_key)
        with lock:
            hit = _ANALYSIS_CACHE.get(cache_key)
            age = time.monotonic() - hit[0] if hit else None
            fresh = age is not None and age < _ANALYSIS_TTL_S
            if fresh and (not refresh or age < _ANALYSIS_REFRESH_MIN_S):
                payload = hit[1]
            else:
                if refresh:
                    with st.cache_lock:
                        st._analysis_due_cache = None
                span_name = (
                    "analysis_fuzzy" if want_fuzzy
                    else ("analysis_bands" if want_bands else "analysis_gaps")
                )
                with span(span_name):
                    due = cached_analysis_due(
                        st, namespace=namespace, locales=locales,
                    )
                    payload = analysis_report(
                        st.cfg,
                        namespace=namespace,
                        locales=locales,
                        catalog=st.catalog,
                        bands=want_bands,
                        fuzzy=want_fuzzy,
                        due=due,
                        state=st.store,
                    )
                if payload.get("ok"):
                    _cache_put(_ANALYSIS_CACHE, cache_key, (time.monotonic(), payload))
        return self._send(payload, 200 if payload.get("ok") else 400)

    def _get_review_tickets(self, url, q, one):
        from .review import list_review_tickets
        from .timing import span

        st = self._state(one("project", self.default_project))
        locale = one("locale", "")
        if not locale:
            return self._send({"ok": False, "error": "locale is required"}, 400)
        if self._locale_guard([locale]):
            return
        status = one("status", "") or None
        ns = one("namespace", "")
        key = one("key", "")
        with span("review_tickets"):
            payload = list_review_tickets(
                st.cfg,
                locale=locale,
                status=status,
                namespace=ns or None,
                key=key or None,
                scores=st.scores_store(),
            )
        return self._send(payload, 200 if payload.get("ok") else 400)

    def _get_review_counts(self, url, q, one):
        from .auth import locale_allowed
        from .review import review_counts

        if self._locale_guard([]):
            return
        st = self._state(one("project", self.default_project))
        actor = self._actor()
        locales = [
            loc for loc in (st.cfg.targets or [])
            if locale_allowed(actor, str(loc))
        ]
        return self._send(review_counts(st.cfg, locales))

    def _get_translator_lookup(self, url, q, one):
        from .translator import translator_lookup

        st = self._state(one("project", self.default_project))
        if self._locale_guard([one("locale")], allow_anonymous=True):
            return
        try:
            return self._send(translator_lookup(
                st, one("locale"), one("namespace"), one("key"),
            ))
        except ValueError as exc:
            return self._send({"ok": False, "error": str(exc)}, 400)

    def _get_translator_bundle(self, url, q, one):
        from .translator import translator_bundle, translator_bundle_web_ui

        bundle_mode = one("mode", "project")
        locale = one("locale", "en")
        if self._locale_guard([locale], allow_anonymous=True):
            return
        st = self._state(one("project", self.default_project))
        try:
            if bundle_mode == "web-ui":
                payload = translator_bundle_web_ui(locale, state_root=st.cfg.state_root())
            else:
                payload = translator_bundle(st, locale)
        except ValueError as exc:
            return self._send({"ok": False, "error": str(exc)}, 400)
        return self._send(payload)

    def _get_translator_config(self, url, q, one):
        from .translator import translator_config, translator_config_web_ui

        if one("mode", "project") == "web-ui":
            st = self._state(one("project", self.default_project))
            return self._send(
                translator_config_web_ui(state_root=st.cfg.state_root())
            )
        st = self._state(one("project", self.default_project))
        return self._send(translator_config(st))
