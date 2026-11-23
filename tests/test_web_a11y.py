"""Accessibility scaffolding of the web shell: skip link, live-region script, reduced motion."""

from __future__ import annotations

import re
from pathlib import Path

from llm_localizator.web.server_logic import _SHELL_STATIC, _SHELL_STATIC_DIR
from llm_localizator.web.shell import render_shell

CSS = (Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "app.css").read_text(encoding="utf-8")


def test_shell_has_a_skip_link_to_the_page_body_and_loads_the_a11y_script() -> None:
    html = render_shell("dashboard")
    assert re.search(r'<a class="skip-link" href="#page-body"', html)
    assert 'id="page-body"' in html
    assert "/static/a11y.js" in html


def test_a11y_script_is_served_and_announces_through_a_polite_live_region() -> None:
    name, ctype = _SHELL_STATIC["/static/a11y.js"]
    assert ctype.startswith("application/javascript")
    source = (_SHELL_STATIC_DIR / name).read_text(encoding="utf-8")
    assert 'aria-live", "polite"' in source and "window.LLMA11y" in source


def test_stylesheet_honours_reduced_motion_and_has_screen_reader_only_text() -> None:
    assert "prefers-reduced-motion: reduce" in CSS
    assert ".sr-only" in CSS and ".skip-link:focus" in CSS
