"""Plan-review-7 phase 2 (web): targeted writes, lock use, status codes."""

from __future__ import annotations

import json

from llm_localizator.web.plurals import joined_value

from .test_w08 import _request, auth_server  # noqa: F401  (fixture re-export)


def test_joined_value_null_prefix_keeps_source_prefix() -> None:
    source = "You have {n, plural, one {# item} other {# items}} left"
    out = joined_value(
        source, {"one": "a", "other": "b"},
        {"pluralPrefix": None, "pluralSuffix": None}, None,
    )
    assert out is not None and "None" not in out
    assert out.startswith("You have ") and out.endswith(" left")


def test_mark_intentional_writes_only_that_key(auth_server) -> None:
    port, cfg = auth_server
    root = cfg.root / "messages"
    (root / "en" / "app.json").write_text(
        json.dumps({"greet": "Hello", "bye": "Bye", "extra": "Extra"}), encoding="utf-8",
    )
    (root / "de" / "app.json").write_text(json.dumps({"greet": "Hallo"}), encoding="utf-8")
    status, payload, _ = _request(port, "/api/mark-intentional", method="POST", body={
        "locale": "de", "namespace": "app", "key": "bye",
    })
    assert status == 200, payload
    data = json.loads((root / "de" / "app.json").read_text(encoding="utf-8"))
    assert data == {"greet": "Hallo", "bye": "Bye"}


def test_branches_track_invalid_name_is_400(auth_server) -> None:
    port, _cfg = auth_server
    status, payload, _ = _request(
        port, "/api/branches/track", method="POST", body={"name": "../bad"},
    )
    assert status == 400, payload


def test_screenshot_upload_reports_context_failure(auth_server) -> None:
    import base64

    port, cfg = auth_server
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    status, payload, _ = _request(port, "/api/screenshot-upload", method="POST", body={
        "namespace": "app", "key": "does-not-exist", "screen": "s1",
        "data": base64.b64encode(png).decode("ascii"),
    })
    # No context dir configured, or key unknown: either way a 400, never a fake ok.
    assert status == 400, payload
