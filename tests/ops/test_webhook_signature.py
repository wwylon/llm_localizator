"""Webhook bodies are HMAC-signed when LLM_LOCALIZE_WEBHOOK_SECRET is set."""

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from llm_localizator.ops.notify import notify_webhook, sign_body


def _serve():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            seen["body"] = self.rfile.read(n)
            seen["sig"] = self.headers.get("X-LLM-Localizator-Signature")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def test_sign_body_matches_hmac():
    assert sign_body(b"x", "k") == "sha256=" + hmac.new(b"k", b"x", hashlib.sha256).hexdigest()


def test_signature_header_sent_when_secret_set(monkeypatch):
    monkeypatch.setenv("LLM_LOCALIZE_WEBHOOK_SECRET", "s3")
    srv, seen = _serve()
    try:
        notify_webhook(f"http://127.0.0.1:{srv.server_port}/", {"a": 1})
    finally:
        srv.shutdown()
    assert json.loads(seen["body"]) == {"a": 1}
    assert seen["sig"] == sign_body(seen["body"], "s3")


def test_no_header_without_secret(monkeypatch):
    monkeypatch.delenv("LLM_LOCALIZE_WEBHOOK_SECRET", raising=False)
    srv, seen = _serve()
    try:
        notify_webhook(f"http://127.0.0.1:{srv.server_port}/", {"a": 1})
    finally:
        srv.shutdown()
    assert seen["sig"] is None
