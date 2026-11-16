"""Webhook envelope, slack format and event emission (C-017)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from llm_localizator.ops.notify import envelope, notify_webhook


def _serve():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["sig"] = self.headers.get("X-LLM-Localizator-Signature")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def test_envelope_keeps_old_fields():
    env = envelope({"event": "source.changed", "added": 2}, "p")
    assert env["event"] == "source.changed" and env["project"] == "p" and env["added"] == 2
    assert env["data"] == {"added": 2} and env["ts"]


def test_command_payload_gets_op_event():
    assert envelope({"command": "translate"}, "p")["event"] == "op.translate"


@pytest.mark.parametrize("fmt", ["json", "slack"])
def test_send_formats(monkeypatch, fmt):
    monkeypatch.setenv("LLM_LOCALIZE_WEBHOOK_SECRET", "k")
    srv, seen = _serve()
    try:
        notify_webhook(f"http://127.0.0.1:{srv.server_port}/", {"event": "x", "n": 1}, project="p", fmt=fmt)
    finally:
        srv.shutdown()
    if fmt == "slack":
        assert list(seen["body"]) == ["text"] and "x" in seen["body"]["text"]
        assert seen["sig"] is None
    else:
        assert seen["body"]["event"] == "x" and seen["body"]["data"] == {"n": 1}
        assert seen["sig"].startswith("sha256=")


def test_plain_call_unchanged():
    srv, seen = _serve()
    try:
        notify_webhook(f"http://127.0.0.1:{srv.server_port}/", {"a": 1})
    finally:
        srv.shutdown()
    assert seen["body"] == {"a": 1}
