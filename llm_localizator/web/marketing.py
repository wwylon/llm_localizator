"""Public marketing pages: landing, how-it-works, roadmap, API docs.

Served on the marketing loopback port (ADR-45). Format names come from the
registry. The landing demo transcript is an illustration, not a measured
catalogue count. Fixture test counts stay out of the HTML (W-11).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
import json
from html import escape
from pathlib import Path

from .. import __version__
from ..catalog import KNOWN_FORMATS, resolve_format
from .api_routes import (
    API_DETAILS, API_GROUP_ORDER, API_ROUTES, api_anchor, api_group,
)
from .assets import document_style_links
from .marketing_sections import (
    FORMAT_BLURBS, bench_section, builtin_engines, engines_section, roadmap_list,
)
from .static_site import StaticSite, seo_head

def _mkt_labels() -> dict[str, str]:
    """EN UI catalogue; marketing copy lives here so SSR has no prose literals."""
    from .translator import _load_web_ui_en

    return dict(_load_web_ui_en())


def _t(labels: dict[str, str], key: str) -> str:
    return labels.get(key, key)


_REPO = Path(__file__).resolve().parents[2]
_PHASE_DIR = _REPO / "plan" / "web-platform"
_DOCS_INSTALL = _REPO / "docs" / "getting-started.md"
_PACKAGED = Path(__file__).resolve().parent / "marketing_content"
_PACKAGED_PHASES = _PACKAGED / "phases.json"
BRAND = "llm-localizator"
GITHUB_URL = "https://github.com/wwylon/llm_localizator"
PIP_INSTALL = "pip install llm_localizator"  # PyPI dist name; llm-localize on PyPI is another project
_GITHUB = GITHUB_URL
_BRANCH = "main"  # public default branch (the local checkout uses master)
_DOCS = f"{_GITHUB}/blob/{_BRANCH}/docs"

DEFAULT_APP_PORT = 8770

# One-page landing scroll targets (match index.dc.html).
_LANDING_NAV = (
    ("#features", "mkt_nav_features"),
    ("#engines", "mkt_nav_engines"),
    ("#benchmark", "mkt_nav_benchmark"),
    ("#formats", "mkt_nav_formats"),
    ("#install", "mkt_nav_install"),
)

_PIPELINE_STEPS = (
    ("mkt_pipeline_discover", "mkt_pipeline_discover_body"),
    ("mkt_pipeline_translate", "mkt_pipeline_translate_body"),
    ("mkt_pipeline_validate", "mkt_pipeline_validate_body"),
    ("mkt_pipeline_review", "mkt_pipeline_review_body"),
)

_LANDING_FEATURES = (
    ("01", "mkt_feat_01_t", "mkt_feat_01_b"),
    ("02", "mkt_feat_02_t", "mkt_feat_02_b"),
    ("03", "mkt_feat_03_t", "mkt_feat_03_b"),
    ("04", "mkt_feat_04_t", "mkt_feat_04_b"),
    ("05", "mkt_feat_05_t", "mkt_feat_05_b"),
    ("06", "mkt_feat_06_t", "mkt_feat_06_b"),
)


def _packaged_snapshot() -> dict:
    if not _PACKAGED_PHASES.is_file():
        return {}
    try:
        raw = json.loads(_PACKAGED_PHASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def install_command() -> str:
    """First command of the install fence in docs/getting-started.md.

    Matches "## Install" and numbered headings such as "## 1. Install the tool";
    falls back to the packaged snapshot, then :data:`PIP_INSTALL`.
    """
    if _DOCS_INSTALL.exists():
        text = _DOCS_INSTALL.read_text(encoding="utf-8")
        match = re.search(
            r"^##\s+(?:\d+\.\s*)?Install\b[^\n]*\n\s*```(?:bash|shell|sh)?\s*\n(.*?)```",
            text,
            flags=re.DOTALL | re.MULTILINE,
        )
        if match:
            lines = [
                ln.strip() for ln in match.group(1).splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            if lines:
                return lines[0]
    snap = _packaged_snapshot().get("install")
    if isinstance(snap, str) and snap.strip():
        return snap.strip()
    return PIP_INSTALL


def format_ids() -> list[str]:
    """Canonical adapter ids shown on the landing page (subset of registry)."""
    return sorted(fmt for fmt in KNOWN_FORMATS if resolve_format(fmt) == fmt)


def phase_statuses(*, use_plan: bool = True) -> list[dict[str, str]]:
    """W-01…W-12 from phase file ``**Status:**`` headers (or packaged snapshot)."""
    rows: list[dict[str, str]] = []
    if use_plan and _PHASE_DIR.is_dir():
        for path in sorted(_PHASE_DIR.glob("phase-*.md")):
            match = re.match(r"phase-(\d+)-(.+)\.md$", path.name)
            if not match:
                continue
            num, slug = match.groups()
            text = path.read_text(encoding="utf-8")
            status_m = re.search(r"\*\*Status:\*\*\s*(\w+)", text)
            title_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            status = (status_m.group(1) if status_m else "todo").lower()
            title = title_m.group(1).strip() if title_m else slug.replace("-", " ")
            title = re.sub(r"^W-\d+\s*[—–-]\s*", "", title)
            rows.append({
                "id": f"W-{int(num):02d}",
                "title": title,
                "status": status,
                "done": "yes" if status == "done" else "no",
            })
        return rows
    snap = _packaged_snapshot().get("phases")
    if isinstance(snap, list):
        return [row for row in snap if isinstance(row, dict)]
    return rows


def app_base(app_port: int = DEFAULT_APP_PORT) -> str:
    return f"http://127.0.0.1:{int(app_port)}"


# Public stand-in for the loopback server in exported API samples.
PUBLIC_SERVER = "http://your-host:8770"


def _page_href(site: StaticSite | None, route_id: str) -> str:
    """Link to a marketing page: marketing-port path in-app, base path in the export."""
    if site is not None:
        return site.page(route_id)
    return "/" if route_id == "landing" else f"/{route_id}"


def _editor_cta(site: StaticSite | None, app: str) -> tuple[str, str]:
    """(href, label key) of the 'open the editor' call-to-action.

    In-app it opens the loopback editor; the public export has no server, so it
    points at the getting-started guide instead.
    """
    if site is not None:
        return _DOCS + "/getting-started.md", "mkt_read_docs"
    return f"{app}/app", "mkt_open_editor"


def _public_chrome(
    current_id: str,
    title: str,
    main_html: str,
    *,
    app_port: int = DEFAULT_APP_PORT,
    site: StaticSite | None = None,
) -> str:
    app = app_base(app_port)
    labels = _mkt_labels()
    editor_href, editor_key = _editor_cta(site, app)
    # Landing is one scrolling page; secondary pages link back to those anchors.
    prefix = "" if current_id == "landing" else _page_href(site, "landing")
    nav: list[str] = []
    for href, key in _LANDING_NAV:
        nav.append(
            f'<a class="public-nav-link" href="{escape(prefix + href)}">'
            f"{escape(_t(labels, key))}</a>"
        )
    year = datetime.now(timezone.utc).year
    footer = (
        '<footer class="mkt-footer">'
        '<div class="mkt-wrap mkt-footer-grid">'
        "<div>"
        f'<div class="mkt-footer-brand">{escape(BRAND)}</div>'
        f'<p class="mkt-footer-lede">{escape(_t(labels, "mkt_footer_lede"))}</p>'
        f'<code class="mkt-footer-cmd">{escape(PIP_INSTALL)}</code>'
        "</div>"
        "<div>"
        f'<div class="mkt-footer-head">{escape(_t(labels, "mkt_footer_product"))}</div>'
        '<div class="mkt-footer-links">'
        f'<a href="{escape(prefix)}#features">{escape(_t(labels, "mkt_nav_features"))}</a>'
        f'<a href="{escape(prefix)}#how">{escape(_t(labels, "mkt_nav_how"))}</a>'
        f'<a href="{escape(prefix)}#engines">{escape(_t(labels, "mkt_nav_engines"))}</a>'
        f'<a href="{escape(prefix)}#benchmark">{escape(_t(labels, "mkt_nav_benchmark"))}</a>'
        f'<a href="{escape(prefix)}#formats">{escape(_t(labels, "mkt_nav_formats"))}</a>'
        f'<a href="{escape(_page_href(site, "how-it-works"))}">{escape(_t(labels, "mkt_how_title"))}</a>'
        "</div></div>"
        "<div>"
        f'<div class="mkt-footer-head">{escape(_t(labels, "mkt_footer_links"))}</div>'
        '<div class="mkt-footer-links">'
        f'<a href="{escape(_GITHUB)}" target="_blank" rel="noopener">{escape(_t(labels, "mkt_github"))}</a>'
        f'<a href="{escape(_page_href(site, "roadmap"))}">{escape(_t(labels, "mkt_roadmap"))}</a>'
        f'<a href="{escape(_page_href(site, "api-docs"))}">{escape(_t(labels, "mkt_api_docs"))}</a>'
        f'<a href="{escape(_page_href(site, "tools"))}">{escape(_t(labels, "mkt_free_tools"))}</a>'
        f'<a href="{escape(_GITHUB)}/blob/{_BRANCH}/LICENSE" target="_blank" '
        f'rel="noopener">{escape(_t(labels, "mkt_mit_license"))}</a>'
        "</div></div>"
        "</div>"
        '<div class="mkt-wrap mkt-footer-bar">'
        f"<span>© {year} {escape(BRAND)} contributors. {escape(_t(labels, 'mkt_mit_license'))}.</span>"
        f'<a href="{escape(editor_href)}">{escape(_t(labels, editor_key))}</a>'
        "</div>"
        "</footer>"
    )
    page_title = f"{title} — {BRAND}"
    if site is None:
        head_extra = document_style_links()
    else:
        if current_id == "landing":
            page_title = _t(labels, "mkt_meta_title")
        head_extra = (
            seo_head(
                site, current_id, title=page_title,
                description=_t(labels, "mkt_meta_description"),
                brand=BRAND, repo_url=GITHUB_URL, version=__version__,
            )
            + f'<link rel="stylesheet" href="{escape(site.asset("site.css"))}">'
        )
    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(page_title)}</title>"
        f"{head_extra}"
        "</head>"
        '<body class="public-body mkt-body">'
        '<header class="public-header mkt-header">'
        f'<a class="brand" href="{escape(_page_href(site, "landing"))}">{escape(BRAND)}</a>'
        f'<nav class="public-nav" aria-label="{escape(_t(labels, "mkt_on_this_page"))}">{"".join(nav)}</nav>'
        f'<a class="btn btn-ghost mkt-gh" href="{escape(_GITHUB)}" '
        f'target="_blank" rel="noopener">{escape(_t(labels, "mkt_github"))}</a>'
        f'<a class="btn btn-primary public-open" href="{escape(editor_href)}">'
        f'{escape(_t(labels, editor_key))}</a>'
        "</header>"
        f"{main_html}"
        f"{footer}"
        "</body>"
        "</html>"
    )


def render_landing(*, app_port: int = DEFAULT_APP_PORT, site: StaticSite | None = None) -> str:
    labels = _mkt_labels()
    formats = format_ids()
    n_formats = len(formats)
    cmd = install_command()
    app = app_base(app_port)
    editor_href, editor_key = _editor_cta(site, app)
    shown_app = app if site is None else _t(labels, "mkt_web_opens")

    format_cells = "".join(
        f'<div class="mkt-format-cell" data-format="{escape(fmt)}">'
        f'<div class="mkt-format-id">{escape(fmt)}</div>'
        f'<div class="mkt-format-blurb">{escape(_t(labels, FORMAT_BLURBS[fmt]) if fmt in FORMAT_BLURBS else "")}</div>'
        "</div>"
        for fmt in formats
    )
    feature_html = "".join(
        f'<li class="feature-card card mkt-feature">'
        f'<div class="card-kicker">{escape(num)}</div>'
        f'<div class="card-title">{escape(_t(labels, title_key))}</div>'
        f'<div class="card-body">{escape(_t(labels, body_key))}</div></li>'
        for num, title_key, body_key in _LANDING_FEATURES
    )
    how_steps = (
        ("01", "mkt_how_01_t", "mkt_how_01_b", "mkt_how_01_c"),
        ("02", "mkt_how_02_t", "mkt_how_02_b", "mkt_how_02_c"),
        ("03", "mkt_how_03_t", "mkt_how_03_b", "mkt_how_03_c"),
        ("04", "mkt_how_04_t", "mkt_how_04_b", "mkt_how_04_c"),
    )
    how_html = "".join(
        '<div class="mkt-how-card">'
        f'<div class="mkt-how-num">{escape(num)}</div>'
        f'<div class="mkt-how-title">{escape(_t(labels, title_key))}</div>'
        f'<p class="mkt-how-body">{escape(_t(labels, body_key))}</p>'
        f'<div class="mkt-how-cmd">{escape(_t(labels, cmd_key))}</div>'
        "</div>"
        for num, title_key, body_key, cmd_key in how_steps
    )
    cta_points = ("mkt_cta_1", "mkt_cta_2", "mkt_cta_3", "mkt_cta_4")
    n_engines = len(builtin_engines())
    cta_html = "".join(
        f'<div class="mkt-cta-point"><span class="mkt-check" aria-hidden="true">'
        f"</span><span>{escape(_t(labels, key))}</span></div>"
        for key in cta_points
    )
    reqs = ("mkt_req_1", "mkt_req_2", "mkt_req_3")
    reqs_html = "".join(
        f'<div class="mkt-req"><span class="mkt-check accent" aria-hidden="true">'
        f"</span>{escape(_t(labels, key))}</div>"
        for key in reqs
    )
    # Commands only: no invented catalogue counts (W-11).
    transcript = "\n".join((
        "$ llm-localizator init .",
        "$ llm-localizator agent-hardcoded",
        "$ llm-localizator engine recommend",
        "$ llm-localizator engine apply local-8gb",
        "$ llm-localizator translate --locales de,pl",
        "$ llm-localizator validate",
        "$ llm-localizator web",
        f"  → {shown_app}",
    ))
    quick_start = "\n".join((
        f"# 1. {_t(labels, 'mkt_qs_install')}",
        f"$ {PIP_INSTALL}",
        "",
        f"# 2. {_t(labels, 'mkt_qs_project')}",
        "$ cd my-app",
        "$ llm-localizator init",
        "",
        f"# 3. {_t(labels, 'mkt_qs_find')}",
        "$ llm-localizator agent-hardcoded",
        "",
        f"# 4. {_t(labels, 'mkt_qs_validate')}",
        "$ llm-localizator validate",
        "",
        f"# 5. {_t(labels, 'mkt_qs_engine')}",
        "$ llm-localizator engine recommend",
        "$ llm-localizator translate --locales de,pl",
        "",
        f"# 6. {_t(labels, 'mkt_qs_review')}",
        "$ llm-localizator web",
        f"  → {shown_app}",
    ))

    main = (
        '<main class="mkt-main" id="landing" data-page="landing">'
        '<section class="mkt-hero">'
        '<div class="mkt-wrap hero-grid">'
        "<div>"
        f'<p class="kicker mkt-badge">{escape(_t(labels, "mkt_badge_oss"))}</p>'
        f'<h1>{escape(_t(labels, "mkt_hero_h1_a"))}<span>{escape(_t(labels, "mkt_hero_h1_b"))}</span> '
        f'<span class="accent">{escape(_t(labels, "mkt_hero_h1_c"))}</span></h1>'
        f'<p class="lede">{escape(_t(labels, "mkt_hero_lede"))}</p>'
        f'<pre class="install-cmd"><code>{escape(cmd)}</code></pre>'
        '<div class="mkt-hero-actions">'
        f'<a class="btn btn-primary" href="{escape(_GITHUB)}" target="_blank" '
        f'rel="noopener">{escape(_t(labels, "mkt_view_github"))}</a>'
        f'<a class="btn btn-ghost" href="{escape(editor_href)}">{escape(_t(labels, "mkt_live_demo_arrow" if site is None else editor_key))}</a>'
        "</div>"
        f'<p class="public-meta">{escape(_t(labels, "mkt_package"))} '
        f'<span data-version="{escape(__version__)}">'
        f"v{escape(__version__)}</span></p>"
        "</div>"
        '<div class="mkt-terminal card">'
        f'<div class="mkt-terminal-bar">{escape(_t(labels, "mkt_terminal"))}</div>'
        f'<pre class="mkt-terminal-body"><code>{escape(transcript)}</code></pre>'
        "</div>"
        "</div>"
        "</section>"
        f'<section class="mkt-stats" aria-label="{escape(_t(labels, "mkt_highlights"))}">'
        '<div class="mkt-wrap mkt-stats-grid">'
        '<div class="mkt-stat">'
        f'<div class="mkt-stat-num accent">{n_formats}</div>'
        f'<div class="mkt-stat-label">{escape(_t(labels, "mkt_stat_formats"))}</div>'
        "</div>"
        '<div class="mkt-stat">'
        f'<div class="mkt-stat-num">{n_engines}</div>'
        f'<div class="mkt-stat-label">{escape(_t(labels, "mkt_stat_engines"))}</div>'
        "</div>"
        '<div class="mkt-stat">'
        '<div class="mkt-stat-num">MIT</div>'
        f'<div class="mkt-stat-label">{escape(_t(labels, "mkt_stat_license"))}</div>'
        "</div>"
        "</div>"
        "</section>"
        '<section class="mkt-section" id="features">'
        '<div class="mkt-wrap">'
        '<div class="mkt-section-head">'
        "<div>"
        f'<span class="kicker">{escape(_t(labels, "mkt_nav_features"))}</span>'
        f'<h2>{escape(_t(labels, "mkt_features_h2"))}</h2>'
        "</div>"
        f'<p class="lede">{escape(_t(labels, "mkt_features_lede"))}</p>'
        "</div>"
        f'<ul class="feature-grid mkt-feature-grid">{feature_html}</ul>'
        "</div>"
        "</section>"
        '<section class="mkt-section mkt-section-alt" id="how">'
        '<div class="mkt-wrap">'
        f'<span class="kicker">{escape(_t(labels, "mkt_nav_how"))}</span>'
        f'<h2>{escape(_t(labels, "mkt_how_h2"))}</h2>'
        f'<div class="mkt-how-grid">{how_html}</div>'
        "</div>"
        "</section>"
        f"{engines_section(labels)}"
        f"{bench_section(labels, _DOCS)}"
        '<section class="mkt-section" id="formats">'
        '<div class="mkt-wrap">'
        f'<span class="kicker">{escape(_t(labels, "mkt_formats_kicker"))}</span>'
        f'<div class="mkt-format-grid">{format_cells}</div>'
        f'<p class="lede">{escape(_t(labels, "mkt_formats_lede"))}</p>'
        "</div>"
        "</section>"
        '<section class="mkt-section mkt-section-alt" id="install">'
        '<div class="mkt-wrap mkt-install-grid">'
        "<div>"
        f'<span class="kicker">{escape(_t(labels, "mkt_get_started"))}</span>'
        f'<h2>{escape(_t(labels, "mkt_install_h2"))}</h2>'
        f'<p class="lede">{escape(_t(labels, "mkt_install_lede"))}</p>'
        f'<div class="mkt-reqs">{reqs_html}</div>'
        f'<a class="btn btn-primary" href="{escape(_GITHUB)}" target="_blank" '
        f'rel="noopener">{escape(_t(labels, "mkt_star_github"))}</a>'
        "</div>"
        '<div class="mkt-terminal card">'
        f'<div class="mkt-terminal-bar">{escape(_t(labels, "mkt_quick_start"))}</div>'
        f'<pre class="mkt-terminal-body"><code>{escape(quick_start)}</code></pre>'
        "</div>"
        "</div>"
        "</section>"
        '<section class="mkt-cta">'
        '<div class="mkt-wrap mkt-cta-grid">'
        "<div>"
        f'<h2>{escape(_t(labels, "mkt_cta_h2"))}</h2>'
        f'<p class="mkt-cta-lede">{escape(_t(labels, "mkt_cta_lede"))}</p>'
        '<div class="mkt-hero-actions">'
        f'<a class="btn btn-on-accent" href="{escape(_GITHUB)}" target="_blank" '
        f'rel="noopener">{escape(_t(labels, "mkt_view_github_arrow"))}</a>'
        f'<a class="btn btn-ghost-on-accent" href="{escape(editor_href)}">'
        f'{escape(_t(labels, "mkt_try_demo" if site is None else editor_key))}</a>'
        "</div>"
        "</div>"
        f'<div class="mkt-cta-points">{cta_html}</div>'
        "</div>"
        "</section>"
        "</main>"
    )
    return _public_chrome("landing", "Landing", main, app_port=app_port, site=site)


def render_how_it_works(*, app_port: int = DEFAULT_APP_PORT, site: StaticSite | None = None) -> str:
    labels = _mkt_labels()
    steps = "".join(
        f'<li class="pipeline-step card"><h2>{escape(_t(labels, title_key))}</h2>'
        f"<p>{escape(_t(labels, body_key))}</p></li>"
        for title_key, body_key in _PIPELINE_STEPS
    )
    href, key = _editor_cta(site, app_base(app_port))
    if site is None:
        key = "mkt_open_review"
    main = (
        '<main class="public-main" id="how-it-works" data-page="how-it-works">'
        f'<h1>{escape(_t(labels, "mkt_how_title"))}</h1>'
        f'<p class="lede">{escape(_t(labels, "mkt_how_sub"))}</p>'
        f'<ol class="pipeline-list">{steps}</ol>'
        f'<p><a class="btn btn-primary" href="{escape(href)}">'
        f'{escape(_t(labels, key))}</a></p>'
        "</main>"
    )
    return _public_chrome(
        "how-it-works", _t(labels, "mkt_how_title"), main, app_port=app_port, site=site,
    )


def render_roadmap(*, app_port: int = DEFAULT_APP_PORT, site: StaticSite | None = None) -> str:
    # Public roadmap from marketing_content/roadmap.json in both modes; the
    # internal W-01..W-12 phases stay available through phase_statuses().
    labels = _mkt_labels()
    main = (
        '<main class="public-main" id="roadmap" data-page="roadmap">'
        f'<h1>{escape(_t(labels, "mkt_roadmap"))}</h1>'
        f'<p class="lede">{escape(_t(labels, "mkt_roadmap_lede"))}</p>'
        f"{roadmap_list(labels)}"
        "</main>"
    )
    return _public_chrome(
        "roadmap", _t(labels, "mkt_roadmap"), main, app_port=app_port, site=site,
    )


def _api_code(text: str) -> str:
    """Escape a sample and colour keys, strings, numbers and // comments."""
    tokens = re.compile(
        r'(?P<c>//[^\n]*)|(?P<k>"[^"\n]*"(?=\s*:))|(?P<s>"[^"\n]*"|\'[^\'\n]*\')'
        r"|(?P<v>\b(?:true|false|null|\d+(?:\.\d+)?)\b)"
    )
    out: list[str] = []
    pos = 0
    for m in tokens.finditer(text):
        out.append(escape(text[pos:m.start()]))
        out.append(f'<span class="{m.lastgroup}">{escape(m.group())}</span>')
        pos = m.end()
    out.append(escape(text[pos:]))
    return f'<pre class="api-code"><code>{"".join(out)}</code></pre>'


