"""Static export of the public marketing pages (GitHub Pages / custom domain).

``scripts/build_site.py`` calls :func:`build_site`. The in-app marketing port
keeps rendering with ``site=None``; a :class:`StaticSite` switches the pages to
public mode: base-path links, public call-to-actions instead of the loopback
editor, a slim stylesheet and no reads from ``plan/``.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_SITE_URL = "https://llm-localizator.dev"

# Renderer id -> path under the base path ("" is the landing page).
PAGE_DIRS: dict[str, str] = {
    "landing": "",
    "how-it-works": "how-it-works/",
    "roadmap": "roadmap/",
    "api-docs": "api-docs/",
    "tools": "tools/",
}

_REPO = Path(__file__).resolve().parents[2]
_APP_CSS = Path(__file__).resolve().parent / "static" / "app.css"
_SOCIAL_PNG = _REPO / "docs" / "assets" / "social.png"
SOCIAL_IMAGE_PATH = "docs/assets/social.png"

_SYSTEM_FONTS = (
    ":root{"
    "--font-body:system-ui,-apple-system,\"Segoe UI\",Roboto,\"Helvetica Neue\",Arial,sans-serif;"
    "--font-heading:system-ui,-apple-system,\"Segoe UI\",Roboto,\"Helvetica Neue\",Arial,sans-serif;"
    "--font-mono:ui-monospace,\"Cascadia Code\",Menlo,Consolas,monospace}\n"
)


@dataclass(frozen=True)
class StaticSite:
    """Public-mode settings for one export."""

    base_path: str = "/"
    site_url: str = DEFAULT_SITE_URL

    def __post_init__(self) -> None:
        base = "/" + self.base_path.strip("/") + "/"
        object.__setattr__(self, "base_path", base.replace("//", "/"))
        object.__setattr__(self, "site_url", self.site_url.rstrip("/"))

    def page(self, route_id: str) -> str:
        """Base-path link to a page (directory index)."""
        return self.base_path + PAGE_DIRS[route_id]

    def asset(self, name: str) -> str:
        return self.base_path + name.lstrip("/")

    def absolute(self, path: str) -> str:
        """Absolute URL of a path relative to the base path."""
        return self.site_url + self.base_path + path.lstrip("/")


# ---- SEO head ----------------------------------------------------------------

#: Icon files shipped with the site (published path -> source under docs/assets/).
ICON_FILES = {
    "docs/assets/favicon.svg": _REPO / "docs" / "assets" / "favicon.svg",
    "docs/assets/apple-touch-icon.png": _REPO / "docs" / "assets" / "apple-touch-icon.png",
    "docs/assets/logo.svg": _REPO / "docs" / "assets" / "logo.svg",
}
FAVICON_PATH = "docs/assets/favicon.svg"
APPLE_ICON_PATH = "docs/assets/apple-touch-icon.png"


def seo_head(
    site: StaticSite, route_id: str, *, title: str, description: str,
    brand: str, repo_url: str, version: str,
) -> str:
    """Meta description, canonical, Open Graph, Twitter card, favicon and JSON-LD."""
    import json
    from html import escape

    url = site.absolute(PAGE_DIRS[route_id])
    image = site.absolute(SOCIAL_IMAGE_PATH)
    ld = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": brand,
        "applicationCategory": "DeveloperApplication",
        "operatingSystem": "Windows, macOS, Linux",
        "softwareVersion": version,
        "license": "https://opensource.org/licenses/MIT",
        "url": site.absolute(""),
        "codeRepository": repo_url,
        "description": description,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    }
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    tags = [
        f'<meta name="description" content="{escape(description)}">',
        f'<link rel="canonical" href="{escape(url)}">',
        f'<link rel="icon" type="image/svg+xml" href="{escape(site.absolute(FAVICON_PATH))}">',
        f'<link rel="apple-touch-icon" href="{escape(site.absolute(APPLE_ICON_PATH))}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{escape(brand)}">',
        f'<meta property="og:title" content="{escape(title)}">',
        f'<meta property="og:description" content="{escape(description)}">',
        f'<meta property="og:url" content="{escape(url)}">',
        f'<meta property="og:image" content="{escape(image)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{escape(title)}">',
        f'<meta name="twitter:description" content="{escape(description)}">',
        f'<meta name="twitter:image" content="{escape(image)}">',
        f'<script type="application/ld+json">{ld_json}</script>',
    ]
    return "".join(tags)


# ---- slim stylesheet ---------------------------------------------------------

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_CLASS = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
_ID = re.compile(r"#(-?[_a-zA-Z][\w-]*)")


def _blocks(css: str) -> list[tuple[str, str]]:
    """Split CSS into top-level ``(prelude, body)`` pairs by brace depth."""
    out: list[tuple[str, str]] = []
    depth = 0
    start = 0
    prelude = ""
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                prelude = css[start:i].strip()
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append((prelude, css[start:i]))
                start = i + 1
    return out


def _keep_selector(sel: str, classes: set[str], ids: set[str]) -> bool:
    sel_classes = set(_CLASS.findall(sel))
    sel_ids = set(_ID.findall(sel))
    if sel_ids - ids:
        return False
    return sel_classes <= classes


def _filter(css: str, classes: set[str], ids: set[str]) -> list[str]:
    kept: list[str] = []
    for prelude, body in _blocks(css):
        if prelude.startswith("@"):
            if prelude.startswith("@media") or prelude.startswith("@supports"):
                inner = _filter(body, classes, ids)
                if inner:
                    kept.append(f"{prelude}{{{''.join(inner)}}}")
            # @font-face, @keyframes, @import: never in the public sheet.
            continue
        selectors = [s.strip() for s in prelude.split(",") if s.strip()]
        live = [s for s in selectors if _keep_selector(s, classes, ids)]
        if live:
            body = re.sub(r"\s+", " ", body).strip()
            kept.append(f"{','.join(live)}{{{body}}}\n")
    return kept


def used_names(pages: dict[str, str]) -> tuple[set[str], set[str]]:
    classes: set[str] = set()
    ids: set[str] = set()
    for html in pages.values():
        for value in re.findall(r'class="([^"]*)"', html):
            classes.update(value.split())
        ids.update(re.findall(r'id="([^"]*)"', html))
    return classes, ids


def slim_css(pages: dict[str, str], source: Path = _APP_CSS) -> str:
    """Only the app.css rules the exported pages use, with system fonts."""
    css = _COMMENT.sub("", source.read_text(encoding="utf-8"))
    classes, ids = used_names(pages)
    rules = _filter(css, classes, ids)
    header = "/* Generated by scripts/build_site.py from the app stylesheet (app.css). */\n"
    return header + "".join(rules) + _SYSTEM_FONTS


# ---- export ------------------------------------------------------------------


def render_pages(site: StaticSite) -> dict[str, str]:
    from .marketing import MARKETING_ROUTES, render_public

    route_ids = list(dict.fromkeys(MARKETING_ROUTES.values()))
    return {rid: render_public(rid, site=site) for rid in route_ids}


def _sitemap(site: StaticSite, route_ids: list[str]) -> str:
    urls = "".join(
        f"<url><loc>{site.absolute(PAGE_DIRS[rid])}</loc></url>" for rid in route_ids
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>\n"
    )


def build_site(out: Path, site: StaticSite) -> list[Path]:
    """Write the public site into ``out``; returns the files written."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pages = render_pages(site)
    written: list[Path] = []

    def write(rel: str, text: str) -> None:
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)

    for rid, html in pages.items():
        write(PAGE_DIRS[rid] + "index.html", html)
    write("site.css", slim_css(pages))
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site.absolute('sitemap.xml')}\n")
    write("sitemap.xml", _sitemap(site, list(pages)))
    write(".nojekyll", "")
    host = urlsplit(site.site_url).hostname or ""
    if host and not host.endswith("github.io") and site.base_path == "/":
        write("CNAME", host + "\n")
    assets = {SOCIAL_IMAGE_PATH: _SOCIAL_PNG, **ICON_FILES}
    for rel, source in assets.items():
        if source.is_file():
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            written.append(target)
    return written
