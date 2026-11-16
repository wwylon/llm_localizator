"""Webhook deliveries are logged without leaking URL query tokens."""

from __future__ import annotations

import pytest
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from llm_localizator.ops.notify import notify_webhook, read_delivery_log


def _server(status: int):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(status)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_success_and_http_error_are_logged(tmp_path) -> None:
    log = tmp_path / "hook.jsonl"
    for status in (200, 500):
        srv = _server(status)
        try:
            url = f"http://127.0.0.1:{srv.server_port}/hook?token=SECRET"
            notify_webhook(url, {"event": "x.done"}, log_path=log)
        finally:
            srv.shutdown()
    rows = read_delivery_log(log)
    assert [r["ok"] for r in rows] == [False, True]  # newest first
    assert rows[0]["status"] == 500 and rows[1]["status"] == 200
    assert all("SECRET" not in r["url"] and r["event"] == "x.done" for r in rows)
    assert "SECRET" not in log.read_text(encoding="utf-8")


def test_connection_failure_and_refused_url_are_logged(tmp_path) -> None:
    log = tmp_path / "hook.jsonl"
    srv = _server(200)
    port = srv.server_port
    srv.shutdown()
    srv.server_close()
    notify_webhook(f"http://127.0.0.1:{port}/h", {"command": "sync"}, log_path=log)
    notify_webhook("http://10.0.0.5/h", {"event": "y"}, log_path=log)
    rows = read_delivery_log(log)
    assert len(rows) == 2 and not any(r["ok"] for r in rows)
    assert "private" in rows[0]["error"]
    assert rows[1]["event"] == "sync" and rows[1]["error"]


@pytest.mark.slow
def test_no_log_path_and_log_trimming(tmp_path) -> None:
    notify_webhook("http://10.0.0.5/h", {"event": "y"})  # no log_path: silent
    assert read_delivery_log(tmp_path / "missing.jsonl") == []
    log = tmp_path / "hook.jsonl"
    for i in range(450):
        notify_webhook("http://10.0.0.5/h", {"event": f"e{i}"}, log_path=log)
    rows = read_delivery_log(log, limit=1000)
    assert len(rows) <= 400 and rows[0]["event"] == "e449"
