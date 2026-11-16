"""Wave 0 request timing helpers."""

from llm_localizator.web import timing as web_timing


def test_spans_noop_when_disabled():
    web_timing.reset(enabled=False)
    with web_timing.span("collect"):
        pass
    assert web_timing.spans_dict() == {}
    assert not web_timing.server_timing_header(0)
    web_timing.clear()


def test_spans_and_attach_when_enabled():
    web_timing.reset(enabled=True)
    with web_timing.span("collect"):
        pass
    spans = web_timing.spans_dict()
    assert "collect" in spans
    payload = web_timing.attach_timing({"ok": True}, response_bytes=12)
    assert "_timing" in payload
    assert payload["_timing"]["responseBytes"] == 12
    assert "collect" in (web_timing.server_timing_header(12) or "")
    web_timing.clear()
