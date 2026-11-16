"""Static export of the public marketing site (scripts/build_site.py)."""

from __future__ import annotations

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from llm_localizator.web.marketing import render_landing
from llm_localizator.web.static_site import PAGE_DIRS, StaticSite, build_site

ROOT = Path(__file__).resolve().parents[2]
SITE_URL = "https://llm-localizator.dev"


class _Refs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.refs.append(value)


def _refs(html: str) -> list[str]:
    parser = _Refs()
    parser.feed(html)
    return parser.refs


@pytest.fixture(scope="module", params=["/", "/llm_localizator/"])
def built(request, tmp_path_factory) -> tuple[Path, StaticSite]:
    site = StaticSite(base_path=request.param, site_url=SITE_URL)
    out = tmp_path_factory.mktemp("site")
    build_site(out, site)
    return out, site


def _pages(out: Path) -> dict[str, str]:
    return {
        rid: (out / rel / "index.html").read_text(encoding="utf-8")
        for rid, rel in PAGE_DIRS.items()
    }


def test_every_page_and_support_file_is_written(built) -> None:
    out, site = built
    for rel in PAGE_DIRS.values():
        assert (out / rel / "index.html").is_file()
    for name in ("site.css", "robots.txt", "sitemap.xml", ".nojekyll"):
        assert (out / name).is_file(), name
    cname = out / "CNAME"
    if site.base_path == "/":
        assert cname.read_text(encoding="utf-8").strip() == "llm-localizator.dev"
    else:
        assert not cname.exists()
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert f"<loc>{SITE_URL}{site.base_path}roadmap/</loc>" in sitemap


def test_no_loopback_targets(built) -> None:
    out, _site = built
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".css", ".xml", ".txt"}:
            text = path.read_text(encoding="utf-8")
            assert "127.0.0.1" not in text, path
            assert "localhost" not in text, path
            assert "/static/" not in text, path
            assert "fonts.googleapis" not in text, path


def test_internal_links_resolve(built) -> None:
    out, site = built
    for rid, html in _pages(out).items():
        ids = set(re.findall(r'id="([^"]+)"', html))
        for ref in _refs(html):
            parts = urlsplit(ref)
            if parts.scheme == "data":
                continue
            if parts.scheme in {"http", "https"}:
                assert parts.hostname not in {"127.0.0.1", "localhost"}, ref
                continue
            if ref.startswith("#"):
                assert ref[1:] in ids, f"{rid}: dangling anchor {ref}"
                continue
            assert ref.startswith(site.base_path), f"{rid}: {ref} ignores base path"
            rel = parts.path[len(site.base_path):]
            target = out / rel
            if rel == "" or rel.endswith("/"):
                target = target / "index.html"
            assert target.is_file(), f"{rid}: {ref} -> {target}"
            if parts.fragment:
                assert f'id="{parts.fragment}"' in target.read_text(encoding="utf-8"), ref


def test_slim_css_is_slim() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        build_site(Path(tmp), StaticSite())
        css = (Path(tmp) / "site.css").read_text(encoding="utf-8")
    app = (ROOT / "llm_localizator" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert len(css) < len(app) / 3
    assert ".mkt-hero" in css
    assert "@font-face" not in css
    assert "--font-body:system-ui" in css


def test_in_app_render_keeps_loopback_editor() -> None:
    html = render_landing(app_port=8770)
    assert 'href="http://127.0.0.1:8770/app"' in html
    assert "/static/app.css" in html


def test_build_script_cli(tmp_path) -> None:
    out = tmp_path / "site"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_site.py"), "--out", str(out),
         "--base-path", "llm_localizator", "--site-url", "https://example.github.io"],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="/llm_localizator/site.css"' in html
    assert not (out / "CNAME").exists()


def test_pages_workflow_builds_the_site() -> None:
    text = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "python scripts/build_site.py" in text
    assert "upload-pages-artifact" in text
    assert "deploy-pages" in text
