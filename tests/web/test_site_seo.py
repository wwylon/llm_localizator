"""SEO and accessibility of the exported public site (site P3)."""

from __future__ import annotations

import json
import re

import pytest

from llm_localizator.web.marketing import render_landing
from llm_localizator.web.static_site import PAGE_DIRS, SOCIAL_IMAGE_PATH, StaticSite, build_site

SITE_URL = "https://llm-localizator.dev"


@pytest.fixture(scope="module", params=["/", "/llm_localizator/"])
def built(request, tmp_path_factory):
    site = StaticSite(base_path=request.param, site_url=SITE_URL)
    out = tmp_path_factory.mktemp("seo")
    build_site(out, site)
    pages = {rid: (out / rel / "index.html").read_text(encoding="utf-8") for rid, rel in PAGE_DIRS.items()}
    return out, site, pages


def test_landing_title(built) -> None:
    _out, _site, pages = built
    assert "<title>llm-localizator — find hardcoded strings &amp; localize with AI</title>" in pages["landing"]


def test_required_meta_tags(built) -> None:
    out, site, pages = built
    for rid, html in pages.items():
        assert '<html lang="en">' in html, rid
        assert re.search(r'<meta name="description" content="[^"]{50,}">', html), rid
        canonical = site.absolute(PAGE_DIRS[rid])
        assert f'<link rel="canonical" href="{canonical}">' in html, rid
        assert f'<meta property="og:url" content="{canonical}">' in html, rid
        for prop in ("og:title", "og:description", "og:type", "og:image"):
            assert f'property="{prop}"' in html, (rid, prop)
        for name in ("twitter:card", "twitter:title", "twitter:image"):
            assert f'name="{name}"' in html, (rid, name)
        image = site.absolute(SOCIAL_IMAGE_PATH)
        assert image.startswith("https://")
        assert f'<meta property="og:image" content="{image}">' in html
        assert 'rel="icon"' in html
    assert (out / SOCIAL_IMAGE_PATH).read_bytes().startswith(b"\x89PNG")


def test_json_ld_software_application(built) -> None:
    _out, _site, pages = built
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', pages["landing"], re.DOTALL)
    assert match
    data = json.loads(match.group(1))
    assert data["@type"] == "SoftwareApplication"
    assert data["name"] == "llm-localizator"
    assert data["codeRepository"] == "https://github.com/wwylon/llm_localizator"


def test_heading_order_and_alt_text(built) -> None:
    _out, _site, pages = built
    for rid, html in pages.items():
        levels = [int(n) for n in re.findall(r"<h([1-6])[\s>]", html)]
        assert levels and levels[0] == 1, rid
        assert levels.count(1) == 1, rid
        for prev, cur in zip(levels, levels[1:]):
            assert cur <= prev + 1, f"{rid}: h{prev} -> h{cur}"
        for img in re.findall(r"<img\b[^>]*>", html):
            assert re.search(r'\balt="[^"]*"', img), (rid, img)


def test_in_app_head_has_no_public_seo_tags() -> None:
    html = render_landing()
    assert 'rel="canonical"' not in html
    assert "application/ld+json" not in html
