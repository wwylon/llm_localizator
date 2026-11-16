"""Landing-page sections built from repo data: engines, benchmark, roadmap, formats.

Kept apart from ``marketing.py`` so the page renderers stay readable. Copy lives
in the ``mkt_*`` keys of the EN UI catalogue; data comes from the built-in
engine files and ``marketing_content/roadmap.json``. Benchmark numbers are the
held-out figures in docs/scanners.md (scanner v38, 2026-11-11); update both together.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from ..engines import _BUILTIN, Engine, _load_dir

_ROADMAP = Path(__file__).resolve().parent / "marketing_content" / "roadmap.json"

# Every canonical adapter id -> blurb key (tests assert full coverage).
FORMAT_BLURBS: dict[str, str] = {
    "android-xml": "mkt_fmt_android",
    "arb": "mkt_fmt_arb",
    "chrome-messages": "mkt_fmt_chrome_messages",
    "csv": "mkt_fmt_csv",
    "go-i18n": "mkt_fmt_go_i18n",
    "ios-strings": "mkt_fmt_ios_strings",
    "ios-stringsdict": "mkt_fmt_ios_stringsdict",
    "json-flat": "mkt_fmt_json_flat",
    "json-nested": "mkt_fmt_json_nested",
    "multilang-json": "mkt_fmt_multilang_json",
    "php-array": "mkt_fmt_php_array",
    "po": "mkt_fmt_po",
    "properties": "mkt_fmt_properties",
    "qt-ts": "mkt_fmt_qt_ts",
    "resx": "mkt_fmt_resx",
    "xcstrings": "mkt_fmt_xcstrings",
    "xliff": "mkt_fmt_xliff",
    "yaml": "mkt_fmt_yaml",
}

# Held-out scanner benchmark (docs/scanners.md, "Held-out by storage pattern").
BENCH_STATS = (
    ("0.91", "mkt_bench_precision"),
    ("12", "mkt_bench_projects"),
    ("0.34", "mkt_bench_recall"),
)


def _t(labels: dict[str, str], key: str) -> str:
    return labels.get(key, key)


def builtin_engines() -> list[Engine]:
    """Shipped engines only (never the user's engine directory), local first."""
    engines = _load_dir(_BUILTIN, "builtin").values()
    return sorted(engines, key=lambda e: (e.cloud and e.vram_gib == 0, e.cloud, e.vram_gib, e.id))


def _requirement(labels: dict[str, str], engine: Engine) -> str:
    parts: list[str] = []
    if engine.vram_gib:
        parts.append(_t(labels, "mkt_engine_req_gpu").format(gib=f"{engine.vram_gib:g}"))
    if engine.api_key_env:
        parts.append(_t(labels, "mkt_engine_req_key").format(env=engine.api_key_env))
    return " + ".join(parts)


def engines_section(labels: dict[str, str]) -> str:
    rows = "".join(
        f'<tr data-engine="{escape(e.id)}" data-status="{escape(e.status)}">'
        f"<td><code>{escape(e.id)}</code><div class=\"mkt-engine-name\">{escape(e.name)}</div></td>"
        f'<td><span class="mkt-badge-status is-{escape(e.status)}">'
        f'{escape(_t(labels, "mkt_engine_status_" + e.status))}</span></td>'
        f"<td>{escape(_requirement(labels, e))}</td>"
        f"<td>{escape(e.summary)}</td></tr>"
        for e in builtin_engines()
    )
    heads = "".join(
        f'<th scope="col">{escape(_t(labels, key))}</th>'
        for key in ("mkt_engine_th_engine", "mkt_engine_th_status", "mkt_engine_th_needs", "mkt_engine_th_note")
    )
    return (
        '<section class="mkt-section mkt-section-alt" id="engines">'
        '<div class="mkt-wrap">'
        f'<span class="kicker">{escape(_t(labels, "mkt_nav_engines"))}</span>'
        f'<h2>{escape(_t(labels, "mkt_engines_h2"))}</h2>'
        f'<p class="lede">{escape(_t(labels, "mkt_engines_lede"))}</p>'
        '<div class="mkt-table-wrap"><table class="api-table mkt-engines">'
        f"<thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table></div>"
        f'<pre class="install-cmd"><code>llm-localizator engine list\n'
        f"llm-localizator engine recommend\n"
        f"llm-localizator engine apply local-8gb</code></pre>"
        f'<p class="public-meta">{escape(_t(labels, "mkt_engines_status_note"))}</p>'
        "</div></section>"
    )


def bench_section(labels: dict[str, str], docs_url: str) -> str:
    stats = "".join(
        '<div class="mkt-stat">'
        f'<div class="mkt-stat-num">{escape(num)}</div>'
        f'<div class="mkt-stat-label">{escape(_t(labels, key))}</div></div>'
        for num, key in BENCH_STATS
    )
    tiers = "".join(
        f"<li>{escape(_t(labels, key))}</li>"
        for key in ("mkt_bench_tier_supported", "mkt_bench_tier_basic", "mkt_bench_tier_gaps")
    )
    return (
        '<section class="mkt-section" id="benchmark">'
        '<div class="mkt-wrap">'
        f'<span class="kicker">{escape(_t(labels, "mkt_nav_benchmark"))}</span>'
        f'<h2>{escape(_t(labels, "mkt_bench_h2"))}</h2>'
        f'<p class="lede">{escape(_t(labels, "mkt_bench_lede"))}</p>'
        f'<div class="mkt-stats-grid">{stats}</div>'
        f'<ul class="mkt-bench-tiers">{tiers}</ul>'
        f'<p class="public-meta">{escape(_t(labels, "mkt_bench_method"))} '
        f'<a href="{escape(docs_url)}/scanners.md" target="_blank" rel="noopener">'
        "docs/scanners.md</a></p>"
        "</div></section>"
    )


def roadmap_items() -> list[dict[str, str]]:
    """Public roadmap: ``marketing_content/roadmap.json`` (never plan/)."""
    try:
        raw = json.loads(_ROADMAP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    return [i for i in items or [] if isinstance(i, dict) and i.get("id")]


def roadmap_list(labels: dict[str, str]) -> str:
    rows: list[str] = []
    for item in roadmap_items():
        status = str(item.get("status", "planned"))
        done = "yes" if status == "done" else "no"
        rows.append(
            f'<li class="roadmap-row is-{"done" if done == "yes" else "todo"}" '
            f'data-item="{escape(str(item["id"]))}" data-status="{escape(status)}" data-done="{done}">'
            f'<span class="roadmap-id">{escape(str(item.get("area", "")))}</span>'
            f'<span class="roadmap-title"><strong>{escape(str(item.get("title", "")))}</strong>'
            f' {escape(str(item.get("detail", "")))}</span>'
            f'<span class="roadmap-status">{escape(_t(labels, "mkt_roadmap_status_" + status))}</span>'
            "</li>"
        )
    return f'<ul class="roadmap-list">{"".join(rows)}</ul>'
