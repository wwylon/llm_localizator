"""Wave 3: dashboard aggregate + server-side message search modes."""

from __future__ import annotations

from .test_w08 import _request, auth_server  # noqa: F401


def test_dashboard_aggregate(auth_server) -> None:
    port, _cfg = auth_server
    status, payload, _ = _request(port, "/api/dashboard")
    assert status == 200, payload
    assert payload.get("ok") is True
    assert "lite" in payload and "stats" in payload
    assert "review" in payload


def test_messages_fuzzy_mode(auth_server) -> None:
    port, _cfg = auth_server
    status, payload, _ = _request(
        port, "/api/messages?locales=pl&namespace=app&q=greet&mode=fuzzy&limit=50",
    )
    assert status == 200, payload
    assert "rows" in payload
    assert payload["counts"]["total"] >= 0