def _api_label(text: str) -> str:
    return f'<div class="api-label">{escape(text)}</div>'


def _api_method(method: str) -> str:
    return f'<span class="api-method {escape(method.lower())}">{escape(method)}</span>'


def render_api_docs(*, app_port: int = DEFAULT_APP_PORT, site: StaticSite | None = None) -> str:
    labels = _mkt_labels()
    base = app_base(app_port) if site is None else PUBLIC_SERVER
    grouped: dict[str, list[tuple[str, str, str]]] = {g: [] for g in API_GROUP_ORDER}
    for route in API_ROUTES:
        grouped[api_group(route[1])].append(route)

    side: list[str] = []
    quick: list[str] = []
    for group, routes in grouped.items():
        if not routes:
            continue
        side.append(f'<div class="api-side-head">{escape(group)}</div>')
        quick.append(
            f'<tr class="api-group-row"><th colspan="3">{escape(group)}</th></tr>'
        )
        for method, path, purpose in routes:
            anchor = api_anchor(method, path)
            # Only endpoints with a detail section get an anchor link.
            if (method, path) in API_DETAILS:
                side.append(
                    f'<a class="api-side-link" href="#{anchor}">'
                    f"{_api_method(method)}<span>{escape(path)}</span></a>"
                )
                path_cell = (
                    f'<a class="api-path" href="#{anchor}" '
                    f'data-api-path="{escape(path)}">{escape(path)}</a>'
                )
            else:
                path_cell = (
                    f'<code class="api-path" data-api-path="{escape(path)}">'
                    f"{escape(path)}</code>"
                )
            quick.append(
                "<tr>"
                f"<td>{_api_method(method)}</td>"
                f"<td>{path_cell}</td>"
                f"<td>{escape(purpose)}</td>"
                "</tr>"
            )

    purposes = {(m, p): t for m, p, t in API_ROUTES}
    details: list[str] = []
    for (method, path), info in API_DETAILS.items():
        head = (
            '<div class="api-endpoint-head">'
            f"{_api_method(method)}<code>{escape(path)}</code>"
            f"<span>{escape(purposes.get((method, path), ''))}</span></div>"
        )
        left: list[str] = []
        if info.get("params"):
            rows = "".join(
                f"<tr><td><code>{escape(n)}</code></td><td>{escape(d)}</td></tr>"
                for n, d in info["params"]
            )
            left.append(
                _api_label(_t(labels, "mkt_api_query_params"))
                + f'<table class="api-params">{rows}</table>'
            )
        def sample(text: str) -> str:
            # The export has no loopback server; samples name a placeholder host.
            return text if site is None else text.replace(app_base(), PUBLIC_SERVER)

        left.append(_api_label(_t(labels, "mkt_api_example_req")) + _api_code(sample(info["request"])))
        right = [_api_label(_t(labels, "mkt_api_response")) + _api_code(sample(info["response"]))]
        if info.get("note"):
            right.append(f'<div class="api-note">{sample(info["note"])}</div>')
        details.append(
            f'<section class="api-endpoint" id="{api_anchor(method, path)}">'
            f'{head}<div class="api-cols"><div>{"".join(left)}</div>'
            f'<div>{"".join(right)}</div></div></section>'
        )

    chips = (
        ("mkt_api_base_url", base),
        ("mkt_api_auth_header", "X-LLM-Token: <token>"),
        ("mkt_api_content_type", "application/json"),
        ("mkt_api_version", f"v{__version__}"),
    )
    chips_html = "".join(
        f'<div class="api-chip">{_api_label(_t(labels, label_key))}<code>{escape(value)}</code></div>'
        for label_key, value in chips
    )
    main = (
        '<main class="api-docs" id="api-docs" data-page="api-docs">'
        '<header class="api-hero"><div class="mkt-wrap">'
        f'<h1>{escape(_t(labels, "mkt_api_ref"))}</h1>'
        f'<p class="lede">{escape(_t(labels, "mkt_api_lede"))}</p>'
        f'<div class="api-chips">{chips_html}</div>'
        "</div></header>"
        '<div class="mkt-wrap api-layout">'
        f'<aside class="api-side" aria-label="{escape(_t(labels, "mkt_endpoints"))}">'
        f'{"".join(side)}</aside>'
        '<div class="api-content">'
        f'{"".join(details)}'
        '<section class="api-quick">'
        f'{_api_label(_t(labels, "mkt_api_quick"))}'
        '<table class="api-table"><thead><tr>'
        f'<th>{escape(_t(labels, "mkt_th_method"))}</th>'
        f'<th>{escape(_t(labels, "mkt_th_path"))}</th>'
        f'<th>{escape(_t(labels, "mkt_th_desc"))}</th></tr></thead>'
        f'<tbody>{"".join(quick)}</tbody></table>'
        f'<p class="public-meta">{escape(_t(labels, "mkt_see_also"))} '
        f'<code>docs/web.md</code> and <code>docs/cli.md</code> '
        f'{escape(_t(labels, "mkt_in_repo"))}</p>'
        "</section></div></div>"
        "</main>"
    )
    return _public_chrome(
        "api-docs", _t(labels, "mkt_api_docs"), main, app_port=app_port, site=site,
    )


