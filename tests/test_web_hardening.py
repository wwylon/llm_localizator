"""Security headers and POST body caps of the loopback web server."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from llm_localizator.web import build_state
from llm_localizator.web.request_guard import (
    BODY_LIMIT_DEFAULT,
    BODY_LIMIT_FILES,
    SECURITY_HEADERS,
    max_body_bytes,
)
from llm_localizator.web.server import _Handler


def test_body_limit_is_small_for_json_and_large_for_file_routes() -> None:
    assert max_body_bytes("/api/set") == BODY_LIMIT_DEFAULT
    assert max_body_bytes("/api/import") == BODY_LIMIT_FILES
    assert max_body_bytes("/api/screenshot-upload") == BODY_LIMIT_FILES
    assert max_body_bytes("/api/ops/export") == BODY_LIMIT_FILES
    assert BODY_LIMIT_DEFAULT < BODY_LIMIT_FILES


def _serve(tmp_path, make_config):
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_responses_carry_security_headers_and_oversized_posts_are_refused(
    tmp_path, make_config,
) -> None:
    server, port = _serve(tmp_path, make_config)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/ops/status",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-LLM-Token": "secret-token"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            for name, value in SECURITY_HEADERS.items():
                assert resp.headers.get(name) == value

        big = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/set",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-LLM-Token": "secret-token",
                "Content-Length": str(BODY_LIMIT_DEFAULT + 1),
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(big)
        except urllib.error.HTTPError as exc:
            assert exc.code == 413
            assert exc.headers.get("X-Frame-Options") == "DENY"
        else:
            raise AssertionError("expected 413")
    finally:
        server.shutdown()


def test_screenshot_route_refuses_paths_outside_the_context_folder(tmp_path, make_config) -> None:
    from llm_localizator.projects.config import ProjectConfig  # noqa: F401  (config type used by make_config)

    cfg = make_config(tmp_path, context_dir=tmp_path / "context")
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "ok.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")
    (tmp_path / "messages" / "en").mkdir(parents=True)
    (tmp_path / "messages" / "en" / "app.json").write_text(json.dumps({"a": "A"}), encoding="utf-8")
    handler = type("Handler", (_Handler,), {
        "states": {"testproj": build_state(cfg)}, "default_project": "testproj", "session_token": "",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def get(rel: str) -> int:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/screenshot?file={rel}") as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    try:
        assert get("ok.png") == 200
        assert get("..%2Fsecret.txt") == 403
        assert get("..%5Csecret.txt") in (403, 404)
        assert get("%2E%2E%2Fsecret.txt") == 403
    finally:
        server.shutdown()


def test_cors_header_only_for_same_origin_overlay_or_login(tmp_path, make_config) -> None:
    server, port = _serve(tmp_path, make_config)
    base = f"http://127.0.0.1:{port}"

    def acao(path: str, origin: str) -> str | None:
        req = urllib.request.Request(base + path, headers={"Origin": origin}, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.headers.get("Access-Control-Allow-Origin")
        except urllib.error.HTTPError as exc:
            return exc.headers.get("Access-Control-Allow-Origin")

    try:
        assert acao("/api/version", base) == base                      # same origin
        assert acao("/api/version", "http://localhost:3000") is None   # another local page: no read access
        assert acao("/api/auth/login", "http://localhost:3000") == "http://localhost:3000"
    finally:
        server.shutdown()


def test_token_file_is_written_and_stays_readable_by_its_owner(tmp_path, make_config) -> None:
    from llm_localizator.web.request_guard import _install_session_token

    cfg = make_config(tmp_path)
    token = _install_session_token(cfg)
    path = cfg.state_root() / "web.token"
    assert path.read_text(encoding="utf-8").strip() == token
    path.write_text("again\n", encoding="utf-8")  # the owner can still write it
