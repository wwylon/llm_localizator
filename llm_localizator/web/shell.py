"""Shared chrome for the multi-page review UI.

Routes are empty states until a later phase fills them. Dashboard and
editor are filled here. ``/`` redirects to the dashboard. Public marketing
pages run on the marketing loopback port (ADR-45); the app port 302s the
old ``/landing`` paths there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape

from ..ops.permissions import DEFAULT_MATRIX, OPERATIONS
from .assets import document_style_links, static_href

# Apply font/theme before first paint (appearance.js also runs later).
_APPEARANCE_BOOT = (
    "<script>(function(){try{var d=document.documentElement,f=localStorage.getItem"
    "('llm_ui_font'),t=localStorage.getItem('llm_ui_theme');"
    "if(f)d.setAttribute('data-font',f);if(t){d.setAttribute('data-theme',t);"
    "d.style.colorScheme=t==='dark'?'dark':'light';}}catch(e){}})();</script>"
)


@dataclass(frozen=True)
class ShellRoute:
    id: str
    path: str
    title: str
    group: str
    phase: str


ROUTES: tuple[ShellRoute, ...] = (
    ShellRoute("dashboard", "/app", "Dashboard", "Workspace", "W-02"),
    ShellRoute("editor", "/app/editor", "Translations", "Workspace", "W-02"),
    ShellRoute("tm", "/app/tm", "Translation memory", "Workspace", "W-03"),
    ShellRoute("glossary", "/app/glossary", "Glossary", "Workspace", "W-04"),
    ShellRoute("review", "/app/review", "Review queue", "Workspace", "W-06"),
    ShellRoute("operations", "/app/operations", "Operations", "Operator", "W-05"),
    ShellRoute("queue", "/app/queue", "Queue", "Operator", "W-05"),
    ShellRoute("hardcoded", "/app/hardcoded", "Hardcoded strings", "Operator", "W-05"),
    ShellRoute("settings", "/app/settings", "Settings", "Operator", "W-05"),
    ShellRoute("analysis", "/app/analysis", "Analysis", "Operator", "W-05"),
    ShellRoute("usage", "/app/stats/usage", "Usage", "Operator", "W-05"),
    ShellRoute("progress", "/app/stats/progress", "Progress", "Operator", "W-05"),
    ShellRoute("project-config", "/app/project-config", "Project config", "Operator", "W-07"),
    ShellRoute("model-eval", "/app/model-eval", "Model eval", "Operator", "W-07"),
    ShellRoute("workflow", "/app/workflow", "Workflow", "Operator", "W-10"),
    ShellRoute("branches", "/app/branches", "Branches", "Operator", "W-10"),
    ShellRoute("login", "/login", "Login", "Account", "W-08"),
    ShellRoute("register", "/register", "Register", "Account", "W-08"),
    ShellRoute("pending", "/pending", "Pending", "Account", "W-08"),
    ShellRoute("setup", "/setup", "Setup", "Account", "W-08"),
    ShellRoute("users", "/app/admin/users", "Users & roles", "Account", "W-08"),
    ShellRoute("activity", "/app/admin/activity", "Team activity", "Account", "W-08"),
)

_BY_ID = {route.id: route for route in ROUTES}
_BY_PATH = {route.path: route for route in ROUTES}

# Pages this phase fills. Other routes stay an empty state.
# help.js is deferred via shell ``__LLM_ENSURE_HELP`` (Wave 3) so first paint
# does not wait on the large help catalogue.
_PAGE_SCRIPTS = {
    "dashboard": ("/static/dashboard.js",),
    "editor": ("/static/placeholders.js", "/static/editor-memory.js", "/static/editor.js"),
    "tm": ("/static/tm.js",),
    "glossary": ("/static/glossary.js",),
    "review": ("/static/review.js",),
    "operations": ("/static/operations.js",),
    "queue": ("/static/queue.js",),
    "hardcoded": ("/static/hardcoded.js",),
    "settings": ("/static/settings.js",),
    "analysis": ("/static/analysis.js",),
    "usage": ("/static/usage.js",),
    "progress": ("/static/progress.js",),
    "project-config": ("/static/project-config.js",),
    "model-eval": ("/static/model-eval.js",),
    "login": ("/static/auth.js",),
    "register": ("/static/auth.js",),
    "pending": ("/static/auth.js",),
    "setup": ("/static/setup.js",),
    "users": ("/static/users.js",),
    "activity": ("/static/translator-activity.js",),
    "workflow": ("/static/workflow.js",),
    "branches": ("/static/branches.js",),
}
_HELP_DEFER = (
    "<script>(function(){var e=window.__LLM_ENSURE_HELP;if(!e)return;"
    "var run=function(){e();};"
    "if(window.requestIdleCallback)requestIdleCallback(run,{timeout:2000});"
    "else setTimeout(run,0);})();</script>"
)

_I18N_KEYS = {
    "dashboard": "nav_dashboard",
    "editor": "nav_translations",
    "tm": "nav_tm",
    "glossary": "nav_glossary",
    "review": "nav_review",
    "operations": "nav_operations",
    "queue": "nav_queue",
    "hardcoded": "nav_hardcoded",
    "settings": "nav_settings",
    "analysis": "nav_analysis",
    "usage": "nav_usage",
    "progress": "nav_progress",
    "project-config": "nav_project_config",
    "model-eval": "nav_model_eval",
    "workflow": "nav_workflow",
    "branches": "nav_branches",
    "users": "nav_users",
    "activity": "nav_activity",
}

# Same order and defaults as ops.permissions. Settings JS locks Admin and
# Translator×translate (W-08).
def _permission_rows() -> tuple[tuple[str, tuple[bool, bool, bool, bool]], ...]:
    return tuple((name, DEFAULT_MATRIX[name]) for name in OPERATIONS)


def route_for_path(path: str) -> ShellRoute | None:
    """Exact path match. A trailing slash is a different path and misses."""
    return _BY_PATH.get(path)


def token_snippet(token: str) -> str:
    """Attach the startup token to every same-origin fetch without inlining it.

    The token is fetched once from ``GET /api/bootstrap-token`` (loopback only)
    so View Source / HTML scrapers do not see it. Curl still uses
    ``X-LLM-Token`` from the startup print / ``web.token`` file. Locale-gated
    GETs resolve the actor the same way POSTs do.
    """
    if not token:
        return ""
    # *token* is accepted so call sites stay stable; the value is not embedded.
    _ = token
    return (
        "<script>(function(){"
        "var _fetch=window.fetch;"
        "var tokenPromise=null;"
        "function loadToken(){"
        "if(!tokenPromise){"
        "tokenPromise=_fetch('/api/bootstrap-token',{credentials:'same-origin'})"
        ".then(function(r){return r.ok?r.json():{};})"
        ".then(function(j){window.__LLM_TOKEN=j.token||'';return window.__LLM_TOKEN;})"
        ".catch(function(){window.__LLM_TOKEN='';return '';});"
        "}"
        "return tokenPromise;"
        "}"
        "window.__LLM_TOKEN_READY=loadToken();"
        # Token only for same-origin URLs; on a 403 token error (server
        # restarted / token rotated) fetch a fresh token and retry once.
        "function sameOrigin(input){"
        "try{var u=new URL(typeof input==='string'?input:input.url,location.href);"
        "return u.origin===location.origin;}catch(e){return false;}"
        "}"
        "function send(self,input,init,t){"
        "var o=Object.assign({},init||{});"
        "var headers=new Headers(o.headers||{});"
        "if(t)headers.set('X-LLM-Token',t);"
        "o.headers=headers;"
        "return _fetch.call(self,input,o);"
        "}"
        "window.fetch=function(input,init){"
        "var self=this;"
        "if(!sameOrigin(input))return _fetch.call(self,input,init);"
        "var preset=init&&new Headers(init.headers||{}).has('X-LLM-Token');"
        "if(preset)return _fetch.call(self,input,init);"
        "return loadToken().then(function(t){"
        "return send(self,input,init,t).then(function(r){"
        "if(r.status!==403||(init&&init.body&&typeof init.body!=='string'))return r;"
        "return r.clone().json().catch(function(){return {};}).then(function(j){"
        "if(!/token/i.test(String(j&&j.error||'')))return r;"
        "tokenPromise=null;"
        "return loadToken().then(function(t2){"
        "return t2&&t2!==t?send(self,input,init,t2):r;"
        "});"
        "});"
        "});"
        "});"
        "};"
        "})();</script>"
    )


def _ops_markup(ui_labels: dict[str, str] | None = None) -> str:
    labels = ui_labels or {}
    return (
        '<div id="ops-drawer" class="ops-panel" hidden>'
        '<div class="ops-head">'
        f'<strong data-i18n="nav_operations">{escape(labels.get("nav_operations", "Operations"))}</strong>'
        f'<button type="button" class="btn" id="ops-close" data-i18n="op_close">'
        f'{escape(labels.get("op_close", "Close"))}</button>'
        "</div>"
        '<div class="ops-body">'
        '<nav id="ops-commands" class="ops-commands"></nav>'
        '<div class="ops-main">'
        '<p id="ops-desc" class="empty-state"></p>'
        '<div id="ops-form"></div>'
        '<div class="ops-actions">'
        f'<button type="button" class="btn" id="ops-dry-btn" data-i18n="wf_run_dry">'
        f'{escape(labels.get("wf_run_dry", "Dry run"))}</button>'
        f'<button type="button" class="btn btn-primary" id="ops-run-btn" data-i18n="op_run">'
        f'{escape(labels.get("op_run", "Run"))}</button>'
        f'<button type="button" class="btn" id="ops-stop-btn" hidden data-i18n="op_stop">'
        f'{escape(labels.get("op_stop", "Stop"))}</button>'
        "</div>"
        f'<pre class="ops-log" id="ops-log" data-i18n="op_output_empty">'
        f'{escape(labels.get("op_output_empty", "Output appears here after you run an operation."))}</pre>'
        "</div>"
        "</div>"
        "</div>"
    )


def _svg(body: str) -> str:
    """Inline icon. Not passed through html.escape."""
    return (
        '<svg viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        f"{body}</svg>"
    )


_NAV_ICONS = {
    "dashboard": _svg(
        '<rect width="7" height="9" x="3" y="3" rx="1"/>'
        '<rect width="7" height="5" x="14" y="3" rx="1"/>'
        '<rect width="7" height="9" x="14" y="12" rx="1"/>'
        '<rect width="7" height="5" x="3" y="16" rx="1"/>'
    ),
    "editor": _svg(
        '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/>'
        '<path d="M2 5h12"/><path d="M7 2h1"/>'
        '<path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>'
    ),
    "tm": _svg(
        '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>'
    ),
    "glossary": _svg(
        '<path d="M12 7v14"/>'
        '<path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>'
    ),
    "review": _svg(
        '<rect width="8" height="4" x="8" y="2" rx="1"/>'
        '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
        '<path d="m9 14 2 2 4-4"/>'
    ),
    "operations": _svg(
        '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>'
    ),
    "settings": _svg(
        '<path d="M20 7h-9"/><path d="M14 17H5"/>'
        '<circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>'
    ),
    "analysis": _svg(
        '<line x1="18" x2="18" y1="20" y2="10"/>'
        '<line x1="12" x2="12" y1="20" y2="4"/>'
        '<line x1="6" x2="6" y1="20" y2="14"/>'
    ),
    "usage": _svg(
        '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>'
        '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/>'
        '<path d="M12 17.5v-11"/>'
    ),
    "progress": _svg(
        '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>'
        '<polyline points="16 7 22 7 22 13"/>'
    ),
    "project-config": _svg(
        '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/>'
        '<line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/>'
        '<line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/>'
        '<line x1="14" x2="14" y1="2" y2="6"/>'
        '<line x1="8" x2="8" y1="10" y2="14"/>'
        '<line x1="16" x2="16" y1="18" y2="22"/>'
    ),
    "model-eval": _svg(
        '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/>'
        '<path d="M8.5 2h7"/><path d="M7 16h10"/>'
    ),
    "workflow": _svg(
        '<line x1="6" x2="6" y1="3" y2="15"/>'
        '<circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>'
        '<path d="M18 9a9 9 0 0 1-9 9"/>'
    ),
    "branches": _svg(
        '<line x1="6" x2="6" y1="3" y2="15"/>'
        '<circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>'
        '<path d="M18 9a9 9 0 0 1-9 9"/>'
        '<line x1="19" x2="19" y1="16" y2="22"/><line x1="16" x2="22" y1="19" y2="19"/>'
    ),
    "users": _svg(
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "activity": _svg(
        '<path d="M3 3v18h18"/>'
        '<path d="m19 9-5 5-4-4-3 3"/>'
    ),
    "queue": _svg(
        '<line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/>'
        '<line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/>'
        '<line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/>'
    ),
    "hardcoded": _svg(
        '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/>'
        '<line x1="11" x2="11" y1="8" y2="12"/><line x1="11" x2="11.01" y1="15" y2="15"/>'
    ),
}

_COMPACT_PAGES = frozenset({
    "editor", "review", "tm", "glossary", "branches", "workflow",
    "operations", "analysis", "project-config", "model-eval",
    "usage", "progress", "users", "activity", "queue", "hardcoded",
})

# Auth screens and public marketing stay routable, not app-sidebar links.
_SIDEBAR_SKIP = frozenset({
    "login", "register", "pending", "setup",
    "landing", "how-it-works", "roadmap", "api-docs",
})


def _ui_href(path: str, ui_locale: str) -> str:
    """Prefix shell hrefs with ``/{lang}`` (ADR-108)."""
    from .ui_locale_path import prefixed_path

    return prefixed_path(ui_locale or "en", path)


def _ui_nav_labels(ui_locale: str) -> dict[str, str]:
    """Package locale strings for SSR nav (ADR-108); EN fills gaps."""
    from .translator import _load_web_ui_en, _read_locale_json, web_ui_locales_dir

    labels = dict(_load_web_ui_en())
    loc = (ui_locale or "en").strip() or "en"
    if loc != "en":
        labels.update(_read_locale_json(web_ui_locales_dir() / f"{loc}.json"))
    return labels


def _ui_span(
    labels: dict[str, str],
    key: str,
    fallback: str,
    *,
    tag: str = "span",
    attrs: str = "",
) -> str:
    """SSR text node with ``data-i18n`` so client locale switches stay in sync."""
    text = labels.get(key, fallback)
    extra = f" {attrs}" if attrs else ""
    return f"<{tag}{extra} data-i18n=\"{escape(key)}\">{escape(text)}</{tag}>"


def _build_nav(current, ui_labels: dict, ui_locale: str) -> list[str]:
    """The sidebar: one heading per route group, one link per route (the active one marked)."""
    groups: list[str] = []
    for route in ROUTES:
        if route.id in _SIDEBAR_SKIP:
            continue
        if route.group not in groups:
            groups.append(route.group)
    nav: list[str] = []
    for group in groups:
        group_key = {
            "Workspace": "nav_workspace",
            "Operator": "nav_reports",
            "Account": "nav_admin",
        }.get(group, "")
        if group_key:
            group_label = ui_labels.get(group_key, group)
            nav.append(
                f'<div class="nav-group" data-i18n="{escape(group_key)}">'
                f"{escape(group_label)}</div>"
            )
        else:
            nav.append(f'<div class="nav-group">{escape(group)}</div>')
        for route in ROUTES:
            if route.group != group:
                continue
            if route.id in _SIDEBAR_SKIP:
                continue
            active = " is-active" if route.id == current.id else ""
            icon = _NAV_ICONS.get(route.id, "·")
            i18n = _I18N_KEYS.get(route.id)
            label_attrs = f' data-i18n="{escape(i18n)}"' if i18n else ""
            label_text = (
                ui_labels.get(i18n, route.title) if i18n else route.title
            )
            badge = ""
            if route.id == "review":
                badge = (
                    '<span class="nav-badge" id="review-badge" hidden></span>'
                )
            href = _ui_href(route.path, ui_locale)
            nav.append(
                f'<a class="nav-link{active}" href="{escape(href)}" '
                f'data-route="{escape(route.id)}">'
                f'<span class="nav-icon" aria-hidden="true">{icon}</span>'
                f'<span class="nav-label"{label_attrs}>{escape(label_text)}</span>'
                f"{badge}"
                f"</a>"
            )
    return nav


def render_shell(
    route_id: str,
    token: str = "",
    *,
    ui_locale: str = "en",
    qa_locales: list[str] | None = None,
) -> str:
    """One sidebar for every app page-map route. Filled pages mount their script."""
    current = _BY_ID[route_id]
    ui_labels = _ui_nav_labels(ui_locale)
    qa = [c for c in (qa_locales or []) if c]
    nav = _build_nav(current, ui_labels, ui_locale)
    account_pages = {"login", "register", "pending", "setup"}
    if current.id in account_pages:
        return _render_auth_shell(
            current, token, ui_locale=ui_locale, qa_locales=qa,
        )

    scripts = [
        _script_tag("/static/ui-locale.js"),
        _script_tag("/static/appearance.js"),
        _script_tag("/static/api.js"),
        _script_tag("/static/request-health.js"),
        _script_tag("/static/a11y.js"),
        _script_tag("/static/shell.js"),
    ]
    if current.id in _PAGE_SCRIPTS:
        # Visible before the page script finishes its first fetch.
        inner = (
            f'<p class="empty-state" data-i18n="usage_loading">'
            f'{escape(ui_labels.get("usage_loading", "Loading…"))}</p>'
        )
        editor_cls = " is-editor" if current.id == "editor" else ""
        compact_cls = " is-compact" if current.id in _COMPACT_PAGES else ""
        if current.id == "settings":
            page_head = (
                '<div class="page-head page-head-settings">'
                '<div class="page-head-text">'
                f"{_ui_span(ui_labels, 'set_title', 'System settings', tag='h1')}"
                f"{_ui_span(ui_labels, 'set_sub', 'LLM engine, locale configuration, and project options', tag='p', attrs='class=\"page-sub\"')}"
                "</div>"
                "</div>"
                '<div class="settings-tabs" id="settings-tabs" role="tablist">'
                '<button type="button" class="settings-tab is-active" data-tab="llm" '
                f'data-i18n="set_tab_llm">{escape(ui_labels.get("set_tab_llm", "Translation engine"))}</button>'
                '<button type="button" class="settings-tab" data-tab="locales" '
                f'data-i18n="set_tab_locales">{escape(ui_labels.get("set_tab_locales", "Locales"))}</button>'
                '<button type="button" class="settings-tab" data-tab="project" '
                f'data-i18n="set_tab_project">{escape(ui_labels.get("set_tab_project", "Project"))}</button>'
                '<button type="button" class="settings-tab" data-tab="web" '
                f'data-i18n="set_tab_web">{escape(ui_labels.get("set_tab_web", "Web UI"))}</button>'
                '<button type="button" class="settings-tab" data-tab="permissions" '
                f'data-i18n="set_tab_permissions">{escape(ui_labels.get("set_tab_permissions", "Permissions"))}</button>'
                "</div>"
            )
        elif current.id == "users":
            page_head = (
                '<div class="page-head page-head-users">'
                '<div class="page-head-text">'
                f'<h1 data-i18n="nav_users">{escape(ui_labels.get("nav_users", current.title))}</h1>'
                f"{_ui_span(ui_labels, 'users_sub', 'Manage who can access the workspace and what they can edit', tag='p', attrs='class=\"page-sub\"')}"
                "</div>"
                '<div class="page-head-actions" id="users-head-actions">'
                '<button type="button" class="btn btn-primary" id="invite-open" '
                f'data-i18n="users_invite">{escape(ui_labels.get("users_invite", "+ Invite user"))}</button>'
                "</div>"
                "</div>"
            )
        elif current.id == "activity":
            page_head = (
                '<div class="page-head">'
                '<div class="page-head-text">'
                f'<h1 data-i18n="nav_activity">{escape(ui_labels.get("nav_activity", current.title))}</h1>'
                f"{_ui_span(ui_labels, 'activity_sub', 'Edits, verifies, and reverts by translator', tag='p', attrs='class=\"page-sub\"')}"
                "</div>"
                '<div class="page-head-actions" id="activity-head-actions"></div>'
                "</div>"
            )
        elif current.id == "model-eval":
            page_head = (
                '<div class="page-head">'
                '<div class="page-head-text">'
                f"{_ui_span(ui_labels, 'usage_link_eval', 'Model evaluation', tag='h1')}"
                f"{_ui_span(ui_labels, 'me_sub', 'Test and validate a new LLM model before using it in production', tag='p', attrs='class=\"page-sub\"')}"
                "</div>"
                '<div class="page-head-actions" id="me-head-actions"></div>'
                "</div>"
            )
        elif current.id == "project-config":
            page_head = (
                '<div class="page-head">'
                '<div class="page-head-text">'
                f'<h1 id="pc-title" data-i18n="nav_project_config">{escape(ui_labels.get("nav_project_config", "Project config"))}</h1>'
                f'<p class="page-sub" id="pc-sub" data-i18n="pc_shell_sub">{escape(ui_labels.get("pc_shell_sub", "Project-specific prompts, bridge language, and glossary sharing"))}</p>'
                "</div>"
                '<div class="page-head-actions" id="pc-head-actions"></div>'
                "</div>"
            )
        elif current.id == "glossary":
            page_head = (
                '<div class="page-head page-head-glossary">'
                '<div class="page-head-text">'
                f'<h1 data-i18n="nav_glossary">{escape(ui_labels.get("nav_glossary", current.title))}</h1>'
                '<p class="page-sub" id="glossary-sub"></p>'
                "</div>"
                '<div class="page-head-actions" id="glossary-head-actions">'
                "</div>"
                "</div>"
            )
        elif current.id == "tm":
            page_head = (
                '<div class="page-head page-head-tm">'
                '<div class="page-head-text">'
                f'<h1 data-i18n="nav_tm">{escape(ui_labels.get("nav_tm", current.title))}</h1>'
                '<p class="page-sub" id="tm-sub"></p>'
                "</div>"
                '<div class="page-head-actions" id="tm-head-actions">'
                '<button type="button" class="btn" id="tm-import-btn" '
                f'data-i18n="tm_import">{escape(ui_labels.get("tm_import", "Import TMX"))}</button>'
                '<button type="button" class="btn" id="tm-export-btn" '
                f'data-i18n="tm_export">{escape(ui_labels.get("tm_export", "Export TMX"))}</button>'
                "</div>"
                "</div>"
                '<div class="tm-tabs-slot" id="tm-tabs"></div>'
            )
        elif current.id == "usage":
            page_head = (
                '<div class="page-head page-head-usage">'
                '<div class="page-head-text">'
                f'<h1 data-i18n="nav_usage">{escape(ui_labels.get("nav_usage", current.title))}</h1>'
                f'<p class="page-sub" id="usage-sub" data-i18n="usage_subtitle">{escape(ui_labels.get("usage_subtitle", "External LLM API usage and cost estimates"))}</p>'
                "</div>"
                '<div class="page-head-actions" id="usage-head-actions">'
                '<select class="pg-select" id="usage-period" '
                f'aria-label="{escape(ui_labels.get("usage_period_label", "Period"))}" '
                'data-i18n-aria="usage_period_label">'
                f'<option value="month" data-i18n="usage_period_month">{escape(ui_labels.get("usage_period_month", "This month"))}</option>'
                f'<option value="last_month" data-i18n="usage_period_last_month">{escape(ui_labels.get("usage_period_last_month", "Last month"))}</option>'
                f'<option value="90d" data-i18n="usage_period_90d">{escape(ui_labels.get("usage_period_90d", "Last 90 days"))}</option>'
                f'<option value="all" data-i18n="usage_period_all">{escape(ui_labels.get("usage_period_all", "All time"))}</option>'
                "</select>"
                '<button type="button" class="btn" id="usage-export-btn" '
                f'data-i18n="usage_export">{escape(ui_labels.get("usage_export", "↓ Export CSV"))}</button>'
                "</div>"
                "</div>"
            )
        elif current.id == "analysis":
            page_head = (
                '<div class="page-head page-head-analysis">'
                '<div class="page-head-text">'
                f"{_ui_span(ui_labels, 'an_title', 'Pre-translation analysis', tag='h1')}"
                f'<p class="page-sub" id="an-sub" data-i18n="an_sub">{escape(ui_labels.get("an_sub", "Word count breakdown, TM leverage, estimated effort and cost — before running translate"))}</p>'
                "</div>"
                '<div class="page-head-actions" id="an-head-actions"></div>'
                "</div>"
            )
        elif current.id == "editor":
            page_head = ""
        elif current.id == "dashboard":
            page_head = (
                '<div class="page-head page-head-dash">'
                '<div class="page-head-text">'
                f'<h1 id="dash-title" data-i18n="nav_dashboard">{escape(ui_labels.get("nav_dashboard", "Dashboard"))}</h1>'
                '<p class="page-sub" id="dash-sub"></p>'
                "</div>"
                '<div class="page-head-actions">'
                '<button type="button" class="btn" id="dash-add-locale" '
                f'data-i18n="dash_add_locale">{escape(ui_labels.get("dash_add_locale", "+ Add locale"))}</button>'
                '<a class="btn btn-primary" id="dash-open-editor" '
                f'href="{escape(_ui_href("/app/editor", ui_locale))}" '
                f'data-i18n="dash_open_editor">{escape(ui_labels.get("dash_open_editor", "Open editor →"))}</a>'
                f'<a class="btn" href="{escape(_ui_href("/app/operations", ui_locale))}" '
                f'data-i18n="nav_operations">{escape(ui_labels.get("nav_operations", "Operations"))}</a>'
                "</div>"
                "</div>"
            )
        else:
            i18n = _I18N_KEYS.get(current.id)
            if i18n:
                page_head = (
                    '<div class="page-head">'
                    f'<h1 data-i18n="{escape(i18n)}">'
                    f'{escape(ui_labels.get(i18n, current.title))}</h1>'
                    "</div>"
                )
            else:
                page_head = (
                    '<div class="page-head">'
                    f"<h1>{escape(current.title)}</h1>"
                    "</div>"
                )
        main = (
            f'<main class="main{editor_cls}{compact_cls}" id="page" data-page="{escape(current.id)}">'
            f"{page_head}"
            f'<div id="page-body">{inner}</div>'
            "</main>"
        )
        scripts.extend(
            _script_tag(src) for src in _PAGE_SCRIPTS[current.id]
        )
        scripts.append(_HELP_DEFER)
    else:
        line = escape(f"{current.phase} fills this page.")
        main = (
            "<main class=\"main\">"
            f"<h1>{escape(current.title)}</h1>"
            f'<p class="empty-state">{line}</p>'
            "</main>"
        )
    return (
        "<!DOCTYPE html>"
        f'<html lang="{escape(ui_locale or "en")}">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(current.title)} — llm-localizator</title>"
        f"{document_style_links()}"
        f"{_APPEARANCE_BOOT}"
        f"{token_snippet(token)}"
        f'<script>window.__LLM_UI_LOCALE={json.dumps(ui_locale or "en")};'
        f"window.__LLM_UI_QA_LOCALES={json.dumps(qa)};</script>"
        "</head>"
        "<body>"
        f'<a class="skip-link" href="#page-body" data-i18n="a11y_skip">{escape(ui_labels.get("a11y_skip", "Skip to content"))}</a>'
        '<div class="shell">'
        '<aside class="sidebar">'
        f'<a class="brand" href="{escape(_ui_href("/app", ui_locale))}">'
        'llm<span class="brand-mark">·</span>localizator</a>'
        '<div class="project">'
        '<label class="project-label" for="project-select" data-i18n="shell_project">'
        f'{escape(ui_labels.get("shell_project", "Project"))}</label>'
        '<select id="project-select" class="project-select"></select>'
        '<button type="button" id="project-remove" class="btn-link" hidden '
        f'title="{escape(ui_labels.get("shell_remove_title", "Remove this project from the list (files untouched)"))}" '
        f'data-i18n="shell_remove_list">{escape(ui_labels.get("shell_remove_list", "Remove from list"))}</button>'
        '<a id="shell-branch-chip" class="shell-branch" href="/app/branches" hidden '
        f'title="{escape(ui_labels.get("shell_branch_title", "Active localisation branch"))}"></a>'
        "</div>"
        f'<nav class="nav">{"".join(nav)}</nav>'
        '<div id="lang-sel-mount" class="lang-sel-mount"></div>'
        '<div class="shell-footer" id="shell-user"></div>'
        "</aside>"
        f"{main}"
        "</div>"
        f'{"".join(scripts)}'
        "</body>"
        "</html>"
    )


def _script_tag(src: str) -> str:
    return f'<script src="{escape(static_href(src))}"></script>'


def _render_auth_shell(
    current: ShellRoute,
    token: str = "",
    *,
    ui_locale: str = "en",
    qa_locales: list[str] | None = None,
) -> str:
    """Industry 50/50 auth layout without the app sidebar."""
    qa = [c for c in (qa_locales or []) if c]
    ui_labels = _ui_nav_labels(ui_locale)
    scripts = [_script_tag("/static/ui-locale.js")]
    if current.id in _PAGE_SCRIPTS:
        scripts.extend(
            _script_tag(src) for src in _PAGE_SCRIPTS[current.id]
        )
    points = (
        ("auth_point_formats", "Catalogue formats from the registry: JSON, YAML, gettext, ARB, XML and more"),
        ("auth_point_ollama", "Local or cloud, your choice: nothing leaves your machine unless you pick a cloud engine"),
        ("auth_point_ci", "CI-safe validate: no model required"),
    )
    points_html = "".join(
        f'<li data-i18n="{escape(key)}">{escape(ui_labels.get(key, text))}</li>'
        for key, text in points
    )
    return (
        "<!DOCTYPE html>"
        f'<html lang="{escape(ui_locale or "en")}">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(current.title)} — llm-localizator</title>"
        f"{document_style_links()}"
        f"{_APPEARANCE_BOOT}"
        f"{token_snippet(token)}"
        f'<script>window.__LLM_UI_LOCALE={json.dumps(ui_locale or "en")};'
        f"window.__LLM_UI_QA_LOCALES={json.dumps(qa)};</script>"
        "</head>"
        '<body class="public-body">'
        '<div class="auth-shell">'
        '<aside class="auth-brand">'
        f'<a class="brand" href="{escape(_ui_href("/app", ui_locale))}">'
        'llm<span class="brand-mark">·</span>localizator</a>'
        "<div>"
        f'<h2><span data-i18n="auth_tagline_1">{escape(ui_labels.get("auth_tagline_1", "Translate your app."))}</span> '
        f'<span class="accent" data-i18n="auth_tagline_2">{escape(ui_labels.get("auth_tagline_2", "Without the chaos."))}</span></h2>'
        f'<p class="lede" data-i18n="auth_lede">{escape(ui_labels.get("auth_lede", "Find hardcoded strings, translate with a local or cloud engine, validate and review."))}</p>'
        f'<ul class="auth-points">{points_html}</ul>'
        "</div>"
        f'<div class="auth-foot" data-i18n="auth_foot">{escape(ui_labels.get("auth_foot", "llm-localizator · MIT"))}</div>'
        '<div id="lang-sel-mount" class="lang-sel-mount"></div>'
        "</aside>"
        '<div class="auth-form-wrap">'
        f'<div class="auth-form" id="page" data-page="{escape(current.id)}">'
        f'<div id="page-body"></div>'
        "</div>"
        "</div>"
        "</div>"
        f'{"".join(scripts)}'
        "</body>"
        "</html>"
    )