_TOOLS_SCRIPT = r"""
(function () {
  var PRICES = __PRICES__;
  var PH = /\{\{?\s*[\w.]+\s*\}\}?|%(?:\d+\$)?[sdif@]|\$\{[^}]+\}/g;
  function toks(t) { return (t.match(PH) || []).slice().sort(); }
  function diff(a, b) {
    var left = b.slice(), out = [];
    a.forEach(function (x) {
      var i = left.indexOf(x);
      if (i < 0) out.push(x); else left.splice(i, 1);
    });
    return { missing: out, extra: left };
  }
  var src = document.getElementById("tool-src"),
      tgt = document.getElementById("tool-tgt"),
      res = document.getElementById("tool-ph-result");
  function check() {
    var d = diff(toks(src.value), toks(tgt.value));
    if (!src.value && !tgt.value) { res.textContent = ""; return; }
    res.textContent = (d.missing.length || d.extra.length)
      ? "Missing: " + (d.missing.join(" ") || "none") +
        " | Unexpected: " + (d.extra.join(" ") || "none")
      : "Placeholders match.";
  }
  src.addEventListener("input", check);
  tgt.addEventListener("input", check);
  var chars = document.getElementById("tool-chars"),
      model = document.getElementById("tool-model"),
      cost = document.getElementById("tool-cost");
  Object.keys(PRICES).forEach(function (m) {
    var o = document.createElement("option");
    o.value = m; o.textContent = m; model.appendChild(o);
  });
  function price() {
    var p = PRICES[model.value], n = Math.max(0, +chars.value || 0);
    if (!p) { cost.textContent = ""; return; }
    var tok = n / 4;
    var usd = (tok * p[0] + tok * p[1]) / 1e6;
    cost.textContent = "About $" + usd.toFixed(usd < 1 ? 4 : 2) +
      " (" + Math.round(tok) + " tokens in, same out)";
  }
  chars.addEventListener("input", price);
  model.addEventListener("change", price);
  price();
})();
"""


