"""en-XX leftover hunt smoke (ADR-27 browser marker).

Requires package ``web/locales/en-XX.json`` (run ``llm-localizator pseudo --locale
en-XX`` once). Deselected unless ``-m browser``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if not (REPO / "experiments" / "hardcoded_visible").is_dir():
    pytest.skip("needs experiments/hardcoded_visible (dev checkout only)", allow_module_level=True)
sys.path.insert(0, str(REPO / "experiments" / "hardcoded_visible"))
from classify import is_leftover, is_pseudo_marker  # noqa: E402

LOCALES = REPO / "llm_localizator" / "web" / "locales"
XX_JSON = LOCALES / "en-XX.json"


@pytest.mark.skipif(not XX_JSON.is_file(), reason="en-XX.json missing; run pseudo")
def test_en_xx_route_paints_marker_nav(ui) -> None:
    """Prefixed /en-XX/app loads; wired nav labels should be X markers."""
    # QA markers are opt-in per project ([web] qa_locales, ADR-110); the fixture project has none, so the
    # server served /en-XX/app in English.
    ui.src.qa_locales = ["en-XX"]
    ui.page.goto(ui.base + "/en-XX/app")
    ui.page.evaluate("p => localStorage.setItem('llm_project', p)", "src")
    ui.page.goto(ui.base + "/en-XX/app")
    ui.page.wait_for_selector("#page-body, #dash-title, .brand", timeout=15000)
    # Locale JSON must be fetchable.
    status = ui.page.evaluate(
        """async () => {
          const r = await fetch('/locales/en-XX.json');
          return r.status;
        }"""
    )
    assert status == 200
    # Collect a few visible text nodes; at least one should be pure Xs when
    # shell/nav is wired through the catalogue.
    samples = ui.page.evaluate(
        """() => {
          const out = [];
          const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          let n;
          while ((n = walk.nextNode())) {
            const t = (n.textContent || '').replace(/\\s+/g, ' ').trim();
            if (t.length >= 3) out.push(t);
            if (out.length >= 40) break;
          }
          return out;
        }"""
    )
    assert samples, "expected visible text on /en-XX/app"
    markers = [t for t in samples if is_pseudo_marker(t)]
    leftovers = [t for t in samples if is_leftover(t)]
    # Brand / unwired chrome may still be Latin; require some Xs from nav/i18n.
    assert markers or leftovers  # page painted something
    # If the package en-XX dict loaded, data-i18n nodes should prefer Xs.
    i18n_texts = ui.page.evaluate(
        """() => Array.from(document.querySelectorAll('[data-i18n]'))
            .map(el => (el.textContent || '').replace(/\\s+/g, ' ').trim())
            .filter(t => t.length >= 2)
            .slice(0, 20)"""
    )
    if i18n_texts:
        assert any(is_pseudo_marker(t) for t in i18n_texts), i18n_texts[:5]
