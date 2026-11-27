"""The multi-page shell. `/` redirects to the dashboard."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.web import build_state
from llm_localizator.web.server import _Handler
from llm_localizator.web.shell import ROUTES


@pytest.fixture
def shell_port(tmp_path: Path, make_config):
    cfg = make_config(tmp_path)
    (tmp_path / "messages" / "en").mkdir(parents=True)
    (tmp_path / "messages" / "en" / "app.json").write_text(
        json.dumps({"greet": "Hello"}), encoding="utf-8",
    )
    handler = type("Handler", (_Handler,), {
        "states": {"testproj": build_state(cfg)},
        "default_project": "testproj",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _get(port: int, path: str) -> tuple[int, str, bytes]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def _get_no_redirect(port: int, path: str) -> tuple[int, str, bytes]:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with opener.open(req) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def test_stylesheet_is_local_css(shell_port: int) -> None:
    status, ctype, body = _get(shell_port, "/static/app.css")
    assert status == 200
    assert "text/css" in ctype
    text = body.decode("utf-8")
    assert "--color-accent" in text
    assert "http://" not in text
    assert "https://" not in text
    assert "font-display: optional" in text


def test_static_asset_answers_304_for_a_matching_etag(shell_port: int) -> None:
    url = f"http://127.0.0.1:{shell_port}/static/app.css"
    with urllib.request.urlopen(url) as resp:
        etag = resp.headers.get("ETag")
    assert etag
    req = urllib.request.Request(url, headers={"If-None-Match": etag})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 304
    stale = urllib.request.Request(url, headers={"If-None-Match": '"nope"'})
    with urllib.request.urlopen(stale) as resp:
        assert resp.status == 200


def test_fonts_and_versioned_css_are_cached(shell_port: int) -> None:
    font = urllib.request.Request(
        f"http://127.0.0.1:{shell_port}/static/fonts/Barlow-Regular.woff2",
    )
    with urllib.request.urlopen(font) as resp:
        assert resp.status == 200
        cache = resp.headers.get("Cache-Control", "")
        assert "immutable" in cache
        assert "no-store" not in cache
    css = urllib.request.Request(
        f"http://127.0.0.1:{shell_port}/static/app.css?v=1",
    )
    with urllib.request.urlopen(css) as resp:
        assert "immutable" in (resp.headers.get("Cache-Control") or "")
    bare = urllib.request.Request(
        f"http://127.0.0.1:{shell_port}/static/app.css",
    )
    with urllib.request.urlopen(bare) as resp:
        assert resp.headers.get("Cache-Control") == "no-cache"
    html_req = urllib.request.Request(f"http://127.0.0.1:{shell_port}/app")
    with urllib.request.urlopen(html_req) as resp:
        assert resp.headers.get("Cache-Control") == "no-store"


def test_shell_script_is_javascript(shell_port: int) -> None:
    status, ctype, body = _get(shell_port, "/static/shell.js")
    assert status == 200
    assert "javascript" in ctype
    assert b"llm_project" in body
    assert b"llmNavigate" in body
    assert b"http://" not in body
    assert b"https://" not in body


def test_design_bundle_is_not_served(shell_port: int) -> None:
    for path in ("/_ds_bundle.js", "/static/_ds_bundle.js", "/editor.dc.html"):
        status, _, _ = _get(shell_port, path)
        assert status == 404, path


def test_editor_is_the_shell(shell_port: int) -> None:
    status, ctype, body = _get(shell_port, "/app/editor")
    assert status == 200
    assert "text/html" in ctype
    html = body.decode("utf-8")
    hidden = {"login", "register", "pending", "setup"}
    for route in ROUTES:
        if route.id in hidden:
            assert f'data-route="{route.id}"' not in html
        else:
            assert f'data-route="{route.id}"' in html
    assert 'id="page-body"' in html
    assert "W-02 fills this page." not in html
    assert 'id="shell-user"></div>' in html
    assert "alex.morgan" not in html
    assert "bridge" not in html
    assert "X-LLM-Token" in html
    srcs = re.findall(r'<script src="([^"]+)"', html)
    bare = [src.split("?", 1)[0] for src in srcs]
    assert "/static/shell.js" in bare
    assert "/static/editor.js" in bare
    assert all(src.startswith("/static/") for src in srcs)
    assert "/static/app.css?v=" in html
    assert 'rel="preload"' in html
    assert "Barlow-Regular.woff2" in html


def test_root_redirects_to_the_dashboard(shell_port: int) -> None:
    status, _, body = _get(shell_port, "/")
    assert status == 200
    html = body.decode("utf-8")
    assert 'data-page="dashboard"' in html
    assert 'id="page-body"' in html
    assert "W-02 fills this page." not in html


def test_empty_states_name_their_phase(shell_port: int) -> None:
    _, _, login = _get(shell_port, "/login")
    assert b'data-page="login"' in login
    assert b"/static/auth.js" in login
    assert b"W-08 fills this page." not in login
    # Marketing paths 302 to the marketing port when configured; without
    # marketing_port they are not app shell routes (ADR-45).
    status, _, _ = _get_no_redirect(shell_port, "/landing")
    assert status == 404
    status, _, _ = _get_no_redirect(shell_port, "/how-it-works")
    assert status == 404
    _, _, workflow = _get(shell_port, "/app/workflow")
    assert b'data-page="workflow"' in workflow
    assert b"/static/workflow.js" in workflow
    assert b"W-10 fills this page." not in workflow


def test_trailing_slash_normalizes_under_locale_prefix(shell_port: int) -> None:
    # Bare /app/.../ gains a locale prefix (302). Prefixed trailing slash is
    # stripped by split_ui_locale_path and still serves the shell (ADR-108).
    status, _, _ = _get_no_redirect(shell_port, "/app/editor/")
    assert status == 302
    status, _, body = _get(shell_port, "/en/app/editor/")
    assert status == 200
    assert b'data-page="editor"' in body


@pytest.mark.serial_web
@pytest.mark.xdist_group("serial_web")
def test_post_without_token_is_refused(shell_port: int) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{shell_port}/api/ops/status",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    else:
        raise AssertionError("expected 403")


def test_shell_script_parses() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    path = Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "shell.js"
    proc = subprocess.run(
        [node, "--check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_every_page_script_is_served() -> None:
    from llm_localizator.web.server import _SHELL_STATIC
    from llm_localizator.web.shell import _PAGE_SCRIPTS

    missing = sorted({s for scripts in _PAGE_SCRIPTS.values() for s in scripts} - set(_SHELL_STATIC))
    assert not missing, f"page scripts the server would 404: {missing}"