def render_tools(*, app_port: int = DEFAULT_APP_PORT, site: StaticSite | None = None) -> str:
    """Free utility pages: placeholder check and cost calculator, client-side only."""
    from ..catalog.pricing import PRICE_AS_OF, _TOKEN_PRICES

    prices = {
        m: [p.input_per_million, p.output_per_million]
        for m, p in sorted(_TOKEN_PRICES.items())
    }
    script = _TOOLS_SCRIPT.replace(
        "__PRICES__", json.dumps(prices).replace("</", "<" + chr(92) + "/"),
    )
    labels = _mkt_labels()
    main = (
        '<main class="public-main" id="tools" data-page="tools">'
        f'<h1>{escape(_t(labels, "mkt_free_tools"))}</h1>'
        f'<p class="lede">{escape(_t(labels, "mkt_tools_lede"))}</p>'
        f'<section class="card"><h2>{escape(_t(labels, "mkt_placeholder_check"))}</h2>'
        f'<label for="tool-src">{escape(_t(labels, "mkt_tool_source"))}</label>'
        '<textarea id="tool-src" rows="3"></textarea>'
        f'<label for="tool-tgt">{escape(_t(labels, "mkt_tool_translation"))}</label>'
        '<textarea id="tool-tgt" rows="3"></textarea>'
        '<p id="tool-ph-result" role="status"></p></section>'
        f'<section class="card"><h2>{escape(_t(labels, "mkt_cloud_cost"))}</h2>'
        f'<label for="tool-chars">{escape(_t(labels, "mkt_chars_translate"))}</label>'
        '<input id="tool-chars" type="number" min="0" value="10000">'
        f'<label for="tool-model">{escape(_t(labels, "mkt_tool_model"))}</label>'
        '<select id="tool-model"></select>'
        '<p id="tool-cost" role="status"></p>'
        f'<p>{escape(_t(labels, "mkt_tools_prices").format(as_of=PRICE_AS_OF))}</p></section>'
        f"<script>{script}</script>"
        "</main>"
    )
    return _public_chrome(
        "tools", _t(labels, "mkt_free_tools"), main, app_port=app_port, site=site,
    )


_RENDERERS = {
    "tools": render_tools,
    "landing": render_landing,
    "how-it-works": render_how_it_works,
    "roadmap": render_roadmap,
    "api-docs": render_api_docs,
}

# App-port path → marketing path (ADR-45 redirects).
MARKETING_REDIRECTS: dict[str, str] = {
    "/landing": "/",
    "/how-it-works": "/how-it-works",
    "/roadmap": "/roadmap",
    "/api-docs": "/api-docs",
    "/tools": "/tools",
}

# Marketing-port path → renderer id.
MARKETING_ROUTES: dict[str, str] = {
    "/": "landing",
    "/landing": "landing",
    "/how-it-works": "how-it-works",
    "/roadmap": "roadmap",
    "/api-docs": "api-docs",
    "/tools": "tools",
}


def render_public(
    route_id: str, *, app_port: int = DEFAULT_APP_PORT, site: StaticSite | None = None,
) -> str:
    """Render a Public-group page, or raise KeyError."""
    return _RENDERERS[route_id](app_port=app_port, site=site)


# Touch KNOWN_FORMATS so importers can assert format_ids ⊆ registry.
assert set(format_ids()) <= set(KNOWN_FORMATS)
