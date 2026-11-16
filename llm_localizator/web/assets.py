"""Web UI feature flags and the digest source.

The review pages are files under ``web/static``, served with no build step.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "WEB_FEATURES", "document_style_links", "static_cache_control",
    "static_href", "ui_source",
]

_STATIC_DIR = Path(__file__).parent / "static"
_IMMUTABLE = "public, max-age=31536000, immutable"

# Same URLs as the @font-face src in app.css. A query string here would
# miss the stylesheet request and download each face twice.
_FONT_HREFS = (
    "/static/fonts/Barlow-Regular.woff2",
    "/static/fonts/Barlow-SemiBold.woff2",
    "/static/fonts/BarlowCondensed-SemiBold.woff2",
)


def static_href(path: str) -> str:
    """Append the file mtime so an unchanged asset can stay in the HTTP cache.

    Pages are full document loads. Without a stable cacheable URL the browser
    refetches CSS on every navigation and then swaps fonts, which repaints
    the whole shell.
    """
    rel = path.removeprefix("/static/").lstrip("/")
    try:
        token = (_STATIC_DIR / rel).stat().st_mtime_ns
    except OSError:
        return path
    return f"{path}?v={token}"


def document_style_links() -> str:
    """Preload the local faces, then the versioned stylesheet.

    An early inline script applies saved font/theme before CSS paints (FOUC).
    """
    from html import escape

    preloads = "".join(
        f'<link rel="preload" href="{escape(href)}" as="font" '
        'type="font/woff2" crossorigin>'
        for href in _FONT_HREFS
    )
    css = escape(static_href("/static/app.css"))
    fouc = (
        "<script>(function(){try{var f=localStorage.getItem('llm_ui_font')||'current';"
        "var t=localStorage.getItem('llm_ui_theme')||'light';"
        "document.documentElement.setAttribute('data-font',f);"
        "document.documentElement.setAttribute('data-theme',t);"
        "document.documentElement.style.colorScheme=t==='dark'?'dark':'light';"
        "}catch(e){}})();</script>"
    )
    return fouc + preloads + f'<link rel="stylesheet" href="{css}">'


def static_cache_control(path: str, query: str) -> str:
    """Fonts and versioned CSS/JS are immutable. HTML stays no-store elsewhere.

    A bare ``/static/app.css`` (no ``v``) stays revalidated so a direct fetch
    during development is not stuck on a year-long copy.
    """
    if "/fonts/" in path or path.endswith(".woff2"):
        return _IMMUTABLE
    if "v" in parse_query_keys(query):
        return _IMMUTABLE
    return "no-cache"


def parse_query_keys(query: str) -> set[str]:
    keys: set[str] = set()
    for part in query.split("&"):
        if not part:
            continue
        key, _, _value = part.partition("=")
        if key:
            keys.add(key)
    return keys


WEB_FEATURES = (
    "export", "import", "history", "verify", "revert", "ops", "ops_stream",
    "context", "screenshot", "translator_overlay",
)


_ui_source_cache: dict[Path, tuple[tuple, str]] = {}


def _ui_files(root: Path) -> list[Path]:
    return [
        path for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".css", ".js"}
    ]


def ui_source(root: Path | None = None) -> str:
    """Text hashed for ``/api/version`` so a UI edit changes the digest.

    Cached on the (path, mtime_ns) of every asset: a directory mtime does not
    move when a file is edited in place.
    """
    root = root or Path(__file__).parent / "static"
    files = _ui_files(root)
    signature = []
    for path in files:
        try:
            signature.append((str(path), path.stat().st_mtime_ns))
        except OSError:
            signature.append((str(path), 0))
    key = tuple(signature)
    cached = _ui_source_cache.get(root)
    if cached is not None and cached[0] == key:
        return cached[1]
    chunks = [path.read_text(encoding="utf-8") for path in files]
    from .shell import render_shell

    chunks.append(render_shell("editor"))
    result = "\n".join(chunks)
    _ui_source_cache[root] = (key, result)
    return result
