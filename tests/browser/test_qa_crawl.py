"""[qa]-driven QA crawl against a tiny static site (plan Part C, C7; ADR-119).

The site uses the shipped runtime (ADR-118) with a pseudo en-XX catalogue and has:
a catalogued heading, a hardcoded literal, server text fetched from a JSON API,
text revealed by a click, and a narrow box that clips its Arabic label.
"""

from __future__ import annotations

import functools
import json
import shutil
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.ops.source_ops import op_pseudo
from llm_localizator.ops.types import PseudoRequest
from llm_localizator.projects import load_config
from llm_localizator.web_runtime import RUNTIME_FILE

pytest.importorskip("playwright.sync_api")

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments" / "hardcoded_visible"
if not EXPERIMENTS.is_dir():
    pytest.skip("needs experiments/hardcoded_visible (dev checkout only)", allow_module_level=True)

INDEX = """<!doctype html>
<html><head><meta charset="utf-8">
<style>.narrow { width: 60px; overflow: hidden; white-space: nowrap; }</style>
<script src="/js/i18n.config.js"></script><script src="/js/i18n.js"></script>
</head><body>
<h1 data-i18n="hero">Make it big</h1>
<div class="narrow" data-i18n="long">Short</div>
<p>Hardcoded footer text</p>
<div id="status"></div>
<span id="paper"></span>
<button id="more" data-i18n="more">More</button>
<p id="extra" hidden>Revealed after click</p>
<script>
  fetch('/api/status.json').then(r => r.json()).then(j => {
    document.getElementById('status').textContent = j.message;
    document.getElementById('paper').textContent = j.title;
  });
  document.getElementById('more').addEventListener('click', () => {
    document.getElementById('extra').hidden = false;
  });
</script>
</body></html>
"""

EN = {"hero": "Make it big", "long": "Short", "more": "More"}
AR = {"hero": "اجعلها كبيرة", "long": "نص عربي طويل جدا لا يتسع في الصندوق الضيق", "more": "المزيد"}


@pytest.fixture
def site(tmp_path: Path):
    root = tmp_path / "site"
    (root / "js").mkdir(parents=True)
    (root / "locales").mkdir()
    (root / "api").mkdir()
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    shutil.copy(RUNTIME_FILE, root / "js" / "i18n.js")
    (root / "js" / "i18n.config.js").write_text(
        "window.I18N_CONFIG = { base: '/locales', locales: ['en', 'ar'], qaLocales: ['en-XX'] };\n",
        encoding="utf-8")
    (root / "locales" / "en.json").write_text(json.dumps(EN), encoding="utf-8")
    (root / "locales" / "ar.json").write_text(json.dumps(AR, ensure_ascii=False), encoding="utf-8")
    (root / "api" / "status.json").write_text(
        json.dumps({"message": "Server says hello world", "title": "Notes on quantum gravity"}), encoding="utf-8")
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    toml = tmp_path / ".llm-localize.toml"
    toml.write_text(f"""[project]
name = "qa-fixture"
source_locale = "en"
[catalog]
format = "json-flat"
path = "site/locales/{{locale}}.json"
[locales]
targets = ["ar"]
[scan]
src_dirs = ["site"]
[qa]
base_url = "http://127.0.0.1:{port}"
pages = ["/"]
locale_mode = "query"
[qa.clicks]
"/" = ["#more"]
[qa.wait_for]
"/" = "#paper:not(:empty)"
""", encoding="utf-8")
    cfg = load_config(toml)
    assert op_pseudo(cfg, PseudoRequest(locale="en-XX")).ok
    yield cfg, tmp_path
    server.shutdown()
    server.server_close()


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):  # noqa: D401 - keep pytest output clean
        pass


def _qa_crawl():
    if str(EXPERIMENTS) not in sys.path:
        sys.path.insert(0, str(EXPERIMENTS))
    import qa_crawl

    return qa_crawl


def test_qa_crawl_reports_leftovers_dynamic_text_and_rtl_clipping(site) -> None:
    cfg, tmp = site
    try:
        summary = _qa_crawl().run_qa(cfg, out_dir=tmp / "out", serve=False)
    except Exception as exc:  # noqa: BLE001
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"Chromium unavailable: {exc}")
        raise
    out = tmp / "out"
    left = json.loads((out / "leftovers.json").read_text(encoding="utf-8"))
    by_text = {item["text"]: item for item in left["leftovers"]}
    assert left["pages"][0]["locale_ready"] is True
    # Catalogued text renders as X markers and is not a leftover.
    assert "Make it big" not in by_text
    assert left["catalogued_nodes"] >= 2
    # A literal in the source is a leftover the scanner can find.
    assert by_text["Hardcoded footer text"]["literal"] is True
    assert by_text["Hardcoded footer text"]["file"] == "site/index.html"
    assert by_text["Hardcoded footer text"]["line"] == 8
    # Server text is not in any source file: dynamic.
    assert by_text["Server says hello world"]["literal"] is False
    dynamic = json.loads((out / "dynamic_text.json").read_text(encoding="utf-8"))
    assert [i["text"] for i in dynamic["items"]] == ["Server says hello world"]
    # B1 (ADR-133): the message field is API copy; the title is API data, kept apart.
    assert dynamic["items"][0]["origin"] == "api-copy"
    assert dynamic["items"][0]["producer"] == "api:/api/status.json#message"
    data = json.loads((out / "data_text.json").read_text(encoding="utf-8"))
    assert [(i["text"], i["origin"]) for i in data["items"]] == [("Notes on quantum gravity", "api-data")]
    # Text revealed by a configured click is collected and attributed.
    assert by_text["Revealed after click"]["after_click"] == "#more"

    layout = json.loads((out / "layout.json").read_text(encoding="utf-8"))
    (ar,) = layout["locales"]
    page = ar["pages"][0]
    assert ar["locale"] == "ar" and ar["rtl"] is True
    assert page["dir"] == "rtl" and page["dir_ok"] is True
    clipped = [i for i in page["issues"] if i["kind"] == "clipped"]
    assert any("narrow" in i["selector"] for i in clipped), page["issues"]
    assert (out / page["screenshot"]).is_file()
    assert summary["dynamic"] == 1 and summary["layout"]["ar"]["issues"] >= 1
    assert "dynamic_text.json" in (out / "index.md").read_text(encoding="utf-8")


def test_default_out_dir_is_the_engine_data_home(site) -> None:
    cfg, _tmp = site
    out = _qa_crawl().default_out_dir(cfg)
    assert out.parent == Path(cfg.data_root()) / "qa"
    assert Path(cfg.root) not in out.parents


def test_page_url_modes(site) -> None:
    cfg, _tmp = site
    qa = cfg.qa
    mod = _qa_crawl()
    assert mod.page_url(qa, "/?tab=x", "en-XX").endswith("/?tab=x&lang=en-XX")
    qa.locale_mode = "path"
    assert mod.page_url(qa, "/library", "pl").endswith("/pl/library")
    qa.locale_mode = "storage"
    assert mod.page_url(qa, "/", "pl") == qa.base_url + "/"
