"""Public marketing copy: engines, benchmark, formats, install, roadmap (site P2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from llm_localizator.engines import STATUSES
from llm_localizator.web.marketing import (
    BRAND, GITHUB_URL, PIP_INSTALL, format_ids, install_command, render_landing, render_public,
)
from llm_localizator.web.marketing_sections import (
    BENCH_STATS, FORMAT_BLURBS, builtin_engines, roadmap_items,
)
from llm_localizator.web.static_site import StaticSite

ROOT = Path(__file__).resolve().parents[2]
EN = json.loads((ROOT / "llm_localizator" / "web" / "locales" / "en.json").read_text(encoding="utf-8"))
PAGES = ("landing", "how-it-works", "roadmap", "api-docs", "tools")


def test_install_command_reads_numbered_heading() -> None:
    assert install_command() == PIP_INSTALL == "pip install llm_localizator"


def test_no_page_installs_the_unrelated_pypi_project() -> None:
    for rid in PAGES:
        for site in (None, StaticSite()):
            html = render_public(rid, site=site)
            assert "pip install llm-localizator" not in html, rid
            assert "llm·localizator" not in html, rid


def test_every_format_has_a_blurb() -> None:
    assert set(format_ids()) == set(FORMAT_BLURBS)
    for key in FORMAT_BLURBS.values():
        assert EN.get(key), key
    html = render_landing()
    assert 'class="mkt-format-blurb"></div>' not in html


def test_engines_table_comes_from_builtin_files() -> None:
    engines = builtin_engines()
    ids = {e.id for e in engines}
    assert {"claude-haiku", "deepseek", "openai", "local-4gb", "local-8gb"} <= ids
    assert all(e.source == "builtin" for e in engines)
    html = render_landing()
    for e in engines:
        assert f'data-engine="{e.id}" data-status="{e.status}"' in html
    for status in STATUSES:
        assert EN.get(f"mkt_engine_status_{status}"), status
    assert "$0.12 per 2,300-key locale sweep" in html  # claude-haiku summary, not invented copy


def test_benchmark_is_honest_and_matches_docs() -> None:
    docs = (ROOT / "docs" / "scanners.md").read_text(encoding="utf-8")
    assert "Macro precision 0.91, macro recall 0.34" in docs
    assert "Twelve projects" in docs
    nums = {key: num for num, key in BENCH_STATS}
    assert nums == {"mkt_bench_precision": "0.91", "mkt_bench_projects": "12", "mkt_bench_recall": "0.34"}
    html = render_landing()
    assert 'id="benchmark"' in html
    assert "real open-source projects" in html
    assert "every hardcoded" not in html.lower()
    # 0.34 recall means it finds about a third (docs: "finds about a third").
    assert "finds about a third" in html
    assert "a third of labelled text" not in html
    assert "unusual text storage" in html


def test_local_only_messaging_is_gone() -> None:
    html = render_landing()
    assert "Runs on Ollama" not in html
    assert "cloud dependencies" not in html
    assert "nothing leaves your machine unless you pick a cloud engine" in html
    assert "Python 3.12" in html
    assert "Ollama optional" in html
    assert "Python 3.11" not in html


def test_brand_and_repo_constants() -> None:
    assert BRAND == "llm-localizator"
    assert GITHUB_URL == "https://github.com/wwylon/llm_localizator"
    html = render_landing()
    assert f'class="brand" href="/">{BRAND}</a>' in html
    assert "github.com/<owner>" not in html


def test_public_roadmap_is_not_internal_phases() -> None:
    items = roadmap_items()
    assert items
    areas = {i["area"] for i in items}
    assert {"Engines", "Scanner", "Benchmark", "Launch"} <= areas
    statuses = {i["status"] for i in items}
    assert statuses <= {"done", "in-progress", "planned"}
    for status in statuses:
        assert EN.get(f"mkt_roadmap_status_{status}")
    html = render_public("roadmap", site=StaticSite())
    assert not re.search(r"W-\d\d", html)


def test_auth_panel_copy_is_not_local_only() -> None:
    assert "Runs on Ollama" not in EN["auth_point_ollama"]
    src = (ROOT / "llm_localizator" / "web" / "shell.py").read_text(encoding="utf-8")
    assert "Runs on Ollama" not in src
