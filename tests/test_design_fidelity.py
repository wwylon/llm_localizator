"""Chrome fidelity checks for the W-01–W-12 visual pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.web.shell import render_shell

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "llm_localizator" / "web" / "static" / "app.css"
FONTS = ROOT / "llm_localizator" / "web" / "static" / "fonts"


def test_app_css_has_no_google_fonts_and_industry_accent() -> None:
    text = CSS.read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in text
    assert "70vh" not in text
    assert "--color-accent: #5980a6" in text
    assert "@font-face" in text
    assert "Barlow-Regular.woff2" in text
    assert "font-size: calc(13px * var(--ui-font-scale))" in text
    assert "--color-panel:" in text
    assert "width: 200px" in text
    assert ".tab-btn" in text
    assert ".tab-panel" in text
    assert ".auth-shell" in text
    assert ".counts" in text
    assert "grid-template-columns: repeat(4, 1fr)" in text
    assert ".main.is-editor" in text
    # Never ship Modernist red.
    assert "#ec3013" not in text
    assert "radial-gradient" not in text
    btn = text[text.index(".btn {"):text.index(".btn-primary")]
    assert "border-radius: 0" in btn
    brand = text[text.index(".brand {"):text.index(".brand-mark")]
    assert "text-transform: uppercase" in brand
    assert "var(--font-heading)" in brand
    public = text[text.index(".public-body"):text.index(".public-header")]
    assert "var(--color-bg)" in public
    assert ".card::before" in text
    assert ".btn-primary::before" in text
    marks = text[text.index(".card::before"):text.index(".public-header")]
    assert "inset: -1px" in marks
    badge = text[text.index(".nav-badge"):text.index(".shell-footer")]
    assert "border-radius: 0" in badge
    feature = text[text.index(".feature-card {"):text.index(".feature-card h3")]
    assert "position: relative" in feature
    assert ".cmd-btn" in text
    assert ".op-form-card" in text
    assert ".op-log-body" in text
    assert "#0d1117" in text


def test_local_barlow_fonts_exist() -> None:
    assert (FONTS / "Barlow-Regular.woff2").is_file()
    assert (FONTS / "Barlow-SemiBold.woff2").is_file()
    assert (FONTS / "BarlowCondensed-SemiBold.woff2").is_file()


def test_shell_nav_has_icons_and_tab_scripts() -> None:
    html = render_shell("dashboard", "tok")
    assert 'class="nav-icon"' in html
    assert "<svg" in html
    assert 'stroke-width="1.5"' in html
    assert 'id="shell-user"' in html
    assert "Dashboard" in html
    tm = render_shell("tm", "tok")
    assert "/static/tm.js" in tm
    assert 'id="tm-sub"' in tm
    assert "page-head-tm" in tm
    assert 'id="tm-import-btn"' in tm
    assert 'id="tm-export-btn"' in tm
    eval_html = render_shell("model-eval", "tok")
    assert "/static/model-eval.js" in eval_html
    glossary = render_shell("glossary", "tok")
    assert 'class="main is-compact"' in glossary
    assert 'id="glossary-sub"' in glossary
    assert "page-head-glossary" in glossary
    operations = render_shell("operations", "tok")
    assert 'class="main is-compact"' in operations
    assert 'data-route="login"' not in html
    assert 'data-route="users"' in html


@pytest.mark.skipif(not (ROOT / "plan" / "design" / "1").is_dir(), reason="needs plan/design (private checkout only)")
def test_how_it_works_mockup_is_not_the_pipeline_sketch() -> None:
    design = ROOT / "plan" / "design" / "1"
    page = (design / "how-it-works.dc.html").read_text(encoding="utf-8")
    assert "Discover" in page
    assert "1518" not in page
    assert not (design / "flow-diagram.dc.html").exists()
    sketch = design / "_ref-flow-diagram.dc.html"
    assert sketch.is_file()
    assert "how-it-works.dc.html" in sketch.read_text(encoding="utf-8")


def test_editor_uses_dense_main() -> None:
    html = render_shell("editor", "tok")
    assert 'class="main is-editor is-compact"' in html
    assert 'id="ops-btn"' not in html
    assert "/static/editor.js" in html
    assert "<h1>Translations</h1>" not in html


def test_auth_pages_use_split_layout_without_sidebar() -> None:
    html = render_shell("login", "tok")
    assert 'class="auth-shell"' in html
    assert 'class="sidebar"' not in html
    assert "/static/auth.js" in html
    assert 'data-page="login"' in html
    reg = render_shell("register", "tok")
    assert 'class="auth-shell"' in reg
