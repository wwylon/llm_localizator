"""A local web interface for inspecting and editing translations.

The CLI answers "is anything wrong?" well. It answers "what does this actually
say, and is that right?" badly -- you cannot read a catalogue in a terminal,
and a validation finding is far more useful next to the string it is about.

    llm-localizator web bridge          # http://127.0.0.1:8770

All registered projects are available via a project switcher -- no restart
needed to compare bridge vs taskqueue. Deliberately local-only: binds
127.0.0.1. POSTs need the session token printed at startup (ADR-33).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import functools
import os
import re
import secrets
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..catalog import (
    Catalog, HistoryStore, ScoreStore, StateStore, catalog_for,
    needs_translation,
)
from ..catalog.io import atomic_write_text
from ..catalog.mutation_lock import project_mutation_lock
from ..projects.collections import (
    visible_collections,
)
from ..catalog.state import now_iso
from ..core.standards import get_standard
from ..core.validate import validate_translation_detailed
from ..pipeline.validate import run_validation
from ..pipeline.recording import record_candidate
from ..core.quality import score_translation
from ..projects import ContextNotes, ProjectConfig, load_glossary, load_registry
from ..projects.context import write_context_entry
from ..ops import build_commands_manifest
from ..cli.main import build_parser
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
    "build_state", "messages", "message_row", "findings", "overview",
    "overview_lite", "overview_stats", "save",
    "mark_example", "history_for_key", "verify_key", "validate_key",
    "save_context", "set_translate_enabled", "revert_key", "invalidate_caches",
    "refresh_sidecars_from_disk",
    "invalidate_caches_after_save", "patch_caches_after_save",
]


class ProjectAccessError(PermissionError):
    """Session user may not switch to the requested catalogue project."""


class ProjectLoadError(ValueError):
    """A registered project cannot be opened (missing or invalid config).

    ``hint`` tells the operator what to do next; the web layer returns it
    with a 409 instead of a bare 500.
    """

    def __init__(self, project: str, cause: Exception, config_path=None):
        self.project = project
        self.config_path = str(config_path) if config_path else ""
        self.hint = self._hint(cause)
        super().__init__(f"failed to load project {project!r}: {cause}")

    def _hint(self, cause: Exception) -> str:
        from ..projects.registry import registry_path

        where = self.config_path or "the project folder"
        if "no config file" in str(cause):
            return (
                f"Create {where}: run `llm-localizator init` in that project's "
                f"folder (or `llm-localizator guide`), then reload. If the project "
                f"was moved or deleted, fix or remove the '{self.project}' "
                f"entry in {registry_path()}."
            )
        return (
            f"Fix the problem in {where} (run `llm-localizator validate` from "
            f"that folder to see it), then reload."
        )


DEFAULT_PORT = 8770
DEFAULT_MARKETING_PORT = 8760


_MARKETING_STATIC = {
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/fonts/Barlow-Regular.woff2": ("fonts/Barlow-Regular.woff2", "font/woff2"),
    "/static/fonts/Barlow-SemiBold.woff2": ("fonts/Barlow-SemiBold.woff2", "font/woff2"),
    "/static/fonts/BarlowCondensed-SemiBold.woff2": (
        "fonts/BarlowCondensed-SemiBold.woff2", "font/woff2",
    ),
}
_WRITE_LOCK = threading.RLock()
_STATES_LOCK = threading.Lock()


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# Nested catalogue namespaces use ``admin/users`` (slash segments).
_SAFE_NAMESPACE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$"
)


class ScopeError(ValueError):
    """Request-controlled locale/namespace failed validation (HTTP 400)."""


def _validate_scope(
    st: AppState, locale: str, namespace: str, *,
    write: bool = False, allow_empty_namespace: bool = False,
) -> None:
    """Reject request-controlled path components before catalog access."""
    if not isinstance(locale, str) or not _SAFE_COMPONENT.fullmatch(locale):
        raise ScopeError("invalid locale")
    if write and namespace == "__all__":
        raise ScopeError("cannot write with namespace='__all__'")
    if not isinstance(namespace, str) or (
        namespace and namespace != "__all__" and not _SAFE_NAMESPACE.fullmatch(namespace)
    ):
        raise ScopeError("invalid namespace")
    if write and not namespace and not allow_empty_namespace:
        raise ScopeError("namespace is required")
    if write and locale not in st.cfg.targets:
        raise ScopeError(f"{locale!r} is not a configured target locale")
    if namespace and namespace != "__all__" and namespace not in st.namespaces():
        raise ScopeError(f"{namespace!r} is not a configured namespace")


def _session_author(actor, claimed) -> str:
    """Review author: the signed-in username wins over anything in the body."""
    user = getattr(actor, "user", None)
    if getattr(actor, "kind", "") == "user" and user is not None:
        return str(user.username)
    return str(claimed or "")


from .request_guard import (  # noqa: F401  (re-exported)
    SECURITY_HEADERS,
    max_body_bytes,
    _cors_origin,
    _host_allowed,
    _install_session_token,
    _origin_allowed,
    _safe_filename,
    _same_origin,
    rotate_web_token,
)

_SCREEN_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


_OVERLAY_DIR = Path(__file__).parent / "overlay"
_SHELL_STATIC_DIR = Path(__file__).parent / "static"
_SHELL_STATIC = {
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/shell.js": ("shell.js", "application/javascript; charset=utf-8"),
    "/static/ui-locale.js": ("ui-locale.js", "application/javascript; charset=utf-8"),
    "/static/api.js": ("api.js", "application/javascript; charset=utf-8"),
    "/static/request-health.js": ("request-health.js", "application/javascript; charset=utf-8"),
    "/static/a11y.js": ("a11y.js", "application/javascript; charset=utf-8"),
    "/static/appearance.js": ("appearance.js", "application/javascript; charset=utf-8"),
    "/static/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8"),
    "/static/placeholders.js": ("placeholders.js", "application/javascript; charset=utf-8"),
    "/static/editor-memory.js": ("editor-memory.js", "application/javascript; charset=utf-8"),
    "/static/editor.js": ("editor.js", "application/javascript; charset=utf-8"),
    "/static/ops.js": ("ops.js", "application/javascript; charset=utf-8"),
    "/static/tm.js": ("tm.js", "application/javascript; charset=utf-8"),
    "/static/glossary.js": ("glossary.js", "application/javascript; charset=utf-8"),
    "/static/review.js": ("review.js", "application/javascript; charset=utf-8"),
    "/static/operations.js": ("operations.js", "application/javascript; charset=utf-8"),
    "/static/settings.js": ("settings.js", "application/javascript; charset=utf-8"),
    "/static/analysis.js": ("analysis.js", "application/javascript; charset=utf-8"),
    "/static/usage.js": ("usage.js", "application/javascript; charset=utf-8"),
    "/static/progress.js": ("progress.js", "application/javascript; charset=utf-8"),
    "/static/project-config.js": ("project-config.js", "application/javascript; charset=utf-8"),
    "/static/model-eval.js": ("model-eval.js", "application/javascript; charset=utf-8"),
    "/static/auth.js": ("auth.js", "application/javascript; charset=utf-8"),
    "/static/setup.js": ("setup.js", "application/javascript; charset=utf-8"),
    "/static/help.js": ("help.js", "application/javascript; charset=utf-8"),
    "/static/users.js": ("users.js", "application/javascript; charset=utf-8"),
    "/static/translator-activity.js": (
        "translator-activity.js", "application/javascript; charset=utf-8",
    ),
    "/static/workflow.js": ("workflow.js", "application/javascript; charset=utf-8"),
    "/static/branches.js": ("branches.js", "application/javascript; charset=utf-8"),
    "/static/queue.js": ("queue.js", "application/javascript; charset=utf-8"),
    "/static/hardcoded.js": ("hardcoded.js", "application/javascript; charset=utf-8"),
    "/static/fonts/Barlow-Regular.woff2": ("fonts/Barlow-Regular.woff2", "font/woff2"),
    "/static/fonts/Barlow-SemiBold.woff2": ("fonts/Barlow-SemiBold.woff2", "font/woff2"),
    "/static/fonts/BarlowCondensed-SemiBold.woff2": (
        "fonts/BarlowCondensed-SemiBold.woff2", "font/woff2",
    ),
}


@dataclass
class AppState:
    cfg: ProjectConfig
    catalog: Catalog
    store: StateStore | None
    notes: ContextNotes
    glossary: dict
    scores: ScoreStore | None = None
    history: HistoryStore | None = None
    _overview_cache: dict | None = None
    _overview_stats_cache: dict | None = None
    _findings_cache: OrderedDict[tuple[str, str], dict[str, list[str]]] | None = None
    _message_index_cache: OrderedDict[tuple[tuple[str, ...], str], MessageIndex] | None = None
    _source_total_cache: tuple[int, dict[str, int]] | None = None
    _resolve_by_target_cache: dict[str, dict[str, list[dict]]] | None = None
    # Shared collect()/progress/usage caches (Wave 1–2). Cleared with overview.
    _status_rows_cache: list | None = None
    _progress_cache: dict | None = None
    _usage_cache: dict = field(default_factory=dict)
    _review_queue: object | None = None
    _visible_collections_cache: list | None = None
    _leverage_cache: dict | None = None
    _screen_status_cache: dict | None = None
    # Analysis due sources: { (namespace|None, locales_tuple): {locale: [source]} }
    _analysis_due_cache: dict | None = None
    _branches_cache: dict | None = None
    _metrics_cache: dict | None = None
    _places_cache: dict | None = None
    #: Request threads share the caches above; every read-modify-write holds this.
    cache_lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    # Single-flight for the dashboard stats: concurrent first loads wait for
    # one computation instead of each walking every catalogue.
    stats_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    analysis_due_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False,
    )
    collect_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False,
    )
    screen_status_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False,
    )
    metrics_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False,
    )
    places_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False,
    )

    def scores_store(self) -> "ScoreStore":
        if self.scores is None:
            self.scores = ScoreStore(self.cfg.scores_root())
        return self.scores

    def history_store(self) -> "HistoryStore":
        if self.history is None:
            self.history = HistoryStore(self.cfg.history_root())
        return self.history

    def namespaces(self) -> list[str]:
        return self.cfg.namespaces_for(self.catalog)


def build_state(cfg: ProjectConfig) -> AppState:
    return AppState(
        cfg=cfg,
        catalog=catalog_for(cfg),
        store=StateStore(cfg.state_dir) if cfg.state_dir else None,
        notes=ContextNotes(cfg.context_dir),
        glossary=load_glossary(cfg.glossary_path),
        scores=ScoreStore(cfg.scores_root()),
        history=HistoryStore(cfg.history_root()),
    )


def invalidate_caches(st: AppState) -> None:
    """Drop request-path caches after catalogue/state mutation or reload.

    Progress/usage/status snapshots share this invalidation with overview so a
    save or ops write never leaves stale coverage cards or collect() results.
    """
    with st.cache_lock:
        st._overview_cache = None
        st._overview_stats_cache = None
        st._findings_cache = None
        st._message_index_cache = None
        st._source_total_cache = None
        st._resolve_by_target_cache = None
        st._status_rows_cache = None
        st._progress_cache = None
        st._usage_cache = {}
        st._review_queue = None
        st._visible_collections_cache = None
        st._leverage_cache = None
        st._screen_status_cache = None
        st._analysis_due_cache = None
        st._branches_cache = None
        st._metrics_cache = None
        st._places_cache = None
    # Analysis report cache lives on the handlers module (bands/fuzzy variants).
    try:
        from . import handlers_get as _hg

        _hg._ANALYSIS_CACHE.clear()
    except Exception:
        pass


def cached_screen_status(st: AppState) -> dict:
    """``status --group-by screen`` payload; invalidated with overview caches."""
    with st.cache_lock:
        hit = st._screen_status_cache
    if hit is not None:
        return hit
    from ..ops.status import op_status
    from ..ops.types import StatusRequest
    from .timing import span

    with st.screen_status_lock:
        with st.cache_lock:
            hit = st._screen_status_cache
        if hit is not None:
            return hit
        with span("status_by_screen"):
            result = op_status(
                st.cfg, StatusRequest(by_screen=True), catalog=st.catalog,
            )
        payload = result.to_dict()
        if result.ok:
            with st.cache_lock:
                st._screen_status_cache = payload
        return payload


def cached_leverage(st: AppState) -> dict:
    """TM leverage report; shares collect() with progress/usage/status."""
    with st.cache_lock:
        hit = st._leverage_cache
    if hit is not None:
        return hit
    from ..ops.tm import leverage_payload
    from .timing import span

    with span("tm_leverage"):
        payload = leverage_payload(
            st.cfg, catalog=st.catalog, status_rows=cached_status_rows(st),
        )
    with st.cache_lock:
        st._leverage_cache = payload
    return payload


def cached_visible_collections(st: AppState) -> list:
    """``visible_collections`` (may discover) once per cache generation."""
    with st.cache_lock:
        hit = st._visible_collections_cache
    if hit is not None:
        return hit
    from ..projects.collections import visible_collections
    from .timing import span

    with span("visible_collections"):
        rows = visible_collections(st.cfg)
    with st.cache_lock:
        st._visible_collections_cache = rows
    return rows


def cached_status_rows(st: AppState) -> list:
    """``collect()`` once per cache generation; shared by progress/usage/guide/status."""
    with st.cache_lock:
        hit = st._status_rows_cache
    if hit is not None:
        return hit
    from ..ops.status import collect
    from .timing import span

    with st.collect_lock:
        with st.cache_lock:
            hit = st._status_rows_cache
        if hit is not None:
            return hit
        with span("collect"):
            rows = collect(st.cfg, st.catalog)
        with st.cache_lock:
            st._status_rows_cache = rows
        return rows


def cached_metrics(st: AppState) -> dict:
    """Default ``/api/metrics`` payload (no by/since/locale filters)."""
    with st.cache_lock:
        hit = st._metrics_cache
    if hit is not None:
        return hit
    from ..ops.metrics import op_metrics
    from ..ops.types import MetricsRequest
    from .timing import span

    with st.metrics_lock:
        with st.cache_lock:
            hit = st._metrics_cache
        if hit is not None:
            return hit
        with span("metrics"):
            result = op_metrics(st.cfg, MetricsRequest(), catalog=st.catalog)
        payload = result.to_dict()
        if result.ok:
            with st.cache_lock:
                st._metrics_cache = payload
        return payload


def cached_places(st: AppState) -> dict:
    """``places list`` for Settings; shares the AppState catalog."""
    with st.cache_lock:
        hit = st._places_cache
    if hit is not None:
        return hit
    from ..ops.places import op_places
    from .timing import span

    with st.places_lock:
        with st.cache_lock:
            hit = st._places_cache
        if hit is not None:
            return hit
        with span("places"):
            result = op_places(st.cfg, "list", catalog=st.catalog)
        payload = result.to_dict()
        if result.ok:
            with st.cache_lock:
                st._places_cache = payload
        return payload


def cached_branches(st: AppState) -> dict:
    """Fast branch list for ``/api/branches``.

    Never runs ``collect()`` — that alone is multi-second and was stalling this
    page for 10–50s. Uses warm status rows when already cached (coverage chips);
    otherwise main shows a source-string count only. Tracked rows are metadata
    stubs (``detail=False``); Sync / merge-preview do the git-heavy work.
    """
    with st.cache_lock:
        hit = st._branches_cache
        warm_rows = st._status_rows_cache
    if hit is not None:
        return hit
    from ..projects.branches import list_branches
    from .timing import span

    # Single-flight: concurrent Branches tab loads share one build.
    lock = getattr(st, "_branches_lock", None)
    if lock is None:
        st._branches_lock = threading.Lock()
        lock = st._branches_lock
    with lock:
        with st.cache_lock:
            hit = st._branches_cache
            warm_rows = st._status_rows_cache
        if hit is not None:
            return hit
        with span("branches_list"):
            payload = list_branches(
                st.cfg,
                catalog=st.catalog,
                status_rows=warm_rows,
                detail=False,
            )
        if payload.get("ok"):
            with st.cache_lock:
                st._branches_cache = payload
        return payload


def cached_analysis_due(
    st: AppState,
    *,
    namespace: str | None,
    locales: list[str],
) -> dict[str, list[str]]:
    """Due source strings per locale for analysis; shared by bands=0 and bands=1."""
    key = (namespace or "", tuple(locales))
    with st.cache_lock:
        bag = st._analysis_due_cache
        if bag is not None and key in bag:
            return bag[key]
    from ..ops.console import analysis_due_sources
    from .timing import span

    with st.analysis_due_lock:
        with st.cache_lock:
            bag = st._analysis_due_cache
            if bag is not None and key in bag:
                return bag[key]
        with span("analysis_due"):
            _scope, due = analysis_due_sources(
                st.cfg,
                namespace=namespace,
                locales=locales,
                catalog=st.catalog,
                state=st.store,
            )
        with st.cache_lock:
            if st._analysis_due_cache is None:
                st._analysis_due_cache = {}
            st._analysis_due_cache[key] = due
        return due


def refresh_sidecars_from_disk(st: AppState, *, bust_catalog: bool = False) -> None:
    """Re-read state/scores after an out-of-process or ops write to disk.

    ``StateStore`` / ``ScoreStore`` keep an in-memory ``_cache``. CLI ``adopt``
    (and web ``dispatch_op`` paths that build their own stores) write new JSON
    while the web ``AppState`` still holds the pre-write map — overview cards
    then under-count until reload. Clearing the sidecar caches + overview
    caches fixes that without a full ``build_state``.
    """
    if st.store is not None:
        st.store.invalidate()
    if st.scores is not None:
        st.scores.invalidate()
    if bust_catalog:
        st.catalog.invalidate()
    invalidate_caches(st)


#: Ops that write state/scores/history on disk via a fresh store (not ``st.store``).
_OPS_REFRESH_SIDECARS = frozenset({
    "adopt",
    "apply",
    "scan_decide",
    "scan-decide",
    "import",
    "migrate_state",
    "migrate-state",
})
_OPS_BUST_CATALOG = frozenset({"import", "apply", "scan_decide", "scan-decide"})


def _coverage_bucket(st: AppState, locale: str, namespace: str, key: str) -> str:
    """Coverage class for one key — matches :func:`overview_stats` counting."""
    source = st.catalog.load(st.cfg.source_locale, namespace)
    if key not in source or st.cfg.is_skipped(namespace, key):
        return "missing"
    target = st.catalog.load(locale, namespace)
    if key not in target:
        return "missing"
    entry = st.store.entry(locale, namespace, key) if st.store else None
    if entry is None:
        return "missing"
    if needs_translation(source[key], entry):
        return "stale"
    return "translated"


def patch_caches_after_save(
    st: AppState,
    locale: str,
    namespace: str,
    key: str,
    *,
    old_bucket: str | None = None,
) -> None:
    """Patch index row and overview-stats after one key save; keep overview-lite."""
    with st.cache_lock:
        new_bucket = _coverage_bucket(st, locale, namespace, key)
        if st._overview_stats_cache is not None and old_bucket is not None:
            if old_bucket != new_bucket:
                for loc_data in st._overview_stats_cache.get("locales", []):
                    if loc_data["locale"] != locale:
                        continue
                    if old_bucket in ("translated", "stale", "missing"):
                        loc_data[old_bucket] = max(0, loc_data[old_bucket] - 1)
                    if new_bucket in ("translated", "stale", "missing"):
                        loc_data[new_bucket] = loc_data.get(new_bucket, 0) + 1
                    total = loc_data.get("total") or 1
                    loc_data["coverage"] = round(
                        loc_data["translated"] / total * 100, 1,
                    )
                    break
        if st._findings_cache is not None:
            st._findings_cache.pop((locale, namespace), None)
        st._resolve_by_target_cache = None
        if st._overview_stats_cache is not None:
            # Quality bins / averages go stale when scores or statuses change.
            st._overview_stats_cache.update(_dashboard_extras(st))
        if st._message_index_cache is not None:
            for cache_key, index in list(st._message_index_cache.items()):
                ns_scope = cache_key[1]
                if namespace != ns_scope and ns_scope != "__all__":
                    continue
                index.patch_row(st, list(cache_key[0]), namespace, key)
        # Reporting snapshots are not patchable cheaply — drop them so progress /
        # usage / status / leverage / metrics refresh after the next GET.
        st._status_rows_cache = None
        st._progress_cache = None
        st._usage_cache = {}
        st._metrics_cache = None
        st._leverage_cache = None
        st._screen_status_cache = None
        st._analysis_due_cache = None


def invalidate_caches_after_save(
    st: AppState, locale: str, namespace: str,
) -> None:
    """Legacy alias — prefer :func:`patch_caches_after_save`."""
    with st.cache_lock:
        st._overview_stats_cache = None
        if st._findings_cache is not None:
            st._findings_cache.pop((locale, namespace), None)
        if st._message_index_cache is not None:
            for key in list(st._message_index_cache):
                if key[1] == namespace or key[1] == "__all__":
                    del st._message_index_cache[key]


_MODELS_CACHE: dict[str, tuple[float, dict]] = {}


@functools.lru_cache(maxsize=1)
def _commands_manifest() -> dict:
    """The CLI manifest never changes while the server runs; build it once."""
    return build_commands_manifest(build_parser())


_INDEX_CACHE_CAP = 8
_FINDINGS_CACHE_CAP = 200
_STATES_CAP = 8
_INDEX_BUILD_LOCKS: OrderedDict[tuple, threading.Lock] = OrderedDict()
_INDEX_BUILD_LOCKS_GUARD = threading.Lock()


def _bounded_build_lock(key: tuple) -> threading.Lock:
    from .cache_bounds import LOCK_MAP_CAP, bounded_lock

    return bounded_lock(
        _INDEX_BUILD_LOCKS, key, guard=_INDEX_BUILD_LOCKS_GUARD, cap=LOCK_MAP_CAP,
    )


def reload_project_state(states: dict, name: str, *, default_project: str | None = None) -> AppState:
    """Rebuild ``AppState`` for *name* from disk and store it in *states*."""
    from ..projects import load_config, load_registry

    entry = load_registry().get(name)
    if entry is None:
        raise ValueError(f"unknown project {name!r}")
    cfg = load_config(entry.config_path)
    st = build_state(cfg)
    states[name] = st
    if isinstance(states, OrderedDict):
        states.move_to_end(name)
        _prune_states(states, keep=default_project or name)
    return st


def store_state(states: dict, name: str, st: AppState, default_project: str | None = None) -> AppState:
    """Put a freshly built ``AppState`` into the shared map under the lock, keeping it inside the project cap.

    Handlers run on many threads and ``_state``/``_prune_states`` iterate the same OrderedDict, so every write goes
    through here (M0, audit ops #9). Build the state before calling: that part is slow and needs no lock.
    """
    with _STATES_LOCK:
        states[name] = st
        if isinstance(states, OrderedDict):
            states.move_to_end(name)
            _prune_states(states, keep=default_project or name)
    return st


def _prune_states(states: OrderedDict, *, keep: str | None) -> None:
    while len(states) > _STATES_CAP:
        victim = None
        for key in states:
            if keep and key == keep:
                continue
            victim = key
            break
        if victim is None:
            break
        states.pop(victim, None)


def _message_index(
    st: AppState,
    locales: list[str],
    namespace: str,
) -> MessageIndex:
    """Return a cached MessageIndex; build outside ``cache_lock`` so a slow
    index does not stall provider-status / collect / other cache readers.
    """
    key = index_cache_key(locales, namespace)
    with st.cache_lock:
        if st._message_index_cache is None:
            st._message_index_cache = OrderedDict()
        hit = st._message_index_cache.get(key)
        if hit is not None:
            st._message_index_cache.move_to_end(key)
            return hit
    build_lock = _bounded_build_lock(key)
    with build_lock:
        with st.cache_lock:
            if st._message_index_cache is None:
                st._message_index_cache = OrderedDict()
            hit = st._message_index_cache.get(key)
            if hit is not None:
                st._message_index_cache.move_to_end(key)
                return hit
        hit = MessageIndex.build(st, locales, namespace)
        with st.cache_lock:
            if st._message_index_cache is None:
                st._message_index_cache = OrderedDict()
            st._message_index_cache[key] = hit
            while len(st._message_index_cache) > _INDEX_CACHE_CAP:
                st._message_index_cache.popitem(last=False)
            return hit


def _source_total(st: AppState) -> tuple[int, dict[str, int]]:
    if st._source_total_cache is not None:
        return st._source_total_cache
    namespaces = st.namespaces()
    per_ns: dict[str, int] = {}
    total = 0
    for ns in namespaces:
        n = len([
            k for k in st.catalog.load(st.cfg.source_locale, ns)
            if not st.cfg.is_skipped(ns, k)
        ])
        per_ns[ns] = n
        total += n
    st._source_total_cache = (total, per_ns)
    return st._source_total_cache


def _load_primary_state(primary_cfg: ProjectConfig) -> OrderedDict[str, AppState]:
    """Build AppState for the active project only; others load on first select."""
    return OrderedDict([(primary_cfg.name, build_state(primary_cfg))])


def _registered_project_names(primary: str) -> list[str]:
    names = {primary, *load_registry().keys()}
    return sorted(names)


# ---- data assembly ---------------------------------------------------------

def _tq_on_path() -> bool:
    from ..projects.taskqueue import tq_available
    return tq_available()


def findings(
    st: AppState,
    locale: str,
    namespace: str,
    *,
    keys: list[tuple[str, str]] | None = None,
    full: bool = False,
    cached_only: bool = False,
) -> dict:
    """Validation findings for one locale (optionally one namespace).

    ``namespace == "__all__"`` validates every namespace. Results are cached on
    AppState until ``invalidate_caches``.

    When ``keys`` is a list of (namespace, key) tuples, only those keys are
    validated (page-scoped). When ``sourceTotal > FULL_FINDINGS_THRESHOLD`` and
    neither ``keys`` nor ``full`` is set, returns partial empty payload.
    """
    try:
        if namespace == "__all__":
            if not isinstance(locale, str) or not _SAFE_COMPONENT.fullmatch(locale):
                raise ValueError("invalid locale")
        else:
            _validate_scope(st, locale, namespace)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "byKey": {}, "byNamespace": {}}

    # A fully cached answer needs no size check (and no catalogue walk).
    if keys is None and st._findings_cache:
        cached_ns = [namespace] if namespace != "__all__" else st.namespaces()
        if cached_ns and all((locale, ns) in st._findings_cache for ns in cached_ns):
            return _findings_payload(st, locale, namespace, cached_ns)

    source_total, _ = _source_total(st)
    # Cap full scans even when the client passes full=1. A specific namespace
    # may still run; ``__all__`` on a large project stays partial.
    if (
        keys is None
        and source_total > FULL_FINDINGS_THRESHOLD
        and (not full or namespace == "__all__")
    ):
        return {
            "ok": True,
            "partial": True,
            "locale": locale,
            "namespace": namespace,
            "byKey": {},
            "byNamespace": {},
        }

    all_ns = namespace == "__all__"
    ns_list = st.namespaces() if all_ns else [namespace]
    if keys is not None:
        ns_list = sorted({ns for ns, _ in keys})

    by_namespace: dict[str, dict[str, list[str]]] = {}
    by_key: dict[str, list[str]] = {}

    if st._findings_cache is None:
        st._findings_cache = OrderedDict()

    only_keys = set(keys) if keys else None

    for ns in ns_list:
        cache_key = (locale, ns)
        if only_keys is not None:
            ns_keys = {k for n, k in only_keys if n == ns}
            if not ns_keys:
                by_namespace[ns] = {}
                continue
            cached = None
        else:
            cached = st._findings_cache.get(cache_key)
            if cached is not None:
                st._findings_cache.move_to_end(cache_key)

        if cached is None and cached_only:
            by_namespace[ns] = {}
            continue
        if cached is None:
            ns_only = (
                {(n, k) for n, k in only_keys if n == ns}
                if only_keys is not None else None
            )
            report = run_validation(
                st.cfg, st.catalog, locales=[locale], namespace=ns,
                only_keys=ns_only,
            )
            ns_finds: dict[str, list[str]] = {}
            for f in report.findings:
                if f.locale == locale:
                    if only_keys is not None and (ns, f.key) not in only_keys:
                        continue
                    ns_finds.setdefault(f.key, []).append(f"{f.check}: {f.message}")
            if only_keys is None:
                st._findings_cache[cache_key] = ns_finds
                while len(st._findings_cache) > _FINDINGS_CACHE_CAP:
                    st._findings_cache.popitem(last=False)
            cached = ns_finds
        by_namespace[ns] = cached
        if all_ns:
            for key, msgs in cached.items():
                by_key.setdefault(f"{ns}.{key}" if ns else key, []).extend(msgs)
        else:
            by_key.update(cached)

    return {
        "ok": True,
        "locale": locale,
        "namespace": namespace,
        "byKey": by_key,
        "byNamespace": by_namespace,
    }


def _findings_payload(
    st: AppState, locale: str, namespace: str, ns_list: list[str],
) -> dict:
    """Assemble a findings response from the per-namespace cache only."""
    all_ns = namespace == "__all__"
    by_namespace: dict[str, dict[str, list[str]]] = {}
    by_key: dict[str, list[str]] = {}
    for ns in ns_list:
        cached = st._findings_cache[(locale, ns)]
        st._findings_cache.move_to_end((locale, ns))
        by_namespace[ns] = cached
        if all_ns:
            for key, msgs in cached.items():
                by_key.setdefault(f"{ns}.{key}" if ns else key, []).extend(msgs)
        else:
            by_key.update(cached)
    return {
        "ok": True, "locale": locale, "namespace": namespace,
        "byKey": by_key, "byNamespace": by_namespace,
    }


def _parse_finding_keys(raw: str) -> list[tuple[str, str]] | None:
    """Parse ``keys=ns:key,ns:key`` from query string."""
    if not raw or not raw.strip():
        return None
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            ns, key = part.split(":", 1)
        else:
            ns, key = "", part
        out.append((ns, key))
    return out or None


def messages(
    st: AppState,
    locales: list[str],
    namespace: str,
    query: str = "",
    only: str = "all",
    *,
    offset: int = 0,
    limit: int | None = None,
    include_findings: bool = False,
    sort: str = "",
    sort_dir: str = "asc",
    detail: str = "minimal",
    ns_prefix: str = "",
    mode: str = "exact",
) -> dict:
    """Keys in one namespace (or all), for one or more locales side by side.

    ``ns_prefix`` (e.g. ``admin``) keeps rows whose namespace equals the prefix
    or starts with ``prefix/``. When set, the index is built for ``__all__``
    (or the exact namespace when it is itself a configured leaf).
    """
    if not locales:
        locales = st.cfg.targets[:1]
    primary = locales[0] if locales else ""
    threshold = float(
        (getattr(st.cfg, "quality_thresholds", None) or {}).get(
            primary, getattr(st.cfg, "quality_threshold", 0.55),
        )
    )
    effective_limit = clamp_limit(limit)

    prefix = (ns_prefix or "").strip()
    index_ns = namespace
    if prefix:
        known = st.namespaces()
        if prefix in known and namespace == prefix:
            index_ns = prefix
        else:
            index_ns = "__all__"

    need_findings = include_findings or only == "has_findings"
    findings_by_ns: dict[str, dict[str, list[str]]] = {}
    if need_findings and primary:
        all_ns = index_ns == "__all__"
        ns_list = st.namespaces() if all_ns else [index_ns]
        if prefix:
            ns_list = [
                ns for ns in ns_list
                if ns == prefix or ns.startswith(prefix + "/")
            ]
        # A big project must not validate every namespace for one filter click:
        # past the threshold an ``__all__`` scan reads only what is cached.
        big = (
            index_ns == "__all__"
            and only == "has_findings"
            and _source_total(st)[0] > FULL_FINDINGS_THRESHOLD
        )
        for ns in ns_list:
            payload = findings(st, primary, ns, full=True, cached_only=big)
            findings_by_ns[ns] = payload.get("byNamespace", {}).get(ns, {})

    index = _message_index(st, locales, index_ns)
    pre_keys = None
    if only == "pre_translated" and primary and st.history is not None:
        latest = st.history.latest_by_key(primary)
        pre_keys = {
            sk for sk, event in latest.items() if event.trigger == "pre-translate"
        }
    filtered = index.filter_rows(
        only=only, query=query, threshold=threshold,
        findings_by_ns=findings_by_ns if need_findings else None,
        pre_translated_keys=pre_keys,
        mode=mode or "exact",
    )
    if prefix:
        filtered = [
            row for row in filtered
            if row.namespace == prefix or row.namespace.startswith(prefix + "/")
        ]
    if sort:
        filtered = index.sort_rows(filtered, sort, sort_dir, primary)

    total = len(filtered)
    start = max(0, int(offset or 0))
    page_rows = filtered[start:start + effective_limit]

    hydrated = hydrate_rows(
        st, page_rows, locales,
        detail=detail,
        findings_by_ns=findings_by_ns if need_findings else None,
    )

    return {
        "locales": locales,
        "namespace": namespace,
        "nsPrefix": prefix or None,
        "rows": hydrated,
        "counts": {"total": total, "offset": start, "limit": effective_limit},
        "qualityThreshold": threshold,
        "detail": detail,
    }


def message_row(
    st: AppState,
    locales: list[str],
    namespace: str,
    key: str,
) -> dict:
    """Full detail for a single key."""
    if not locales:
        locales = st.cfg.targets[:1]
    index = _message_index(st, locales, namespace)
    match = next(
        (r for r in index.rows if r.namespace == namespace and r.key == key),
        None,
    )
    if match is None:
        return {"ok": False, "error": f"{key!r} not found in {namespace!r}"}
    rows = hydrate_rows(st, [match], locales, detail="full")
    row = rows[0]
    primary = locales[0]
    from ..core.glossary_match import glossary_hits

    row["glossaryHits"] = [
        {
            "term": hit.term,
            "kind": hit.kind,
            "target": hit.target,
            "forbidden": list(hit.forbidden),
            "note": hit.note,
        }
        for hit in glossary_hits(match.source, st.glossary, primary)
    ]
    value = (row.get("values") or {}).get(primary)
    status = (row.get("statuses") or {}).get(primary)
    fallback = st.cfg.fallbacks.get(primary) if hasattr(st.cfg, "fallbacks") else None
    if fallback and (value is None or status == "missing"):
        sibling = st.catalog.load(fallback, namespace).get(key)
        if isinstance(sibling, str) and sibling:
            row["fallbackLocale"] = fallback
            row["fallbackValue"] = sibling
    if status == "stale":
        from ..catalog.source_history import SourceHistory

        row["sourceChange"] = SourceHistory(st.cfg.state_root()).latest(namespace, key)
    if st.history is not None:
        latest = st.history.latest(primary, namespace, key)
        if (
            latest is not None
            and latest.trigger == "propagated"
            and latest.propagated_from
        ):
            row["propagatedFrom"] = latest.propagated_from
    return {"ok": True, "row": row}


# Per-key edit operations live in ``key_edits``; resolved lazily so either
# module can be imported first without a circular-import failure.
_KEY_EDIT_NAMES = frozenset({
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
})


if TYPE_CHECKING:  # static view of the lazily re-exported names
    from .key_edits import (  # noqa: F401
        add_locale, history_for_key, mark_example, revert_key, save, save_context,
        set_locked, set_translate_enabled, validate_key, verify_key,
    )


def __getattr__(name: str):
    if name in _KEY_EDIT_NAMES:
        from . import key_edits

        return getattr(key_edits, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---- HTTP ------------------------------------------------------------------

_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


def _export_keys(value) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
        return items or None
    items = [str(part).strip() for part in value if str(part).strip()]
    return items or None


def posted_translation(st: AppState, namespace: str, key: str, body: dict) -> str:
    """The catalogue value for a save or live check.

    ``pluralBranches`` is joined by the active standard. A body without
    branches keeps the plain ``value`` field.
    """
    from .plurals import joined_value

    source = ""
    try:
        source = st.catalog.load(st.cfg.source_locale, namespace).get(key, "")
    except Exception:
        source = ""
    branches = body.get("pluralBranches")
    if isinstance(branches, dict) and branches:
        joined = joined_value(
            source, branches, body, getattr(st.cfg, "catalog_standard", None),
        )
        if joined is not None:
            return joined
    return str(body.get("value") or "")



from .dashboard import (  # noqa: E402,F401  (re-exported)
    _dashboard_extras, _overview_from_index, _warm_full_index,
    overview, overview_lite, overview_stats,
)
